"""CC-17 Prompt / policy / knowledge management & staged rollout: immutable versioned configs, diff, eval-gated promotion,
canary %, A/B metrics by version, one-click rollback, audit trail."""

from __future__ import annotations

import difflib
import time
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.rbac import Actor, require
from ...core.registry import EPIC_D, FeatureInfo
from ...engine.models import AgentConfig
from ..evals import latest_baseline, start_run

FEATURES = [
    FeatureInfo(
        "CC-17", "Prompt/policy/knowledge management & staged rollout", EPIC_D, "P1", "/rollout", "/api/rollout",
        "Immutable versioned agent configs (prompts, tools, policy, KB), diff view, eval-gated promotion, deterministic canary %, A/B metrics by version, one-click rollback, full audit trail.",
    ),
]  # fmt: skip
SEED_ORDER = 5

router = APIRouter(prefix="/api/rollout", tags=["rollout (CC-17)"])


async def seed(svc: Any, force: bool) -> dict[str, Any]:
    await svc.configs.load()
    return {"configs": len(await svc.configs.list()), "active": svc.configs.active_id}


class CreateBody(BaseModel):
    base_id: str | None = None
    name: str = Field(min_length=3, max_length=80)
    prompts: dict[str, str] | None = None
    tools: dict[str, list[str]] | None = None
    policy: dict[str, Any] | None = None
    notes: str = Field("", max_length=400)


class CanaryBody(BaseModel):
    pct: int = Field(ge=1, le=100)


def _brief(c: AgentConfig) -> dict[str, Any]:
    return {"id": c.id, "name": c.name, "version": c.version, "status": c.status, "canary_pct": c.canary_pct, "created_at": c.created_at, "created_by": c.created_by, "parent": c.parent, "notes": c.notes, "gate": c.gate, "policy": c.policy, "prompt_roles": sorted(c.prompts)}


async def _log(svc: Any, action: str, cfg_id: str, actor: str, detail: dict[str, Any] | None = None) -> None:
    await svc.repo.put("rollouts", {"id": f"{int(time.time() * 1000)}-{action}", "ts": time.time(), "action": action, "config": cfg_id, "actor": actor, "detail": detail or {}}, ttl=400 * 86400)


@router.get("/configs")
async def list_configs(request: Request, _: Actor = Depends(require("rollout.read"))) -> list[dict[str, Any]]:
    return [_brief(c) for c in await request.app.state.services.configs.list()]


@router.get("/configs/{cfg_id}")
async def get_config(cfg_id: str, request: Request, _: Actor = Depends(require("rollout.read"))) -> dict[str, Any]:
    cfg = await request.app.state.services.configs.get(cfg_id)
    if cfg is None:
        raise HTTPException(404, "config not found")
    return cfg.model_dump()


@router.get("/diff")
async def diff(a: str, b: str, request: Request, _: Actor = Depends(require("rollout.read"))) -> dict[str, Any]:
    svc = request.app.state.services
    ca, cb = await svc.configs.get(a), await svc.configs.get(b)
    if not ca or not cb:
        raise HTTPException(404, "config not found")
    prompts = {}
    for role in sorted(set(ca.prompts) | set(cb.prompts)):
        d = list(difflib.unified_diff(ca.prompts.get(role, "").splitlines(), cb.prompts.get(role, "").splitlines(), f"{a}/{role}", f"{b}/{role}", lineterm="", n=1))
        if d:
            prompts[role] = d
    policy = {k: {"from": ca.policy.get(k), "to": cb.policy.get(k)} for k in sorted(set(ca.policy) | set(cb.policy)) if ca.policy.get(k) != cb.policy.get(k)}
    tools = {ag: {"added": sorted(set(cb.tools.get(ag, [])) - set(ca.tools.get(ag, []))), "removed": sorted(set(ca.tools.get(ag, [])) - set(cb.tools.get(ag, [])))} for ag in sorted(set(ca.tools) | set(cb.tools)) if set(ca.tools.get(ag, [])) != set(cb.tools.get(ag, []))}
    return {"a": a, "b": b, "prompts": prompts, "policy": policy, "tools": tools, "identical": not (prompts or policy or tools)}


