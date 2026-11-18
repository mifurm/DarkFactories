from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from nightshift.core.deps import get_plant
from nightshift.plant.models import Action
from nightshift.plant.runtime import PlantRuntime
from nightshift.sim.plant import CONTROL_ACTIONS

router = APIRouter(prefix="/api/safety", tags=["DF-10 safety"])


class CheckBody(BaseModel):
    kind: str
    asset: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


@router.get("/summary")
async def summary(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return pr.safety.summary(pr.world())


@router.get("/cyber")
async def cyber(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return pr.safety.cyber


@router.post("/check")
async def check(body: CheckBody, pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    """Guard tester: would the Safety Sentinel / policy hard-rules reject this action? (no side effects)"""
    if body.kind not in CONTROL_ACTIONS:
        raise HTTPException(422, f"unknown action kind; allowed: {list(CONTROL_ACTIONS)}")
    a = Action(body.kind, {**body.params, **({"asset": body.asset} if body.asset else {})}, body.asset)
    viol = pr.safety.check(a, pr.world())
    return {
        "allowed": not any(v["severity"] == "deny" for v in viol),
        "needs_human": any(v["severity"] == "approve" for v in viol),
        "violations": viol,
    }
