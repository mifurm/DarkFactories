from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from nightshift.core.deps import get_plant
from nightshift.features.df12_policy.engine import DEFAULT_POLICY_PATH, load_rules
from nightshift.features.df23_rbac.rbac import Identity, require
from nightshift.plant.models import Action, Plan, Proposal
from nightshift.plant.runtime import PlantRuntime

router = APIRouter(prefix="/api/policy", tags=["DF-12 policy"])


class DialBody(BaseModel):
    levels: dict[str, int] = Field(default_factory=dict, max_length=30)
    global_cap: int | None = Field(default=None, ge=0, le=5)


class KillBody(BaseModel):
    on: bool
    reason: str = Field(default="", max_length=200)


class BreakGlassBody(BaseModel):
    decision_class: str = "*"
    level: int = Field(default=5, ge=0, le=5)
    minutes: int = Field(default=30, ge=1, le=240)
    reason: str = Field(min_length=3, max_length=200)


class TimeboxBody(BaseModel):
    decision_class: str
    minutes: int = Field(default=120, ge=1, le=720)
    max_cost_eur: float = Field(default=1000, ge=0, le=20000)
    max_risk: float = Field(default=0.4, ge=0, le=1)


class RulesBody(BaseModel):
    yaml_text: str = Field(max_length=20000)


class EvalBody(BaseModel):
    decision_class: str
    risk: float = Field(default=0.2, ge=0, le=1)
    assets: int = Field(default=1, ge=0, le=20)
    cost_eur: float = Field(default=100, ge=0, le=100000)
    kind: str = "set_speed"
    params: dict[str, Any] = Field(default_factory=dict)
    target: str | None = None


def persist(pr: PlantRuntime) -> None:
    e = pr.policy
    pr.rt.writer.enqueue(
        "state",
        {
            "id": f"policy-{pr.plant_id}",
            "pk": "policy",
            "levels": e.levels,
            "global_cap": e.global_cap,
            "kill_switch": e.kill_switch,
            "kill_info": e.kill_info,
            "changes": e.changes[-30:],
            "grants": e.active_grants(pr.plant.t),
        },
    )


def _log(pr: PlantRuntime, ident: Identity, summary: str, outcome: str, payload: dict[str, Any] | None = None) -> None:
    pr.ledger.append(
        "system",
        summary,
        agent=ident.subject,
        outcome=outcome,
        payload=payload or {},
        sim_t=pr.plant.t,
        sim_time=pr.plant.now.isoformat(timespec="minutes"),
    )
    persist(pr)


