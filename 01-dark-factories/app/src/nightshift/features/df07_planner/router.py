from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nightshift.core.deps import get_plant
from nightshift.features.df04_swarm.core import WorldView
from nightshift.features.df07_planner.scheduler import build_schedule, check_feasibility
from nightshift.plant.runtime import PlantRuntime

router = APIRouter(prefix="/api/planner", tags=["DF-07 planner"])


class ReplanBody(BaseModel):
    rule: str = "cr"


@router.get("/schedule")
async def schedule(rule: str = "cr", pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    if rule not in ("cr", "fifo"):
        raise HTTPException(422, "rule must be cr|fifo")
    w = WorldView(pr.plant)
    s = build_schedule(w, rule)
    return {
        **s.public(),
        "violations": check_feasibility(s, w),
        "machines": {m: {"free_at": round(ms.free_at), "last_family": ms.last_family} for m, ms in s.machines.items()},
    }


@router.get("/compare")
async def compare(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    w = WorldView(pr.plant)
    cr, fifo = build_schedule(w, "cr"), build_schedule(w, "fifo")
    return {
        "planner": {k: v for k, v in cr.public().items() if k != "slots"},
        "fifo": {k: v for k, v in fifo.public().items() if k != "slots"},
        "improvement": {
            "tardiness_min": round(fifo.tardiness_min - cr.tardiness_min, 1),
            "late_orders": fifo.late_orders - cr.late_orders,
            "tardiness_eur": round(fifo.tardiness_eur - cr.tardiness_eur, 0),
        },
    }


@router.get("/explain")
async def explain(order: str | None = None, pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    pr.planner.schedule = pr.planner.schedule or build_schedule(WorldView(pr.plant), "cr")
    pr.planner.baseline = pr.planner.baseline or build_schedule(WorldView(pr.plant), "fifo")
    return pr.planner.explain(order)


@router.post("/replan")
async def replan(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    pr.planner.last_plan_t = -(10**9)
    pr.planner.last_sig = ()
    plans = pr.supervisor.cycle()
    return {
        "plans": [p.public() for p in plans if p.proposals and p.proposals[0].agent == "planner"][:3],
        "replans": pr.planner.replans,
    }
