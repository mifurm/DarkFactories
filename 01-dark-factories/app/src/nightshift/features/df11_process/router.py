from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from nightshift.core.deps import get_plant
from nightshift.features.df23_rbac.rbac import Identity, require
from nightshift.plant.runtime import PlantRuntime

router = APIRouter(prefix="/api/process", tags=["DF-11 process"])


class EnableBody(BaseModel):
    enabled: bool


@router.get("/summary")
async def summary(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    out = pr.process.summary()
    out["enabled"] = pr.process.enabled
    out["recipe"] = (
        pr.plant.assets[pr.process.pilot or pr.world().ids("PRESS")[0]].recipe if pr.world().ids("PRESS") else {}
    )
    return out


@router.post("/enable")
async def enable(
    body: EnableBody,
    pr: PlantRuntime = Depends(get_plant),
    ident: Identity = Depends(require("agent_toggle", "process.enable")),
) -> dict[str, Any]:
    pr.set_agent_enabled("process", body.enabled)
    return {"enabled": pr.process.enabled}


@router.post("/optimize")
async def optimize(
    pr: PlantRuntime = Depends(get_plant), ident: Identity = Depends(require("sim_control", "process.optimize"))
) -> dict[str, Any]:
    """Force one optimisation step now (twin-evaluated candidates; the resulting recipe change still needs approval under the default policy)."""
    pr.set_agent_enabled("process", True)
    pr.process.last_try = -(10**9)
    pr.process.trial = None
    plans = pr.supervisor.cycle()
    return {
        "plans": [p.public() for p in plans if p.proposals and p.proposals[0].agent == "process"][:2],
        "history": pr.process.summary()["history"][-5:],
    }
