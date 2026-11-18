"""CC-10 100 % Auto-QA: reviews, evidence, calibration workflow, agreement metrics, dashboards, coaching."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.rbac import Actor, require
from ...core.registry import EPIC_C, FeatureInfo
from ...engine import qa as qa_engine
from ...engine.models import Conversation
from .labelled import CASES, build_case

FEATURES = [
    FeatureInfo(
        "CC-10", "100 % Auto-QA", EPIC_C, "P0", "/qa", "/api/qa",
        "Every conversation (AI and human) scored on a 7-dimension rubric with evidence snippets and compliance auto-fail; calibration workflow with agreement metrics (kappa); per-agent coaching; QA dashboards.",
    ),
]  # fmt: skip

router = APIRouter(prefix="/api/qa", tags=["qa (CC-10)"])


class CalibrateBody(BaseModel):
    scores: dict[str, int] = Field(min_length=1)
    note: str = Field("", max_length=300)


def _strip(r: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in r.items() if k not in ("pk", "_ts", "ttl")}


@router.get("/reviews")
async def reviews(request: Request, limit: int = 60, band: str | None = None, participant: str | None = None, _: Actor = Depends(require("qa.read"))) -> list[dict[str, Any]]:
    svc = request.app.state.services
    rows = await svc.repo.query("qa_reviews", {"band": band} if band else None, order_by="scored_at", desc=True, limit=max(1, min(limit, 300)))
    if participant:
        rows = [r for r in rows if participant in r.get("participants", [])]
    return [_strip({k: r[k] for k in ("id", "conversation_id", "channel", "language", "scored_at", "scorer", "dimensions", "overall", "band", "auto_fail", "disposition", "participants", "calibration")}) for r in rows]


@router.get("/reviews/{conv_id}")
async def review(conv_id: str, request: Request, actor: Actor = Depends(require("qa.read"))) -> dict[str, Any]:
    svc = request.app.state.services
    rec = await svc.repo.get("qa_reviews", conv_id)
    if rec is None:
        raise HTTPException(404, "review not found")
    conv = await svc.store.get(conv_id)
    await svc.access_audit.log("qa.review_viewed", actor=f"{actor.role}:{actor.user}", resource=conv_id, conv_id=conv_id)
    transcript = [{"idx": m.idx, "role": m.role, "text": m.text, "flags": m.flags} for m in conv.messages if m.visible_to_customer] if conv else []
    return {**_strip(rec), "transcript": transcript}


@router.post("/score/{conv_id}")
async def rescore(conv_id: str, request: Request, _: Actor = Depends(require("qa.write"))) -> dict[str, Any]:
    svc = request.app.state.services
    conv = await svc.store.get(conv_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    return _strip(await qa_engine.score_conversation(svc, conv))


@router.post("/reviews/{conv_id}/calibrate")
async def calibrate(conv_id: str, body: CalibrateBody, request: Request, actor: Actor = Depends(require("qa.write"))) -> dict[str, Any]:
    if any(d not in qa_engine.DIMENSIONS or not 1 <= v <= 5 for d, v in body.scores.items()):
        raise HTTPException(422, "scores must use the rubric dimensions with values 1-5")
    try:
        rec = await qa_engine.calibrate(request.app.state.services, conv_id, body.scores, actor.user, body.note)
    except KeyError:
        raise HTTPException(404, "review not found") from None
    return _strip(rec)


@router.get("/agreement")
async def agreement(request: Request, _: Actor = Depends(require("qa.read"))) -> dict[str, Any]:
    return await qa_engine.agreement_report(request.app.state.services)


@router.get("/labelled-eval")
async def labelled_eval(_: Actor = Depends(require("qa.read"))) -> dict[str, Any]:
    """Auto-QA vs reference ('human') scores on the labelled transcript set."""
    pairs: list[tuple[int, int]] = []
    per: dict[str, list[tuple[int, int]]] = defaultdict(list)
    cases = []
    ev_ok = ev_total = 0
    for case in CASES:
        conv: Conversation = build_case(case)
        res = qa_engine.rule_score(conv)
        for d in qa_engine.DIMENSIONS:
            pairs.append((res["dimensions"][d], case["ref"][d]))
            per[d].append((res["dimensions"][d], case["ref"][d]))
        present = " ".join(m.text.lower() for m in conv.messages)
        for e in res["evidence"]:
            if e.get("quote"):
                ev_total += 1
                ev_ok += e["quote"].lower()[:60] in present
        cases.append({"case": case["name"], "auto": res["dimensions"], "reference": case["ref"], "auto_fail": [f["rule"] for f in res["auto_fail"]]})
    return {"overall": qa_engine.agreement(pairs), "by_dimension": {d: qa_engine.agreement(p) for d, p in per.items()}, "cases": cases, "evidence_in_transcript_pct": round(100 * ev_ok / ev_total, 1) if ev_total else 100.0, "target": {"within1_pct": 85}}


@router.get("/dashboard")
async def dashboard(request: Request, _: Actor = Depends(require("qa.read"))) -> dict[str, Any]:
    svc = request.app.state.services
    live = await svc.repo.query("qa_reviews")
    hist = [h for h in await svc.repo.query("history") if h.get("qa_overall") is not None]
    total_convs = await svc.repo.count("conversations", {"status": {"$in": ["resolved", "closed"]}})
    bands = defaultdict(int)
    for r in live:
        bands[r["band"]] += 1
    for h in hist:
        bands[h.get("qa_band", "good")] += 1
    dim_sum: dict[str, float] = defaultdict(float)
    n = 0
    for h in hist:
        for d, v in h["qa_dims"].items():
            dim_sum[d] += v
        n += 1
    for r in live:
        for d, v in r["dimensions"].items():
            dim_sum[d] += v
        n += 1
    by_week: dict[str, list[float]] = defaultdict(list)
    for h in hist:
        by_week[h["week"]].append(h["qa_overall"])
    by_handler: dict[str, list[float]] = defaultdict(list)
    for h in hist:
        by_handler[h["handled_by"]].append(h["qa_overall"])
    by_agent: dict[str, list[float]] = defaultdict(list)
    for h in hist:
        by_agent[h["agent_id"]].append(h["qa_overall"])
    fails = [r for r in live if r["auto_fail"]]
    outliers = sorted(live, key=lambda r: r["overall"])[:6]
    return {
        "coverage": {"qa_records_live": len(live), "ended_conversations_live": total_convs, "historical_records": len(hist), "coverage_pct": 100.0 if (total_convs == 0 or len(live) >= total_convs) else round(100 * len(live) / total_convs, 1), "manual_qa_baseline_pct": 2.0},
        "bands": dict(bands), "dimension_avg": {d: round(v / n, 2) for d, v in dim_sum.items()} if n else {},
        "weekly": [{"week": w, "avg": round(sum(v) / len(v), 1), "n": len(v)} for w, v in sorted(by_week.items())],
        "ai_vs_human": {k: {"avg": round(sum(v) / len(v), 1), "n": len(v)} for k, v in by_handler.items()},
        "agents": sorted([{"agent": a, "avg": round(sum(v) / len(v), 1), "n": len(v)} for a, v in by_agent.items()], key=lambda x: x["avg"]),
        "auto_fails_live": [{"conversation_id": r["id"], "rules": [f["rule"] for f in r["auto_fail"]], "overall": r["overall"]} for r in fails][:20],
        "auto_fail_rate_hist": round(sum(1 for h in hist if h.get("qa_auto_fail")) / len(hist), 4) if hist else 0,
        "outliers": [{"conversation_id": r["id"], "overall": r["overall"], "band": r["band"]} for r in outliers],
    }  # fmt: skip


@router.get("/coaching/{agent_id}")
async def coaching(agent_id: str, request: Request, _: Actor = Depends(require("qa.read"))) -> dict[str, Any]:
    svc = request.app.state.services
    is_ai = agent_id in ("concierge-ai", "ai")
    pid = "concierge-ai" if is_ai else agent_id
    live = [r for r in await svc.repo.query("qa_reviews") if pid in r.get("participants", [])]
    hist = [h for h in await svc.repo.query("history", {"agent_id": pid}) if h.get("qa_dims")]
    dims = [r["segments"].get("ai" if is_ai else "human", r["dimensions"]) for r in live] + [h["qa_dims"] for h in hist]
    ev = [e for r in live for e in r["evidence"]]
    return {"agent": pid, "conversations": len(dims), "avg_overall": round(sum(qa_engine.overall_score({d: x.get(d, 3) for d in qa_engine.DIMENSIONS}) for x in dims) / len(dims), 1) if dims else None, "suggestions": qa_engine.coaching(dims, ev, is_ai)}
