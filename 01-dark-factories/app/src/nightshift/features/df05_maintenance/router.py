from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from nightshift.core.deps import get_plant
from nightshift.features.df23_rbac.rbac import Identity, require
from nightshift.plant.runtime import PlantRuntime
from nightshift.sim.plant import ActionRejected

router = APIRouter(prefix="/api/maintenance", tags=["DF-05 maintenance"])


class WoBody(BaseModel):
    asset: str
    start_in_min: int = Field(default=30, ge=0, le=1440)
    duration_min: int | None = Field(default=None, ge=5, le=480)
    reason: str = Field(default="manual work order", max_length=200)


@router.get("/health")
async def health(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    w = pr.world()
    rows = pr.pdm.snapshot(w)
    return {
        "assets": rows,
        "alerts": pr.pdm.alert_log[-20:],
        "spares": [
            {"part": k, "on_hand": s["on_hand"], "min": s["min"], "lead_h": s["lead_h"]} for k, s in w.spares.items()
        ],
        "windows": [{"start_t": s, "end_t": e} for s, e in w.windows(1440)],
        "t": pr.plant.t,
    }


@router.get("/series")
async def series(
    asset: str, metric: str = "vibration_rms", n: int = 180, pr: PlantRuntime = Depends(get_plant)
) -> dict[str, Any]:
    a = asset.upper()
    if a not in pr.plant.assets or not pr.plant.store.has(a, metric):
        raise HTTPException(404, "unknown asset/metric")
    vals = pr.plant.store.series(a, metric, max(10, min(n, 1440)))
    return {
        "asset": a,
        "metric": metric,
        "t0": pr.plant.t - len(vals),
        "values": [None if v != v else round(float(v), 3) for v in vals],
    }


@router.get("/work-orders")
async def work_orders(pr: PlantRuntime = Depends(get_plant)) -> list[dict[str, Any]]:
    p = pr.plant
    return [
        {
            "id": w.id,
            "asset": w.asset,
            "start_t": w.start_t,
            "start_in_min": w.start_t - p.t,
            "duration": w.duration,
            "kind": w.kind,
            "reason": w.reason,
            "spare": w.spare,
            "tool": w.tool,
            "status": w.status,
            "created_by": w.created_by,
        }
        for w in sorted(p.work_orders.values(), key=lambda x: -x.start_t)
    ][:60]


@router.post("/work-orders")
async def create_wo(
    body: WoBody,
    pr: PlantRuntime = Depends(get_plant),
    ident: Identity = Depends(require("sim_control", "maintenance.work_order")),
) -> dict[str, Any]:
    try:
        return pr.direct_action(
            {
                "kind": "schedule_maintenance",
                "asset": body.asset.upper(),
                "start_t": pr.plant.t + body.start_in_min,
                "duration": body.duration_min,
                "reason": body.reason,
                "spare": "SP-BEARING" if body.asset.upper().startswith(("CNC", "PRESS")) else None,
            },
            ident.subject,
        )
    except ActionRejected as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/signatures")
async def signatures(pr: PlantRuntime = Depends(get_plant)) -> list[dict[str, Any]]:
    return pr.library.public()