@router.get("")
async def state(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return pr.policy.snapshot(pr.plant.t)


@router.get("/rules")
async def rules(pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    return {
        "yaml": DEFAULT_POLICY_PATH.read_text(),
        "version": pr.policy.version,
        "active": pr.policy.rules.model_dump(mode="json"),
    }


@router.put("/rules")
async def put_rules(
    body: RulesBody,
    pr: PlantRuntime = Depends(get_plant),
    ident: Identity = Depends(require("policy_edit", "policy.rules")),
) -> dict[str, Any]:
    try:
        new = load_rules(body.yaml_text)
    except (ValidationError, yaml.YAMLError, ValueError) as exc:
        raise HTTPException(422, f"invalid policy: {str(exc)[:400]}") from exc
    pr.policy.rules = new
    pr.policy.version = new.version
    for c, r in new.classes.items():
        pr.policy.levels.setdefault(c, r.level)
    _log(
        pr,
        ident,
        f"Policy rules replaced by {ident.role} (version {new.version})",
        "policy_updated",
        {"version": new.version},
    )
    return {"version": new.version, "classes": len(new.classes)}


@router.put("/dial")
async def dial(
    body: DialBody, pr: PlantRuntime = Depends(get_plant), ident: Identity = Depends(require("dial", "policy.dial"))
) -> dict[str, Any]:
    try:
        for cls, lvl in body.levels.items():
            pr.policy.set_level(cls, lvl, ident.subject, pr.plant.t)
        if body.global_cap is not None:
            pr.policy.set_global_cap(body.global_cap, ident.subject, pr.plant.t)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _log(
        pr,
        ident,
        f"Autonomy Dial changed by {ident.role}: {body.levels or ''} cap={body.global_cap}",
        "dial_changed",
        {"levels": body.levels, "global_cap": body.global_cap},
    )
    return pr.policy.snapshot(pr.plant.t)


@router.post("/kill")
async def kill(
    body: KillBody,
    pr: PlantRuntime = Depends(get_plant),
    ident: Identity = Depends(require("kill", "policy.kill_switch")),
) -> dict[str, Any]:
    if not body.on and not ident.can("kill_reset"):
        raise HTTPException(403, f"role '{ident.role}' may engage but not release the kill switch")
    pr.policy.set_kill_switch(body.on, body.reason, ident.subject, pr.plant.t)
    _log(
        pr,
        ident,
        f"KILL SWITCH {'ENGAGED' if body.on else 'released'} by {ident.role}: {body.reason or 'no reason given'}",
        "kill_switch_on" if body.on else "kill_switch_off",
    )
    pr.hub.publish(f"{pr.plant_id}/agent", {"event": "kill_switch", "on": body.on})
    return {"kill_switch": pr.policy.kill_switch, "info": pr.policy.kill_info}


@router.post("/break-glass")
async def break_glass(
    body: BreakGlassBody,
    pr: PlantRuntime = Depends(get_plant),
    ident: Identity = Depends(require("break_glass", "policy.break_glass")),
) -> dict[str, Any]:
    try:
        g = pr.policy.grant_break_glass(
            body.decision_class, body.level, body.minutes, body.reason, ident.subject, pr.plant.t
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _log(
        pr,
        ident,
        f"BREAK-GLASS {g['id']}: {body.decision_class} elevated to L{body.level} for {body.minutes} min - {body.reason}",
        "break_glass",
        g,
    )
    return g


@router.post("/timebox")
async def timebox(
    body: TimeboxBody,
    pr: PlantRuntime = Depends(get_plant),
    ident: Identity = Depends(require("dial", "policy.timebox")),
) -> dict[str, Any]:
    try:
        g = pr.policy.grant_timebox(
            body.decision_class, body.minutes, body.max_cost_eur, body.max_risk, ident.subject, pr.plant.t
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _log(
        pr,
        ident,
        f"Time-boxed auto-approval {g['id']} for {body.decision_class} ({body.minutes} min, <= EUR {body.max_cost_eur:.0f})",
        "timebox",
        g,
    )
    return g


@router.get("/matrix")
async def matrix(
    decision_class: str,
    risk: float = 0.2,
    assets: int = 1,
    cost_eur: float = 100.0,
    pr: PlantRuntime = Depends(get_plant),
) -> dict[str, Any]:
    if decision_class not in pr.policy.rules.classes:
        raise HTTPException(404, "unknown decision class")
    return {
        "decision_class": decision_class,
        "risk": risk,
        "assets": assets,
        "cost_eur": cost_eur,
        "outcome_by_level": pr.policy.matrix(decision_class, risk, assets, cost_eur, pr.plant.t),
    }


@router.post("/evaluate")
async def evaluate(body: EvalBody, pr: PlantRuntime = Depends(get_plant)) -> dict[str, Any]:
    """Dry-run: what would the policy engine decide for this hypothetical plan right now?"""
    if body.decision_class not in pr.policy.rules.classes:
        raise HTTPException(404, "unknown decision class")
    prop = Proposal(
        agent="dry-run",
        decision_class=body.decision_class,
        title="dry-run",
        actions=[Action(body.kind, body.params, body.target)],
        rationale="dry-run",
        created_t=pr.plant.t,
        expires_t=pr.plant.t + 60,
        risk=body.risk,
        cost_eur=body.cost_eur,
        assets=[f"A{i}" for i in range(body.assets)],
    )
    return pr.policy.evaluate(Plan("dry", "dry", [prop]), pr.plant.t).public()
