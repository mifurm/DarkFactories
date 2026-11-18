"""CC-07 Warm handoff with context package: queue of waiting handoffs, package delivery, accept, reveal-with-audit, callback fallback."""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core import i18n
from ...core.rbac import Actor, require
from ...core.registry import EPIC_B, FeatureInfo
from ...engine import handoff as ho
from ...engine import localize, plan_text
from ...engine.models import now

FEATURES = [
    FeatureInfo(
        "CC-07", "Warm handoff with context package", EPIC_B, "P0", "/agent", "/api/handoff",
        "Escalation builds a context package (summary, intent, entities, steps tried, sentiment trajectory, suggested resolution, policy citations) delivered to the console in real time; PII-minimised with audited reveal; callback fallback.",
    ),
]  # fmt: skip

router = APIRouter(prefix="/api/handoff", tags=["handoff (CC-07)"])


class AcceptBody(BaseModel):
    agent_id: str = Field(max_length=20)


class CallbackBody(BaseModel):
    window: str = Field("next business day 09:00-12:00", max_length=60)


def queue_item(svc: Any, c: Any) -> dict[str, Any]:
    h = c.handoff or {}
    pkg = localize.localize_package(h.get("package"), c) or {}  # trigger reason, routing text and machine-written summary in the request locale
    return {
        "conversation_id": c.id, "queue": c.queue, "queue_name": localize.queue_name(c.queue or "general"), "priority": c.priority, "language": c.language, "channel": c.channel, "status": c.status,
        "waiting_s": round(now() - h.get("created_at", now()), 1) if c.handler == "queue" else None, "sla_s": h.get("routing", {}).get("sla_s"),
        "trigger": localize.localize_trigger(h.get("trigger")), "offered_to": h.get("offered_to"), "customer": pkg.get("customer", {}).get("first_name") or c.customer_label,
        "summary": pkg.get("summary"), "sentiment": pkg.get("sentiment", {}).get("current"), "emotion": pkg.get("sentiment", {}).get("emotion"),
        "risk_flags": pkg.get("risk_flags", []), "completeness": pkg.get("completeness"), "assigned_agent": c.assigned_agent, "state": h.get("state"),
    }  # fmt: skip


@router.get("/queue")
async def queue(request: Request, _: Actor = Depends(require("agent.console", "supervisor"))) -> list[dict[str, Any]]:
    svc = request.app.state.services
    waiting = [c for c in svc.store.cache.values() if c.status == "waiting_human" and c.handoff]
    waiting.sort(key=lambda c: (-c.priority, c.handoff["created_at"]))
    return [queue_item(svc, c) for c in waiting]


@router.get("/{conv_id}/package")
async def package(conv_id: str, request: Request, reveal: str | None = None, actor: Actor = Depends(require("agent.console", "supervisor"))) -> dict[str, Any]:
    svc = request.app.state.services
    conv = await svc.store.get(conv_id)
    if conv is None or not conv.handoff:
        raise HTTPException(404, "no handoff for this conversation")
    pkg = dict(localize.localize_package(conv.handoff["package"], conv))
    out: dict[str, Any] = {**pkg, "handoff_id": conv.handoff["id"], "state": conv.handoff["state"], "package_ms": conv.handoff.get("package_ms")}
    if reveal in ("phone", "email") and conv.identity.customer_id:
        cust = await svc.oms.get_customer(conv.identity.customer_id)
        if cust:
            out["revealed"] = {reveal: cust[reveal]}
            await svc.access_audit.log("pii.reveal", actor=f"{actor.role}:{actor.user}", resource=conv.identity.customer_id, conv_id=conv_id, detail={"field": reveal})
    return out


@router.post("/{conv_id}/accept")
async def accept(conv_id: str, body: AcceptBody, request: Request, _: Actor = Depends(require("handoff.accept"))) -> dict[str, Any]:
    svc = request.app.state.services
    conv = await svc.store.get(conv_id)
    if conv is None or conv.status != "waiting_human":
        raise HTTPException(409, "conversation is not waiting for a human")
    async with svc.store.lock(conv_id):
        h = await ho.accept(svc, conv, body.agent_id)
        await svc.store.save(conv)
        await svc.bus.publish(f"conv:{conv_id}", {"type": "message", "message": conv.messages[-1].model_dump()})
        await svc.bus.publish(f"conv:{conv_id}", {"type": "status", "status": conv.status})
    return {"state": h.get("state"), "wait_s": h.get("wait_s")}


@router.post("/{conv_id}/callback")
async def callback(conv_id: str, body: CallbackBody, request: Request, _: Actor = Depends(require("agent.console", "supervisor"))) -> dict[str, Any]:
    """No human available: offer a callback with the package attached (no loss of context)."""
    svc = request.app.state.services
    conv = await svc.store.get(conv_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    cb = {"id": f"cb_{uuid.uuid4().hex[:8]}", "conv_id": conv_id, "window": body.window, "language": conv.language, "package": (conv.handoff or {}).get("package"), "status": "scheduled", "created_at": time.time()}
    await svc.repo.put("callbacks", cb)
    lang = ho.doc_lang(conv)  # ticket text for the operators and the customer notice are written in the conversation's language
    window = i18n.msg("ho.callback.window_default", lang) if body.window == i18n.msg("ho.callback.window_default", "en") else body.window
    ticket = await svc.oms.create_ticket(conv.identity.customer_id, i18n.msg("ho.callback.ticket", lang, window=window), "other", "high", conv_id, conv.entities.get("order_id"), [i18n.msg("ho.callback.note", lang, id=cb["id"])])
    conv.add("system_notice", plan_text.callback_scheduled(conv.language, window), lang=conv.language, flags=["callback"])
    await svc.store.save(conv)
    return {"callback": {k: v for k, v in cb.items() if k != "package"}, "ticket": ticket["id"]}


@router.post("/{conv_id}/return-to-ai")
async def return_to_ai(conv_id: str, request: Request, actor: Actor = Depends(require("agent.console", "supervisor"))) -> dict[str, Any]:
    conv = await request.app.state.services.orchestrator.return_to_ai(conv_id, actor.user)
    return {"status": conv.status, "handler": conv.handler}
