from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from nightshift.core.deps import get_plant, get_rt
from nightshift.core.llm import narrate
from nightshift.features.df23_rbac.rbac import Identity, require
from nightshift.plant.runtime import PlantRuntime

router = APIRouter(prefix="/api/swarm", tags=["DF-04 swarm"])


class ToggleBody(BaseModel):
    enabled: bool


class WeightsBody(BaseModel):
    weights: dict[str, float] = Field(max_length=8)


class ExplainBody(BaseModel):
    plan_id: str


@router.get("/agents")
async def agents(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return pr.supervisor.info()


@router.post("/agents/{name}/toggle")
async def toggle(
    name: str,
    body: ToggleBody,
    pr: PlantRuntime = Depends(get_plant),
    ident: Identity = Depends(require("agent_toggle", "swarm.toggle")),
) -> dict[str, Any]:
    if not pr.set_agent_enabled(name, body.enabled):
        raise HTTPException(404, "unknown agent")
    pr.ledger.append(
        "system",
        f"Agent {name} {'enabled' if body.enabled else 'disabled'} by {ident.role}",
        agent=ident.subject,
        outcome="agent_toggle",
        sim_t=pr.plant.t,
    )
    return {"agent": name, "enabled": body.enabled}


@router.get("/plans")
async def plans(
    limit: int = 40, status: str | None = None, pr: PlantRuntime = Depends(get_plant)
) -> list[dict[str, Any]]:
    rows = [p for p in pr.supervisor.plans.values() if status in (None, "all") or p.status == status]
    return [p.public() for p in rows[-max(1, min(limit, 200)) :][::-1]]


@router.get("/plans/{plan_id}")
async def plan(plan_id: str, pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    p = pr.supervisor.plans.get(plan_id)
    if p is None:
        raise HTTPException(404, "unknown plan")
    return {**p.public(), "ledger": pr.ledger.query(corr=plan_id, limit=50, desc=False)["items"]}


@router.get("/weights")
async def weights(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return {
        "weights": pr.supervisor.weights,
        "meaning": "Objective weights of the explicit utility used in arbitration (EUR-denominated impact x weight).",
    }


@router.put("/weights")
async def set_weights(
    body: WeightsBody,
    pr: PlantRuntime = Depends(get_plant),
    ident: Identity = Depends(require("dial", "swarm.weights")),
) -> dict[str, Any]:
    for k, v in body.weights.items():
        if k not in pr.supervisor.weights or not 0.0 <= v <= 5.0:
            raise HTTPException(422, f"weight {k!r} unknown or outside 0..5")
        pr.supervisor.weights[k] = v
    return {"weights": pr.supervisor.weights}


@router.get("/blackboard")
async def blackboard(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return {k: v for k, v in pr.supervisor.board.facts.items() if k != "pdm.estimates"} | {
        "pdm.estimates": pr.supervisor.board.get("pdm.estimates", {})
    }


@router.post("/explain")
async def explain(body: ExplainBody, pr: PlantRuntime = Depends(get_plant), rt=Depends(get_rt)) -> dict[str, Any]:
    p = pr.supervisor.plans.get(body.plan_id)
    if p is None:
        raise HTTPException(404, "unknown plan")
    facts = p.public()
    nar = await narrate(
        rt.llm,
        "swarm.explain",
        facts,
        "Explain to a plant manager, in 3-4 sentences, what this plan does, how the agents arbitrated and why the policy decision was taken.",
        lambda f: f"{f['proposals'][0]['title']}: {f['proposals'][0]['rationale']}",
        max_tokens=450,
    )
    return {"plan_id": p.id, **nar.public()}
