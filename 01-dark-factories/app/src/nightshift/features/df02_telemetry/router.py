import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from nightshift.core.bus import sse_format
from nightshift.core.deps import get_plant
from nightshift.features.df02_telemetry.uns import (
    ExternalStore,
    TelemetryMessage,
    build_tree,
    plant_topic,
    sim_messages,
    topic_for,
)
from nightshift.features.df23_rbac.rbac import Identity, require
from nightshift.plant.runtime import PlantRuntime

router = APIRouter(prefix="/api/telemetry", tags=["DF-02 telemetry"])
_external: dict[str, ExternalStore] = {}


class IngestBody(BaseModel):
    messages: list[dict[str, Any]] = Field(min_length=1, max_length=500)


def ext(pr: PlantRuntime) -> ExternalStore:
    return _external.setdefault(pr.plant_id, ExternalStore())


@router.get("/tree")
async def tree(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    latest = {m.topic: {"value": m.value, "unit": m.unit, "source": m.source} for m in sim_messages(pr.plant)}
    for t, v in ext(pr).latest().items():
        latest[t] = {"value": v["value"], "unit": "", "source": "external"}
    return {"plant": pr.plant_id, "topics": len(latest), "tree": build_tree(pr.cfg, latest)}


@router.get("/latest")
async def latest(prefix: str = "", limit: int = 200, pr: PlantRuntime = Depends(get_plant)) -> list[dict[str, Any]]:
    msgs = [m.model_dump() for m in sim_messages(pr.plant) if m.topic.startswith(prefix.lower())]
    return msgs[: max(1, min(limit, 1000))]


@router.get("/series")
async def series(topic: str, n: int = 120, pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    topic = topic.strip().lower()
    n = max(1, min(n, 1440))
    store = ext(pr)
    if topic in store.buf:
        return {"topic": topic, "source": "external", "points": store.series(topic, n)}
    parts = topic.split("/")
    if len(parts) != 7:
        raise HTTPException(422, "topic must have 7 levels")
    asset_id, metric = parts[5].upper(), parts[6]
    if asset_id in pr.plant.assets and pr.plant.store.has(asset_id, metric):
        vals = pr.plant.store.series(asset_id, metric, n)
        t0 = pr.plant.t - len(vals)
        return {
            "topic": topic,
            "source": "sim",
            "unit": "",
            "points": [{"t": t0 + i, "value": None if v != v else round(float(v), 4)} for i, v in enumerate(vals)],
        }
    if asset_id == "PLANT" and pr.plant.store.has("plant", metric):
        vals = pr.plant.store.series("plant", metric, n)
        return {
            "topic": topic,
            "source": "sim",
            "points": [{"t": pr.plant.t - len(vals) + i, "value": round(float(v), 4)} for i, v in enumerate(vals)],
        }
    raise HTTPException(404, "unknown topic")


@router.get("/aggregates")
async def aggregates(
    asset: str, metric: str, bucket: int = 15, buckets: int = 24, pr: PlantRuntime = Depends(get_plant)
) -> list[dict[str, Any]]:
    if not pr.plant.store.has(asset.upper(), metric):
        raise HTTPException(404, "unknown asset/metric")
    return pr.plant.store.aggregates(asset.upper(), metric, max(1, min(bucket, 240)), max(1, min(buckets, 96)))


@router.post("/ingest")
async def ingest(
    body: IngestBody,
    pr: PlantRuntime = Depends(get_plant),
    ident: Identity = Depends(require("ingest", "telemetry.ingest")),
) -> dict[str, Any]:
    prefix = f"contoso/{pr.cfg.site}/"
    allowed = [m for m in body.messages if str(m.get("topic", "")).lower().startswith(prefix)]
    res = ext(pr).ingest(allowed, source="http")
    res["rejected"] += len(body.messages) - len(allowed)
    if len(body.messages) != len(allowed):
        res["errors"].append(f"topics must start with {prefix}")
    return res


@router.get("/adapters")
async def adapters(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    e = ext(pr)
    return {
        "adapters": [
            {
                "name": "sim",
                "status": "active",
                "description": "Simulator SimSource publishing validated UNS messages",
                "topics": len(sim_messages(pr.plant)),
            },
            {
                "name": "http",
                "status": "active",
                "description": "POST /api/telemetry/ingest (validated, size/rate limited, RBAC)",
                "accepted": e.accepted,
                "rejected": e.rejected,
            },
            {
                "name": "mqtt",
                "status": "decoder-only",
                "description": "MQTT payload decoder implemented and tested; broker connection (Azure IoT Operations) not part of this deployment",
            },
            {
                "name": "eventhubs",
                "status": "decoder-only",
                "description": "Event Hubs / IoT Operations data-flow decoder implemented and tested; no Event Hub provisioned (cost/governance)",
            },
        ],
        "isa95": "enterprise/site/area/line/cell/asset/metric",
        "example_topic": topic_for(pr.cfg, pr.cfg.assets[0], "vibration_rms"),
        "plant_topic": plant_topic(pr.cfg, "power_kw"),
    }


@router.get("/stream")
async def stream(request: Request, pr: PlantRuntime = Depends(get_plant)) -> StreamingResponse:
    async def gen():
        yield ": connected\n\n"
        while not await request.is_disconnected():
            msgs = sim_messages(pr.plant)
            yield sse_format(
                "batch",
                {"t": pr.plant.t, "messages": [{"topic": m.topic, "value": m.value, "unit": m.unit} for m in msgs]},
            )
            await asyncio.sleep(2.0)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


def validate_message(raw: str) -> dict[str, Any]:
    return TelemetryMessage(**json.loads(raw)).model_dump()
