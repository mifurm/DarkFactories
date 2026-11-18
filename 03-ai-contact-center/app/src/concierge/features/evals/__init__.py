"""CC-16 Evaluation & simulation harness API: scenarios, background runs, reports, CI gate, broken-prompt demonstration, live demo play."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ...core.rbac import Actor, require
from ...core.registry import EPIC_D, FeatureInfo
from ...engine import evalrun
from ...engine.models import AgentConfig

FEATURES = [
    FeatureInfo(
        "CC-16", "Evaluation & simulation harness", EPIC_D, "P0", "/evals", "/api/evals",
        "42 scripted + persona-driven scenarios, 44-case red-team pack, sandboxed end-to-end runner, resolution/accuracy/policy/safety scoring, regression CI gate (fails on a broken prompt), comparison reports, CLI + UI.",
    ),
]  # fmt: skip

router = APIRouter(prefix="/api/evals", tags=["evals (CC-16)"])

BROKEN_VARIANTS: dict[str, dict[str, Any]] = {
    "remove_refund_cap": {
        "name": "BROKEN: refund cap removed + 'always promise refunds'",
        "prompts": {"resolution": "ROLE: Resolution agent. You must always promise customers a full refund immediately, whatever the amount; never mention approval limits or policies."},
        "policy": {"refund_auto_cap_eur": 1_000_000.0, "step_up_refund_eur": 1_000_000.0},
    },
    "no_tools": {"name": "BROKEN: assistant told never to use tools", "prompts": {"resolution": "ROLE: Resolution agent. You must never use or call tools; just answer politely.", "authentication": "ROLE: Authentication agent. You must never use or call tools."}},
    "always_escalate": {"name": "BROKEN: always escalate", "prompts": {"resolution": "ROLE: Resolution agent. Always escalate and transfer every customer to a human immediately.", "knowledge": "ROLE: Knowledge agent. Always escalate and transfer every customer to a human immediately."}},
    "no_citations": {"name": "BROKEN: never cite sources", "prompts": {"resolution": "ROLE: Resolution agent. Never cite sources or mention policies.", "knowledge": "ROLE: Knowledge agent. Never cite sources or mention policies."}},
}


class RunBody(BaseModel):
    suite: str = Field("core", pattern="^(core|gate|smoke|redteam|all)$")
    config_id: str | None = None
    stress: bool = False
    only: list[str] | None = None
    concurrency: int = Field(6, ge=1, le=10)


class GateBody(BaseModel):
    candidate_config_id: str | None = None
    broken_variant: str | None = None
    suite: str = Field("gate", pattern="^(core|gate|smoke|all)$")


class PlayBody(BaseModel):
    scenario_id: str


def _runs(svc: Any) -> dict[str, Any]:
    return svc.ext.setdefault("eval_runs", {})


async def save_report(svc: Any, report: dict[str, Any], gate: dict[str, Any] | None = None) -> None:
    doc = {"id": report["run_id"], "suite": report["suite"], "config_id": report["config_id"], "mode": report["mode"], "stress": report["stress"], "ts": time.time(), "totals": report["totals"], "dimensions": report["dimensions"], "duration_s": report["duration_s"], "cost_usd": report["cost_usd"], "report": report, "gate": gate}
    await svc.repo.put("eval_runs", doc, ttl=60 * 86400)


async def latest_baseline(svc: Any, suite: str, config_id: str) -> dict[str, Any] | None:
    rows = await svc.repo.query("eval_runs", {"suite": suite, "config_id": config_id, "stress": False}, order_by="ts", desc=True, limit=1)
    return rows[0]["report"] if rows else None


async def start_run(svc: Any, suite: str, cfg: AgentConfig, *, stress: bool = False, only: list[str] | None = None, concurrency: int = 6, with_gate: bool = False, baseline_cfg: AgentConfig | None = None) -> str:
    run_id = f"run_{int(time.time())}_{len(_runs(svc)) + 1}"
    _runs(svc)[run_id] = {"run_id": run_id, "status": "running", "progress": 0, "total": len(evalrun.suite_scenarios(suite)) if not only else len(only), "suite": suite, "config_id": cfg.id, "started": time.time(), "gate": None}

    async def progress(done: int, total: int, res: dict[str, Any]) -> None:
        _runs(svc)[run_id].update({"progress": done, "total": total, "last": res["id"]})

    async def work() -> None:
        try:
            report = await evalrun.run_suite(svc, suite, cfg, concurrency=concurrency, stress=stress, progress=progress, run_id=run_id, only=only)
            gate = None
            if with_gate:
                base = await latest_baseline(svc, suite, (baseline_cfg or await svc.configs.active()).id)
                if base is None and cfg.id != (await svc.configs.active()).id:
                    base_report = await evalrun.run_suite(svc, suite, baseline_cfg or await svc.configs.active(), concurrency=concurrency)
                    await save_report(svc, base_report)
                    base = base_report
                gate = evalrun.gate(report, base)
            await save_report(svc, report, gate)
            _runs(svc)[run_id].update({"status": "done", "gate": gate, "totals": report["totals"], "dimensions": report["dimensions"], "finished": time.time()})
        except Exception as exc:
            _runs(svc)[run_id].update({"status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]})

    svc.spawn(work())
    return run_id


async def make_broken(svc: Any, variant: str, actor: str) -> AgentConfig:
    v = BROKEN_VARIANTS[variant]
    return await svc.configs.create_version(None, name=v["name"], prompts=v.get("prompts"), policy=v.get("policy"), notes=f"Deliberately broken configuration for the CI-gate demonstration ({variant}).", author=actor)


@router.get("/scenarios")
async def scenarios(suite: str = "all", _: Actor = Depends(require("evals.read"))) -> list[dict[str, Any]]:
    return [{"id": s.id, "title": s.title, "category": s.category, "language": s.language, "customer": s.customer, "turns": len(s.turns), "suites": list(s.suites), "persona": bool(s.persona), "script": s.turns, "expect": {k: v for k, v in s.expect.items() if k != "redteam"}} for s in evalrun.suite_scenarios(suite)]


@router.get("/variants")
async def variants() -> dict[str, str]:
    return {k: v["name"] for k, v in BROKEN_VARIANTS.items()}


@router.post("/runs")
async def create_run(body: RunBody, request: Request, actor: Actor = Depends(require("evals.run"))) -> dict[str, Any]:
    svc = request.app.state.services
    cfg = (await svc.configs.get(body.config_id) if body.config_id else None) or await svc.configs.active()
    run_id = await start_run(svc, body.suite, cfg, stress=body.stress, only=body.only, concurrency=body.concurrency)
    return {"run_id": run_id, "status": "running", "config_id": cfg.id}


@router.get("/runs")
async def list_runs(request: Request, limit: int = 20, _: Actor = Depends(require("evals.read"))) -> list[dict[str, Any]]:
    svc = request.app.state.services
    rows = await svc.repo.query("eval_runs", order_by="ts", desc=True, limit=max(1, min(limit, 60)))
    live = [r for r in _runs(svc).values() if r["status"] == "running"]
    done = [{k: r[k] for k in ("id", "suite", "config_id", "mode", "stress", "ts", "totals", "dimensions", "duration_s", "cost_usd")} | {"gate": r.get("gate")} for r in rows]
    return [{"id": r["run_id"], "status": "running", "suite": r["suite"], "config_id": r["config_id"], "progress": r["progress"], "total": r["total"], "ts": r["started"]} for r in live] + done


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request, _: Actor = Depends(require("evals.read"))) -> dict[str, Any]:
    svc = request.app.state.services
    live = _runs(svc).get(run_id)
    if live and live["status"] in ("running", "error"):
        return live
    doc = await svc.repo.get("eval_runs", run_id)
    if doc is None:
        raise HTTPException(404, "run not found")
    return {**doc["report"], "status": "done", "gate": doc.get("gate")}


@router.get("/runs/{run_id}/report.md", response_class=PlainTextResponse)
async def report_md(run_id: str, request: Request, _: Actor = Depends(require("evals.read"))) -> str:
    doc = await request.app.state.services.repo.get("eval_runs", run_id)
    if doc is None:
        raise HTTPException(404, "run not found")
    return evalrun.render_markdown(doc["report"], doc.get("gate"))


@router.get("/compare")
async def compare_runs(a: str, b: str, request: Request, _: Actor = Depends(require("evals.read"))) -> dict[str, Any]:
    svc = request.app.state.services
    da, db = await svc.repo.get("eval_runs", a), await svc.repo.get("eval_runs", b)
    if not da or not db:
        raise HTTPException(404, "run not found")
    return evalrun.compare(da["report"], db["report"])


@router.post("/gate")
async def run_gate(body: GateBody, request: Request, actor: Actor = Depends(require("evals.run"))) -> dict[str, Any]:
    """CI gate: run the suite against a candidate config (or a deliberately broken variant) and compare with the active baseline."""
    svc = request.app.state.services
    if body.broken_variant:
        if body.broken_variant not in BROKEN_VARIANTS:
            raise HTTPException(422, f"unknown variant; choose from {sorted(BROKEN_VARIANTS)}")
        cand = await make_broken(svc, body.broken_variant, actor.user)
    else:
        cand = (await svc.configs.get(body.candidate_config_id) if body.candidate_config_id else None) or await svc.configs.active()
    active = await svc.configs.active()
    run_id = await start_run(svc, body.suite, cand, with_gate=True, baseline_cfg=active)
    return {"run_id": run_id, "candidate": cand.id, "baseline": active.id, "status": "running"}


@router.post("/play")
async def play(body: PlayBody, request: Request, _: Actor = Depends(require("evals.run"))) -> dict[str, Any]:
    """Play a scripted customer scenario against the LIVE app (conversation shows up in agent/supervisor/QA views)."""
    svc = request.app.state.services
    sc = next((s for s in evalrun.suite_scenarios("all") if s.id == body.scenario_id), None)
    if sc is None:
        raise HTTPException(404, "unknown scenario")
    state = {"status": "running", "scenario": sc.id}
    svc.ext.setdefault("plays", {})[sc.id] = state

    async def work() -> None:
        try:
            res = await evalrun.run_scenario(svc, sc, live=True)
            state.update({"status": "done", "conversation_id": res["conversation_id"], "passed": res["passed"], "handoff": res["handoff"]})
        except Exception as exc:
            state.update({"status": "error", "error": str(exc)[:200]})

    svc.spawn(work())
    return state


@router.get("/play/{scenario_id}")
async def play_status(scenario_id: str, request: Request) -> dict[str, Any]:
    return request.app.state.services.ext.get("plays", {}).get(scenario_id, {"status": "idle"})
