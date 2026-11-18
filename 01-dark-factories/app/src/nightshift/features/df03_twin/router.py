from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from nightshift.core.deps import get_plant
from nightshift.features.df19_kpi.engine import KpiEngine
from nightshift.plant.models import Action
from nightshift.plant.runtime import PlantRuntime
from nightshift.sim.plant import CONTROL_ACTIONS

router = APIRouter(prefix="/api/twin", tags=["DF-03 twin"])


class WhatIfBody(BaseModel):
    actions: list[dict[str, Any]] = Field(min_length=1, max_length=6)
    horizon_min: int = Field(default=240, ge=15, le=720)


class ForkBody(BaseModel):
    minutes: int = Field(default=120, ge=1, le=720)


@router.get("/graph")
async def graph(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return pr.twin.graph()


@router.post("/whatif")
async def whatif(body: WhatIfBody, pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    acts = []
    for a in body.actions:
        if a.get("kind") not in CONTROL_ACTIONS:
            raise HTTPException(422, f"unknown action kind {a.get('kind')!r}; allowed: {list(CONTROL_ACTIONS)}")
        acts.append(
            Action(
                a["kind"],
                {k: v for k, v in a.items() if k not in ("kind", "target")},
                a.get("asset") or a.get("target"),
            )
        )
    return pr.twin.simulate_ahead(acts, body.horizon_min, estimates=pr.supervisor.board.get("pdm.estimates", {}))


@router.post("/fork")
async def fork(body: ForkBody, pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    f = pr.twin.fork_estimated(pr.supervisor.board.get("pdm.estimates", {}))
    snap0 = f.current_snapshot()
    f.run(body.minutes)
    k = KpiEngine.compute(f, base=snap0, cur=f.current_snapshot())
    return {
        "forked_at_t": pr.plant.t,
        "minutes": body.minutes,
        "live_t_unchanged": pr.plant.t,
        "kpi": k["plant_kpi"],
        "failures": [e for e in f.events if e["kind"] == "failure"][:5],
    }
