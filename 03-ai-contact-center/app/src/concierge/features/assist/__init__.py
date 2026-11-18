"""CC-08 Agent Assist copilot + human-agent console API: live next-best-action with citations, suggested replies, compliance
reminders, form auto-fill, tone coaching, translation, chat takeover. The copilot never executes a state-changing tool itself."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.rbac import Actor, require
from ...core.registry import EPIC_B, FeatureInfo
from ...engine.guard import EXPLICIT_HUMAN, find_risky_promises, toxicity_rules
from ...engine.models import Conversation, new_id, now
from ...engine.translate import translate
from ...engine.wrapup import classify_disposition

FEATURES = [
    FeatureInfo(
        "CC-08", "Agent Assist copilot", EPIC_B, "P0", "/agent", "/api/assist",
        "Human-agent console: live transcript, next-best-action with policy citations, suggested replies, compliance reminders, form auto-fill, tone coaching, translation, chat takeover with acceptance logging.",
    ),
]  # fmt: skip

router = APIRouter(prefix="/api/assist", tags=["assist (CC-08)"])

NBA = {
    "damaged_item": [("Confirm the damage and the delivery date", "Damage must be reported within 14 days of delivery.", "damage-001", None), ("Offer replacement or full refund; pickup is free", "Refunds up to EUR 500 can be issued immediately; above that a specialist approves.", "refunds-001", None), ("Book the free pickup slot", "Pickup windows are Mon-Fri 09-13 / 13-17.", "returns-003", "get_available_slots")],
    "return_request": [("Check the 30-day return window and item eligibility", "Unused items within 30 days of delivery qualify.", "returns-001", "check_return_eligibility"), ("Start the return and book the pickup", "Bulky items are collected free of charge.", "returns-003", "initiate_return")],
    "refund_status": [("Look up the refund status and release date", "Refunds are paid 5-7 business days after the item is collected.", "refunds-003", "lookup_order")],
    "order_status": [("Track the shipment and share the new ETA", "Delayed means the carrier expects to miss the planned date.", "delivery-002", "track_shipment")],
    "delivery_change": [("Offer the next delivery windows (free until 24 h before)", "Rescheduling is free up to 24 hours before the window.", "delivery-003", "get_available_slots")],
    "warranty_claim": [("Open a warranty claim within 24/36 months", "Decision within 10 working days.", "warranty-002", "warranty_claim")],
    "complaint": [("Acknowledge the complaint, summarise it back, give a timeline", "A senior colleague responds within 5 working days.", "service-003", "create_ticket")],
    "address_change": [("Verify at L2 and change the address if not yet dispatched", "Address changes are free until dispatch.", "delivery-007", "update_address")],
}
REPLIES = {
    "en": {"empathy": "I'm really sorry about this, {name}. I've read everything you told our assistant, so you won't need to repeat it. {next}", "damaged_item": "Thank you for your patience, {name}. I can arrange a free replacement or a full refund and collect the item at no cost - which would you prefer?", "legal_threat": "I understand how serious this is for you, {name}, and I want to resolve it properly. Let me review the full history of your order and tell you exactly what I can do today.", "generic": "Thanks for your patience, {name}. Let me look into this right away.", "refund_terms": "Once the item is collected, the refund reaches your original payment method within 5-7 business days."},
    "de": {"empathy": "Das tut mir wirklich leid, {name}. Ich habe alles gelesen, was Sie unserem Assistenten geschildert haben - Sie müssen nichts wiederholen. {next}", "damaged_item": "Danke für Ihre Geduld, {name}. Ich kann einen kostenlosen Ersatz oder die volle Erstattung veranlassen und den Artikel kostenlos abholen lassen - was möchten Sie?", "legal_threat": "Ich verstehe, wie ernst das für Sie ist, {name}, und möchte es ordentlich klären. Ich prüfe jetzt den gesamten Verlauf Ihrer Bestellung und sage Ihnen genau, was ich heute für Sie tun kann.", "generic": "Danke für Ihre Geduld, {name}. Ich prüfe das sofort.", "refund_terms": "Nach der Abholung erhalten Sie die Erstattung innerhalb von 5-7 Werktagen auf die ursprüngliche Zahlungsart."},
}
EMPATHY_RX = re.compile(r"\b(sorry|apolog|understand|regret|tut mir leid|entschuldig|verständnis|bedauer)", re.IGNORECASE)


class FeedbackBody(BaseModel):
    suggestion_id: str = Field(max_length=60)
    kind: str = Field(pattern="^(reply|nba|form)$")
    action: str = Field(pattern="^(accepted|edited|rejected)$")
    final_text: str | None = Field(None, max_length=1000)


class MessageBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    agent_id: str = Field("AG-08", max_length=20)


class LinkBody(BaseModel):
    identifier: str = Field(min_length=3, max_length=120)


class TakeoverBody(BaseModel):
    agent_id: str = Field("AG-08", max_length=20)


class EndBody(BaseModel):
    disposition: str | None = None


def tone_coaching(conv: Conversation, draft: str | None = None) -> dict[str, Any]:
    last_cust = next((m for m in reversed(conv.messages) if m.role == "customer"), None)
    sentiment = conv.sentiment_trajectory[-1] if conv.sentiment_trajectory else 0.0
    text = draft if draft is not None else next((m.text for m in reversed(conv.messages) if m.role == "agent_human"), "")
    tips: list[str] = []
    if sentiment <= -0.4 and not EMPATHY_RX.search(text):
        tips.append("The customer is frustrated - lead with an acknowledgement or apology before the solution.")
    if text and len(text.split()) < 4:
        tips.append("Very short reply - add the next step and a timeframe.")
    if re.search(r"\b(you should have|your fault|as I said|wie gesagt|sie hätten)\b", text, re.IGNORECASE):
        tips.append("Avoid blame wording; focus on what you can do now.")
    if text and sum(c.isupper() for c in text) > 0.5 * max(sum(c.isalpha() for c in text), 1) and len(text) > 12:
        tips.append("Avoid ALL-CAPS - it reads as shouting.")
    if find_risky_promises(text):
        tips.append("Do not promise outcomes ('guaranteed refund'); say what policy allows.")
    if toxicity_rules(text)["Hate"] >= 2 or toxicity_rules(text)["Violence"] >= 4:
        tips.append("Message contains abusive language and will be blocked.")
    return {"customer_sentiment": sentiment, "customer_emotion": conv.understanding.emotion if conv.understanding else "neutral", "tips": tips, "ok": not tips, "last_customer": last_cust.text[:120] if last_cust else None}


def reminders(conv: Conversation) -> list[dict[str, Any]]:
    human = " ".join(m.text for m in conv.messages if m.role == "agent_human")
    intent = conv.understanding.intent if conv.understanding else "other"
    ok = {s["tool"] for s in conv.steps if s["status"] == "ok"}
    out = [
        {"id": "ai_disclosure", "label": "AI / recording disclosure was given at the start", "required": True, "done": any("disclosure" in m.flags for m in conv.messages), "detail": "Shown by the assistant at conversation start."},
        {"id": "recording_consent", "label": "Recording consent captured", "required": True, "done": conv.consent.recording in ("granted", "declined"), "detail": f"status: {conv.consent.recording}"},
        {"id": "verify_identity", "label": "Customer identity verified before account changes", "required": intent not in ("policy_question", "product_info", "greeting"), "done": conv.identity.verified, "detail": f"level L{conv.identity.level}"},
    ]
    if "issue_refund" in ok or intent in ("damaged_item", "refund_status", "return_request"):
        out.append({"id": "refund_terms", "label": "State refund terms: 5-7 business days after pickup, original payment method", "required": True, "done": bool(re.search(r"5-7|business days|werktage", human, re.IGNORECASE)), "detail": "Required statement for refunds."})
    if "legal_threat" in conv.risk_flags:
        out.append({"id": "no_liability", "label": "Do not admit liability or promise outcomes", "required": True, "done": not find_risky_promises(human), "detail": "Legal-risk conversation."})
        out.append({"id": "complaint_logged", "label": "Complaint ticket logged and legal desk notified", "required": True, "done": "create_ticket" in ok, "detail": "Create a ticket with priority 'urgent'."})
    if intent == "privacy_request":
        out.append({"id": "gdpr_log", "label": "Data-subject request logged (30-day clock)", "required": True, "done": "create_ticket" in ok, "detail": "Privacy policy privacy-001"})
    if intent == "address_change":
        out.append({"id": "address_readback", "label": "Read the new address back to the customer", "required": True, "done": bool(re.search(r"address|adresse", human, re.IGNORECASE)), "detail": "Address changes are a fraud vector."})
    return out


def autofill(conv: Conversation) -> dict[str, Any]:
    u = conv.understanding
    intent = u.intent if u else "other"
    cat = {"damaged_item": "returns", "return_request": "returns", "refund_status": "refund", "order_status": "delivery", "delivery_change": "delivery", "warranty_claim": "warranty", "billing_question": "billing", "complaint": "complaint", "installation_info": "installation"}.get(intent, "other")
    prio = "urgent" if {"legal_threat", "safety_issue", "fraud_suspected"} & set(conv.risk_flags) else "high" if (conv.sentiment_trajectory and conv.sentiment_trajectory[-1] <= -0.5) or "vulnerable_customer" in conv.risk_flags else "normal"
    amounts = [t.result.get("amount_eur") or t.result.get("refundable_amount_eur") for m in conv.messages for t in m.tools if isinstance(t.result, dict) and (t.result.get("amount_eur") or t.result.get("refundable_amount_eur"))]
    first = next((m.text for m in conv.messages if m.role == "customer"), "")
    return {
        "category": cat, "priority": prio, "order_id": conv.entities.get("order_id"), "customer_id": conv.identity.customer_id, "language": conv.language,
        "product": conv.entities.get("product"), "carrier": conv.entities.get("carrier"), "amount_eur": amounts[-1] if amounts else conv.entities.get("amount"),
        "summary": f"{intent.replace('_', ' ')}: {first[:140]}", "resolution_suggested": {"damaged_item": "replacement or refund + free pickup", "warranty_claim": "warranty claim", "complaint": "complaint handling + goodwill within limits"}.get(intent, "per policy"),
        "legal_risk": "legal_threat" in conv.risk_flags,
    }  # fmt: skip


async def build_assist(svc: Any, conv: Conversation, draft: str | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    u = conv.understanding
    intent = u.intent if u else "other"
    lang = conv.language if conv.language in REPLIES else "en"
    name = (conv.customer_label or "").strip() or ("Kunde" if lang == "de" else "there")
    pkg = (conv.handoff or {}).get("package") or {}
    kb_cache: dict[str, Any] = {}

    async def cite(doc_id: str) -> dict[str, Any] | None:
        if doc_id in kb_cache:
            return kb_cache[doc_id]
        chunk = next((c for c in svc.kb.chunks if c["doc_id"] == doc_id), None)
        kb_cache[doc_id] = {"doc_id": doc_id, "title": chunk["title"], "chunk_id": chunk["id"], "snippet": chunk["text"][:220], "version": chunk["version"]} if chunk else None
        return kb_cache[doc_id]

    nbas = []
    specs = list(NBA.get(intent, [("Clarify the request and confirm what has already been tried", "The package shows the assistant's steps.", "service-001", None)]))
    if "legal_threat" in conv.risk_flags:
        specs = [("Acknowledge; do not admit liability; summarise the history back", "Avoid promising outcomes.", "service-003", None), ("Review order timeline and offer the policy remedy + goodwill up to EUR 50", "Goodwill above EUR 50 needs a specialist.", "refunds-004", "goodwill_credit"), ("Create an urgent complaint ticket and notify the legal desk", "Complaints are answered within 5 working days.", "service-003", "create_ticket")] + specs[:1]
    if "vulnerable_customer" in conv.risk_flags:
        specs = [("Slow down, use plain language and offer a callback", "Vulnerable customers are handled by the care team.", "service-002", None)] + specs
    appr = await svc.repo.query("approvals", {"conv_id": conv.id, "status": "pending"})
    for a in appr:
        specs.insert(0, (f"Review approval {a['id']}: {a['kind']} EUR {a['amount']:.2f}", "Above the autonomous cap - a supervisor approves or declines.", "refunds-001", None))
    for i, (title, why, doc, tool) in enumerate(specs[:5]):
        nbas.append({"id": f"nba_{i}", "rank": i + 1, "title": title, "rationale": why, "citation": await cite(doc), "tool": tool, "confidence": round(max(0.55, 0.92 - 0.08 * i), 2)})
    reps = REPLIES[lang]
    nxt = reps.get("damaged_item") if intent == "damaged_item" else reps["generic"]
    suggestions = [
        {"id": "rep_0", "text": reps["empathy"].format(name=name, next=nxt), "tone": "empathic", "citations": [await cite("damage-001")] if intent == "damaged_item" else []},
        {"id": "rep_1", "text": reps["legal_threat"].format(name=name) if "legal_threat" in conv.risk_flags else reps["damaged_item"].format(name=name) if intent == "damaged_item" else reps["generic"].format(name=name), "tone": "professional", "citations": [await cite("service-003")] if "legal_threat" in conv.risk_flags else []},
        {"id": "rep_2", "text": reps["refund_terms"], "tone": "informative", "citations": [await cite("refunds-001")]},
    ]
    suggestions = [{**s, "citations": [c for c in s["citations"] if c]} for s in suggestions]
    if not svc.llm.deterministic:
        try:
            convo = "\n".join(f"{m.role}: {m.text}" for m in conv.messages[-10:] if m.visible_to_customer)[-2500:]
            res = await svc.llm.chat(
                [{"role": "system", "content": f"You are an agent-assist copilot for a human contact-center agent. Write ONE short suggested reply in language '{lang}' (max 3 sentences) the agent can send, empathic, grounded ONLY in the handoff summary and policy snippets, never promising outcomes. Return JSON {{\"reply\": str}}."},
                 {"role": "user", "content": f"Handoff summary: {pkg.get('summary', '')}\nSuggested resolution: {pkg.get('suggested_resolution', '')}\nPolicy: {[c['snippet'][:160] for c in pkg.get('policy_citations', [])[:2]]}\nConversation:\n{convo}"}],
                role="nano", max_tokens=260, reasoning_effort="minimal", json_mode=True, feature="assist", conv_id=conv.id,
            )  # fmt: skip
            reply = json.loads(res.text or "{}").get("reply")
            if reply:
                suggestions.insert(0, {"id": "rep_llm", "text": str(reply)[:600], "tone": "ai-composed", "citations": [c for c in [await cite("service-003" if "legal_threat" in conv.risk_flags else "damage-001")] if c]})
        except Exception:
            pass
    agent_lang = "en"
    translations: dict[str, Any] = {}
    if conv.language != agent_lang:
        for m in [m for m in conv.messages if m.role == "customer"][-4:]:
            if agent_lang not in m.translations:
                m.translations[agent_lang] = (await translate(svc, m.text, agent_lang, conv.language))["text"]
            translations[str(m.idx)] = m.translations[agent_lang]
    return {
        "conversation_id": conv.id, "generated_ms": round((time.perf_counter() - t0) * 1000, 1), "intent": intent, "language": conv.language,
        "next_best_actions": nbas, "suggested_replies": suggestions, "compliance_reminders": reminders(conv), "form_autofill": autofill(conv),
        "tone": tone_coaching(conv, draft), "translations": translations, "package_summary": pkg.get("summary"),
    }  # fmt: skip


async def _conv(request: Request, conv_id: str) -> tuple[Any, Conversation]:
    svc = request.app.state.services
    conv = await svc.store.get(conv_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    return svc, conv


@router.get("/console")
async def console(request: Request, agent_id: str = "AG-08", _: Actor = Depends(require("agent.console"))) -> dict[str, Any]:
    """Everything the console needs: waiting handoffs, my conversations, live AI conversations that can be taken over."""
    svc = request.app.state.services
    from ..handoff import queue_item

    waiting = sorted((c for c in svc.store.cache.values() if c.status == "waiting_human"), key=lambda c: -c.priority)
    mine = [c for c in svc.store.cache.values() if c.assigned_agent == agent_id and c.status == "with_human"]
    live = [c for c in svc.store.cache.values() if c.handler == "ai" and c.status == "active" and not c.eval_run_id]
    return {"agent_id": agent_id, "waiting": [queue_item(svc, c) for c in waiting], "mine": [svc.store.summary(c) for c in mine], "live_ai": [svc.store.summary(c) for c in live][:30]}


@router.get("/{conv_id}")
async def assist(conv_id: str, request: Request, draft: str | None = None, _: Actor = Depends(require("assist"))) -> dict[str, Any]:
    svc, conv = await _conv(request, conv_id)
    out = await build_assist(svc, conv, draft)
    await svc.store.save(conv, publish=False)
    return out


@router.get("/{conv_id}/conversation")
async def conversation(conv_id: str, request: Request, actor: Actor = Depends(require("agent.console", "supervisor", "qa.read", "audit.read"))) -> dict[str, Any]:
    svc, conv = await _conv(request, conv_id)
    await svc.access_audit.log("conversation.viewed", actor=f"{actor.role}:{actor.user}", resource=conv_id, conv_id=conv_id)
    d = conv.model_dump(exclude={"identity"})
    d["identity"] = {"verified": conv.identity.verified, "level": conv.identity.level, "method": conv.identity.method, "customer_id": conv.identity.customer_id, "locked": conv.identity.locked}
    d["outbox"] = [{k: v for k, v in o.items() if k != "code"} for o in conv.outbox]
    d["summary"] = svc.store.summary(conv)
    d["disposition_preview"] = classify_disposition(conv)
    return d


@router.post("/{conv_id}/takeover")
async def takeover(conv_id: str, body: TakeoverBody, request: Request, actor: Actor = Depends(require("handoff.accept", "supervisor"))) -> dict[str, Any]:
    svc, conv = await _conv(request, conv_id)
    conv = await svc.orchestrator.takeover(conv_id, body.agent_id, actor.role)
    return {"status": conv.status, "handler": conv.handler, "assigned_agent": conv.assigned_agent}


@router.post("/{conv_id}/message")
async def send_message(conv_id: str, body: MessageBody, request: Request, actor: Actor = Depends(require("agent.console", "supervisor"))) -> dict[str, Any]:
    svc, conv = await _conv(request, conv_id)
    if conv.handler != "human":
        raise HTTPException(409, {"error": "not_handling", "message": "Accept or take over the conversation before replying."})
    tox = toxicity_rules(body.text)
    if tox["Hate"] >= 2 or tox["Violence"] >= 4:
        await svc.audit.log("compliance.agent_output_blocked", actor=f"{actor.role}:{actor.user}", resource=conv_id, conv_id=conv_id, outcome="blocked", detail={"toxicity": tox})
        raise HTTPException(422, {"error": "message_blocked", "message": "This message contains abusive language and was not sent."})
    og = svc.guard.inspect_output(body.text, lang=conv.language)
    msg = await svc.orchestrator.human_message(conv_id, body.agent_id, og.text)
    if og.issues:
        await svc.audit.log("compliance.agent_output_modified", actor=f"{actor.role}:{actor.user}", resource=conv_id, conv_id=conv_id, outcome="blocked", detail={"issues": og.issues})
    return {"message": msg.model_dump(), "guard": {"modified": bool(og.issues), "issues": og.issues}}


@router.post("/{conv_id}/whisper")
async def whisper(conv_id: str, body: MessageBody, request: Request, actor: Actor = Depends(require("supervisor"))) -> dict[str, Any]:
    """Supervisor whisper: guidance visible to the human agent (or injected as silent guidance for the AI) - never shown to the customer."""
    svc, conv = await _conv(request, conv_id)
    async with svc.store.lock(conv_id):
        conv.supervisor_notes.append({"ts": now(), "by": actor.user, "text": body.text[:400]})
        m = conv.add("supervisor", body.text[:400], author=actor.user, visible_to_customer=False, flags=["whisper"])
        await svc.store.save(conv)
    await svc.bus.publish(f"conv:{conv_id}", {"type": "whisper", "message": m.model_dump()})
    await svc.audit.log("supervisor.whisper", actor=actor.user, resource=conv_id, conv_id=conv_id, detail={"text": body.text[:120]})
    return {"ok": True}


@router.post("/{conv_id}/link-customer")
async def link_customer(conv_id: str, body: LinkBody, request: Request, actor: Actor = Depends(require("agent.console", "supervisor"))) -> dict[str, Any]:
    """The human verifies the customer (e.g. by phone) and links the account; audited, counts as L1."""
    svc, conv = await _conv(request, conv_id)
    cust = await svc.oms.find_customer(body.identifier)
    if not cust:
        raise HTTPException(404, "no matching customer")
    conv.identity.verified, conv.identity.customer_id, conv.identity.method = True, cust["id"], "agent_verified"
    conv.identity.level = max(conv.identity.level, 1)
    conv.customer_label = cust["first_name"]
    await svc.audit.log("identity.agent_linked", actor=f"{actor.role}:{actor.user}", resource=cust["id"], conv_id=conv_id)
    await svc.store.save(conv)
    return {"linked": True, "customer": cust["first_name"], "level": conv.identity.level}


@router.post("/{conv_id}/end")
async def end(conv_id: str, body: EndBody, request: Request, actor: Actor = Depends(require("agent.console", "supervisor"))) -> dict[str, Any]:
    svc, conv = await _conv(request, conv_id)
    conv = await svc.orchestrator.close(conv_id, by=f"human:{actor.user}", resolved=True)
    await svc.drain() if svc.sandbox else None
    return {"status": conv.status}


@router.post("/{conv_id}/feedback")
async def feedback(conv_id: str, body: FeedbackBody, request: Request, actor: Actor = Depends(require("assist"))) -> dict[str, Any]:
    svc, _ = await _conv(request, conv_id)
    doc = {"id": new_id("fb"), "type": "assist_feedback", "conv_id": conv_id, "suggestion_id": body.suggestion_id, "kind": body.kind, "action": body.action, "agent": actor.user, "ts": now(), "final_text": (body.final_text or "")[:300]}
    await svc.repo.put("metrics_samples", doc, ttl=180 * 86400)
    return {"logged": True}


@router.get("/stats/acceptance")
async def acceptance(request: Request, _: Actor = Depends(require("assist", "metrics.read"))) -> dict[str, Any]:
    rows = await request.app.state.services.repo.query("metrics_samples", {"type": "assist_feedback"})
    n = len(rows)
    by = {a: sum(1 for r in rows if r["action"] == a) for a in ("accepted", "edited", "rejected")}
    return {"total": n, **by, "acceptance_rate": round((by["accepted"] + by["edited"]) / n, 3) if n else None}


@router.get("/{conv_id}/search")
async def search(conv_id: str, q: str, request: Request, _: Actor = Depends(require("assist", "kb.read"))) -> dict[str, Any]:
    svc, _c = await _conv(request, conv_id)
    res = await svc.kb.search(q[:300], k=4)
    return {"answerable": res["answerable"], "hits": [{"doc_id": h["doc_id"], "title": h["title"], "section": h["heading"], "text": h["text"][:500], "chunk_id": h["chunk_id"], "score": h["score"]} for h in res["hits"]]}


@router.get("/{conv_id}/translate")
async def translate_text(conv_id: str, text: str, request: Request, target: str = "en", _: Actor = Depends(require("assist"))) -> dict[str, Any]:
    return await translate(request.app.state.services, text[:1500], target)


@router.get("/explicit-request/check")
async def explicit_check(text: str) -> dict[str, bool]:
    return {"explicit_human_request": bool(EXPLICIT_HUMAN.search(text))}
