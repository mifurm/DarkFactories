import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from nightshift.core.bus import sse_format, sse_stream
from nightshift.core.deps import get_plant
from nightshift.plant.runtime import PlantRuntime

router = APIRouter(tags=["DF-20 control tower"])
_streams_per_ip: dict[str, int] = {}
MAX_STREAMS_PER_IP = 12


@router.get("/api/tower/snapshot", tags=["DF-20 control tower"])
async def snapshot(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return pr.snapshot(full=True)


@router.get("/api/tower/map")
async def plant_map(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    """Static layout metadata for the SVG plant map (areas, lines, assets, zones, flow edges)."""
    cfg = pr.cfg
    areas: dict[str, list[dict[str, Any]]] = {}
    for s in cfg.assets:
        areas.setdefault(s.area, []).append(
            {
                "id": s.id,
                "type": s.type,
                "line": s.line,
                "cell": s.cell,
                "zone": s.zone,
                "index": s.index,
                "name": s.name,
            }
        )
    return {
        "plant": cfg.plant_id,
        "name": cfg.name,
        "areas": areas,
        "zones": cfg.zones(),
        "stages": {k: list(v) for k, v in cfg.pools.items()},
    }


@router.get("/api/stream/plant")
async def stream_plant(request: Request, pr: PlantRuntime = Depends(get_plant)) -> StreamingResponse:
    """SSE: tick (1 Hz plant snapshot), agent events, ledger entries, alerts."""
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    if _streams_per_ip.get(ip, 0) >= MAX_STREAMS_PER_IP:
        from fastapi import HTTPException

        raise HTTPException(429, "too many concurrent streams from this address")
    _streams_per_ip[ip] = _streams_per_ip.get(ip, 0) + 1
    topics = {f"{pr.plant_id}/{t}" for t in ("tick", "agent", "ledger", "alert")}
    sub = pr.hub.subscribe(topics, maxsize=400)

    async def gen():
        try:
            yield sse_format("hello", {"plant": pr.plant_id, "t": pr.plant.t})
            yield sse_format("tick", pr.snapshot())
            async for frame in sse_stream(sub, keepalive_s=10, is_disconnected=request.is_disconnected):
                yield frame.replace(f"event: {pr.plant_id}/", "event: ")
        finally:
            _streams_per_ip[ip] = max(0, _streams_per_ip.get(ip, 1) - 1)

    async def passthrough():
        async for frame in gen():
            yield frame

    return StreamingResponse(
        passthrough(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


async def _noop() -> None:  # pragma: no cover
    await asyncio.sleep(0)