@router.post("/configs")
async def create(body: CreateBody, request: Request, actor: Actor = Depends(require("rollout.write"))) -> dict[str, Any]:
    svc = request.app.state.services
    cfg = await svc.configs.create_version(body.base_id, name=body.name, prompts=body.prompts, tools=body.tools, policy=body.policy, notes=body.notes, author=actor.user)
    await _log(svc, "created", cfg.id, actor.user, {"parent": cfg.parent})
    return _brief(cfg)


@router.post("/configs/{cfg_id}/gate")
async def gate(cfg_id: str, request: Request, suite: str = "gate", actor: Actor = Depends(require("rollout.write"))) -> dict[str, Any]:
    """Run the eval gate for a candidate; the result is stored on the config and required for canary / promotion."""
    svc = request.app.state.services
    cfg = await svc.configs.get(cfg_id)
    if cfg is None:
        raise HTTPException(404, "config not found")
    active = await svc.configs.active()
    run_id = await start_run(svc, suite, cfg, with_gate=True, baseline_cfg=active)
    state = svc.ext["eval_runs"][run_id]

    async def attach() -> None:
        import asyncio

        for _ in range(900):
            await asyncio.sleep(1)
            if state["status"] != "running":
                break
        if state["status"] == "done" and state.get("gate"):
            cfg.gate = {"passed": state["gate"]["passed"], "run_id": run_id, "reasons": state["gate"]["reasons"], "pass_rate": state["totals"]["pass_rate"], "suite": suite, "ts": time.time()}
            await svc.configs.save(cfg)
            await _log(svc, "gate", cfg.id, actor.user, cfg.gate)

    svc.spawn(attach())
    return {"run_id": run_id, "config": cfg_id, "status": "running"}


def _require_gate(cfg: AgentConfig) -> None:
    if not cfg.gate or not cfg.gate.get("passed"):
        raise HTTPException(409, {"error": "gate_required", "message": "Promotion and canary require a passing eval gate for this exact config version.", "gate": cfg.gate})


@router.post("/configs/{cfg_id}/canary")
async def canary(cfg_id: str, body: CanaryBody, request: Request, actor: Actor = Depends(require("rollout.write"))) -> dict[str, Any]:
    svc = request.app.state.services
    cfg = await svc.configs.get(cfg_id)
    if cfg is None:
        raise HTTPException(404, "config not found")
    if cfg.status == "active":
        raise HTTPException(409, "already active")
    _require_gate(cfg)
    cfg = await svc.configs.set_status(cfg_id, "canary", actor.user, canary_pct=body.pct)
    await _log(svc, "canary", cfg_id, actor.user, {"pct": body.pct})
    return _brief(cfg)


@router.post("/configs/{cfg_id}/promote")
async def promote(cfg_id: str, request: Request, actor: Actor = Depends(require("rollout.write"))) -> dict[str, Any]:
    svc = request.app.state.services
    cfg = await svc.configs.get(cfg_id)
    if cfg is None:
        raise HTTPException(404, "config not found")
    _require_gate(cfg)
    prev = svc.configs.active_id
    cfg = await svc.configs.set_status(cfg_id, "active", actor.user)
    await _log(svc, "promoted", cfg_id, actor.user, {"previous": prev})
    return _brief(cfg)


