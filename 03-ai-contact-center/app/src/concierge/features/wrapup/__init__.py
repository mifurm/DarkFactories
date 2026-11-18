"""CC-09 Auto wrap-up: summary, disposition, CRM note, follow-up tasks, QA flags; ACW reduction measurement."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.rbac import Actor, require
from ...core.registry import EPIC_B, FeatureInfo
from ...engine.models import now
from ...engine.wrapup import BASELINE_ACW_S, DISPOSITIONS, edit_ratio, generate_wrapup

FEATURES = [
    FeatureInfo(
        "CC-09", "Auto wrap-up", EPIC_B, "P0", "/agent", "/api/wrapup",
        "Summary, disposition code, CRM note (via connector), follow-up tasks and QA flags for every conversation; human edit/submit; after-call-work reduction measured.",
    ),
]  # fmt: skip

router = APIRouter(prefix="/api/wrapup", tags=["wrapup (CC-09)"])


class SubmitBody(BaseModel):
    summary: str | None = Field(None, max_length=1500)
    disposition: str | None = None
    seconds_on_screen: float = Field(45, ge=0, le=3600)


@router.get("/dispositions")
async def dispositions() -> dict[str, str]:
    return DISPOSITIONS


@router.get("/stats")
async def stats(request: Request, _: Actor = Depends(require("metrics.read", "agent.console"))) -> dict[str, Any]:
    svc = request.app.state.services
    docs = await svc.repo.query("conversations", {"status": {"$in": ["resolved", "closed"]}}, limit=500)
    done = [d for d in docs if not d.get("eval_run_id")]
    with_wrap = [d for d in done if d.get("wrapup")]
    lat = sorted(d["wrapup"]["generated_at"] - d["closed_at"] for d in with_wrap if d.get("closed_at"))
    edits = [d["wrapup"]["edit_ratio"] for d in with_wrap if d["wrapup"].get("edit_ratio") is not None]
    auto = [d["wrapup"]["acw_seconds_auto"] for d in with_wrap]
    hist = await svc.repo.query("history", {"handled_by": "human"}, limit=2000)
    hist_ai = [h for h in await svc.repo.query("history", {"handled_by": "ai"}, limit=2000)]
    return {
        "ended_conversations": len(done), "with_wrapup": len(with_wrap), "coverage_pct": round(100 * len(with_wrap) / len(done), 1) if done else None,
        "latency_p95_s": round(lat[int(0.95 * (len(lat) - 1))], 2) if lat else None, "edit_ratio_avg": round(sum(edits) / len(edits), 3) if edits else None,
        "acw_auto_avg_s": round(sum(auto) / len(auto), 2) if auto else None, "acw_baseline_s": BASELINE_ACW_S,
        "acw_reduction_pct": round(100 * (1 - (sum(auto) / len(auto)) / BASELINE_ACW_S), 1) if auto else None,
        "historical": {"human_contacts": len(hist), "ai_contacts": len(hist_ai), "hours_saved_est": round((len(hist) + len(hist_ai)) * (BASELINE_ACW_S - 20) / 3600, 1)},
    }


@router.get("/{conv_id}")
async def get_wrapup(conv_id: str, request: Request, _: Actor = Depends(require("agent.console", "supervisor", "qa.read", "audit.read"))) -> dict[str, Any]:
    conv = await request.app.state.services.store.get(conv_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    if conv.wrapup is None:
        raise HTTPException(404, "wrap-up not generated yet")
    return conv.wrapup


@router.post("/{conv_id}/regenerate")
async def regenerate(conv_id: str, request: Request, _: Actor = Depends(require("agent.console", "supervisor"))) -> dict[str, Any]:
    svc = request.app.state.services
    conv = await svc.store.get(conv_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    conv.wrapup = await generate_wrapup(svc, conv)  # CRM note / task ids are deterministic -> idempotent
    await svc.store.save(conv)
    return conv.wrapup


@router.post("/{conv_id}/submit")
async def submit(conv_id: str, body: SubmitBody, request: Request, actor: Actor = Depends(require("agent.console", "supervisor"))) -> dict[str, Any]:
    svc = request.app.state.services
    conv = await svc.store.get(conv_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    if conv.wrapup is None:
        conv.wrapup = await generate_wrapup(svc, conv)
    w = conv.wrapup
    if body.disposition:
        if body.disposition not in DISPOSITIONS:
            raise HTTPException(422, "unknown disposition code")
        w["disposition"], w["disposition_label"] = body.disposition, DISPOSITIONS[body.disposition]
    if body.summary:
        w["edit_ratio"] = edit_ratio(w["summary"], body.summary)
        w["summary"] = body.summary
    else:
        w["edit_ratio"] = 0.0
    w.update({"submitted": True, "edited_by": actor.user, "acw_seconds_manual_review": body.seconds_on_screen, "submitted_at": now()})
    await svc.store.save(conv)
    await svc.audit.log("wrapup.submitted", actor=actor.user, resource=conv_id, conv_id=conv_id, detail={"edit_ratio": w["edit_ratio"], "disposition": w["disposition"]})
    return w
