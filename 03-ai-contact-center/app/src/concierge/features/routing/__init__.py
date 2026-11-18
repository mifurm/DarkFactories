"""CC-06 Intent/sentiment/urgency understanding & smart routing (Job-Router-style queues, workers, rules, escalation triggers)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.rbac import Actor, require
from ...core.registry import EPIC_B, FeatureInfo
from ...engine.models import Conversation, Understanding
from ...engine.routing import QUEUES, ROUTING_RULES, evaluate_triggers, route
from ...engine.understanding import analyze
from .labelled import LABELLED

FEATURES = [
    FeatureInfo(
        "CC-06", "Intent/sentiment/urgency understanding & smart routing", EPIC_B, "P0", "/routing", "/api/routing",
        "Multilingual intent/entity/sentiment/urgency/risk extraction, deterministic skills-based routing (queues, priorities, VIP, vulnerable, SLA exception policy) and explicit escalation triggers.",
    ),
]  # fmt: skip

router = APIRouter(prefix="/api/routing", tags=["routing (CC-06)"])


class AnalyzeBody(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    language: str | None = None


class RouteBody(BaseModel):
    intent: str = "other"
    risk_flags: list[str] = Field(default_factory=list)
    sentiment: float = 0.0
    urgency: str = "normal"
    vip: bool = False
    vulnerable: bool = False
    language: str = "en"
    channel: str = "web_chat"
    wait_s: float = 0.0


class SimulateBody(BaseModel):
    turns: list[str] = Field(min_length=1, max_length=30)
    language: str = "en"


class PresenceBody(BaseModel):
    presence: str = Field(pattern="^(available|busy|away)$")


def macro_f1(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    labels = sorted({t for t, _ in pairs} | {p for _, p in pairs})
    per: dict[str, dict[str, float]] = {}
    for lab in labels:
        tp = sum(1 for t, p in pairs if t == lab and p == lab)
        fp = sum(1 for t, p in pairs if t != lab and p == lab)
        fn = sum(1 for t, p in pairs if t == lab and p != lab)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        per[lab] = {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(2 * prec * rec / (prec + rec), 3) if prec + rec else 0.0, "support": tp + fn}
    present = [lab for lab in labels if per[lab]["support"] > 0]
    return {"macro_f1": round(sum(per[lab]["f1"] for lab in present) / len(present), 3), "accuracy": round(sum(t == p for t, p in pairs) / len(pairs), 3), "per_intent": {k: per[k] for k in present}, "n": len(pairs)}


@router.post("/analyze")
async def analyze_text(body: AnalyzeBody) -> dict[str, Any]:
    u = analyze(body.text, lang_hint=body.language)
    return u.model_dump()


@router.post("/route")
async def route_job(body: RouteBody) -> dict[str, Any]:
    u = Understanding(intent=body.intent, risk_flags=body.risk_flags, sentiment=body.sentiment, urgency=body.urgency, language=body.language)
    return route(u, vip=body.vip, vulnerable=body.vulnerable, language=body.language, channel=body.channel, wait_s=body.wait_s).to_dict()


@router.get("/queues")
async def queues(request: Request) -> dict[str, Any]:
    svc = request.app.state.services
    live = [c for c in svc.store.cache.values() if c.status == "waiting_human"]
    depth = defaultdict(int)
    for c in live:
        depth[c.queue or "general"] += 1
    return {"queues": [{"id": k, **v, "waiting": depth.get(k, 0)} for k, v in QUEUES.items()], "rules": ROUTING_RULES, "semantics": "Provider-neutral, in-process router with Job-Router-style semantics (an ACS Job Router dependency would not be strategic: it retires 30 Sep 2028): classification policy -> queue + priority + worker selectors; distribution policy (longest-idle / best-worker); exception policy (SLA at 80 % raises priority)."}


@router.get("/workers")
async def workers(request: Request) -> list[dict[str, Any]]:
    return request.app.state.services.ext.get("workers", [])


@router.put("/workers/{worker_id}/presence")
async def set_presence(worker_id: str, body: PresenceBody, request: Request, _: Actor = Depends(require("supervisor", "agent.console"))) -> dict[str, Any]:
    w = next((w for w in request.app.state.services.ext.get("workers", []) if w["id"] == worker_id), None)
    if w is None:
        raise HTTPException(404, "worker not found")
    w["presence"] = body.presence
    return w


@router.post("/triggers/simulate")
async def simulate_triggers(body: SimulateBody) -> dict[str, Any]:
    """Run a transcript turn-by-turn through understanding + escalation triggers (each trigger fires once)."""
    conv = Conversation(id="sim", language=body.language)
    fired: set[str] = set()
    timeline = []
    for text in body.turns:
        u = analyze(text, lang_hint=conv.language, prior=conv.understanding)
        conv.add("customer", text)
        conv.understanding = u
        conv.sentiment_trajectory.append(u.sentiment)
        conv.intent_trail.append(u.intent)
        conv.risk_flags = sorted(set(conv.risk_flags) | set(u.risk_flags))
        from ...core.redaction import redact  # noqa: F401
        from ...engine.guard import EXPLICIT_HUMAN

        trig = evaluate_triggers(conv, u, explicit_request=bool(EXPLICIT_HUMAN.search(text)), fired=fired)
        for t in trig:
            fired.add(t.code)
        timeline.append({"text": text, "intent": u.intent, "sentiment": u.sentiment, "emotion": u.emotion, "risk_flags": u.risk_flags, "fired": [t.to_dict() for t in trig]})
    return {"timeline": timeline, "fired_once": sorted(fired)}


@router.get("/labelled-eval")
async def labelled_eval() -> dict[str, Any]:
    pairs = [(label, analyze(text).intent) for text, label in LABELLED]
    return macro_f1(pairs) | {"misses": [{"text": t, "expected": label, "got": analyze(t).intent} for t, label in LABELLED if analyze(t).intent != label][:12]}