@router.post("/rollback")
async def rollback(request: Request, actor: Actor = Depends(require("rollout.write"))) -> dict[str, Any]:
    """One click: stop any canary and re-activate the previously active config; in-flight conversations keep their version."""
    svc = request.app.state.services
    logs = sorted(await svc.repo.query("rollouts"), key=lambda r: r["ts"], reverse=True)
    current = svc.configs.active_id
    target = None
    for r in logs:
        if r["action"] == "promoted" and r["config"] == current and r["detail"].get("previous"):
            target = r["detail"]["previous"]
            break
    if target is None:
        retired = [c for c in await svc.configs.list() if c.status == "retired"]
        target = retired[0].id if retired else None
    if svc.configs.canary_id:
        await svc.configs.set_status(svc.configs.canary_id, "candidate", actor.user)
        await _log(svc, "canary_stopped", "-", actor.user)
    if target is None or target == current:
        return {"active": current, "rolled_back": False, "message": "nothing to roll back to (canary stopped if any)"}
    cfg = await svc.configs.set_status(target, "active", actor.user)
    cur = await svc.configs.get(current)
    if cur:
        cur.status = "retired"
        await svc.configs.save(cur)
    await _log(svc, "rollback", target, actor.user, {"from": current})
    await svc.audit.log("config.rollback", actor=actor.user, resource=target, detail={"from": current})
    return {"active": cfg.id, "rolled_back": True, "from": current}


@router.get("/ab")
async def ab(request: Request, _: Actor = Depends(require("rollout.read", "metrics.read"))) -> dict[str, Any]:
    """Live A/B split by config version (real conversations) + latest eval pass rates per config."""
    svc = request.app.state.services
    convs = [d for d in await svc.repo.query("conversations") if not d.get("eval_run_id")]
    by: dict[str, dict[str, Any]] = defaultdict(lambda: {"conversations": 0, "resolved_by_ai": 0, "escalated": 0, "qa": [], "cost": 0.0})
    for d in convs:
        v = by[d["config_version"]]
        v["conversations"] += 1
        v["escalated"] += 1 if d.get("handoff") else 0
        v["resolved_by_ai"] += 1 if d.get("status") == "resolved" and not d.get("handoff") else 0
        if d.get("qa") and d["qa"].get("overall") is not None:
            v["qa"].append(d["qa"]["overall"])
        v["cost"] += (d.get("usage") or {}).get("cost_usd", 0.0)
    runs = await svc.repo.query("eval_runs", {"stress": False}, order_by="ts", desc=True, limit=40)
    evals: dict[str, Any] = {}
    for r in runs:
        evals.setdefault(r["config_id"], {"pass_rate": r["totals"]["pass_rate"], "dimensions": r["dimensions"], "suite": r["suite"], "run_id": r["id"]})
    out = []
    for cid in sorted(set(by) | set(evals)):
        v = by.get(cid, {"conversations": 0, "resolved_by_ai": 0, "escalated": 0, "qa": [], "cost": 0.0})
        n = v["conversations"]
        out.append({"config": cid, "conversations": n, "containment": round(v["resolved_by_ai"] / n, 3) if n else None, "escalation_rate": round(v["escalated"] / n, 3) if n else None, "qa_avg": round(sum(v["qa"]) / len(v["qa"]), 1) if v["qa"] else None, "cost_per_resolved_usd": round(v["cost"] / v["resolved_by_ai"], 4) if v["resolved_by_ai"] else None, "eval": evals.get(cid)})
    return {"versions": out, "canary": {"config": svc.configs.canary_id, "pct": svc.configs.canary_pct}, "active": svc.configs.active_id}


@router.get("/log")
async def log(request: Request, _: Actor = Depends(require("rollout.read", "audit.read"))) -> list[dict[str, Any]]:
    rows = sorted(await request.app.state.services.repo.query("rollouts"), key=lambda r: r["ts"], reverse=True)[:80]
    return [{k: v for k, v in r.items() if k not in ("pk", "_ts", "ttl")} for r in rows]


@router.get("/baseline/{config_id}")
async def baseline(config_id: str, request: Request, suite: str = "gate") -> dict[str, Any]:
    rep = await latest_baseline(request.app.state.services, suite, config_id)
    return {"config": config_id, "suite": suite, "totals": rep["totals"] if rep else None, "dimensions": rep["dimensions"] if rep else None}
