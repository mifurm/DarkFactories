"""CC-08 Agent Assist copilot + human-agent console API: live next-best-action with citations, suggested replies, compliance
reminders, form auto-fill, tone coaching, translation, chat takeover. The copilot never executes a state-changing tool itself."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core import i18n
from ...core.money import format_money, pick
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

NBA = {  # intent -> [(doc id, tool)]; the title / rationale of entry i come from the catalog keys nba.<intent>.<i>.title / .why (request locale)
    "damaged_item": [("damage-001", None), ("refunds-001", None), ("returns-003", "get_available_slots")],
    "return_request": [("returns-001", "check_return_eligibility"), ("returns-003", "initiate_return")],
    "refund_status": [("refunds-003", "lookup_order")],
    "order_status": [("delivery-002", "track_shipment")],
    "delivery_change": [("delivery-003", "get_available_slots")],
    "warranty_claim": [("warranty-002", "warranty_claim")],
    "complaint": [("service-003", "create_ticket")],
    "address_change": [("delivery-007", "update_address")],
}
REPLIES = {
    "en": {"empathy": "I'm really sorry about this, {name}. I've read everything you told our assistant, so you won't need to repeat it. {next}", "damaged_item": "Thank you for your patience, {name}. I can arrange a free replacement or a full refund and collect the item at no cost - which would you prefer?", "legal_threat": "I understand how serious this is for you, {name}, and I want to resolve it properly. Let me review the full history of your order and tell you exactly what I can do today.", "generic": "Thanks for your patience, {name}. Let me look into this right away.", "refund_terms": "Once the item is collected, the refund reaches your original payment method within 5-7 business days."},
    "pl": {"empathy": "Bardzo przykro mi z powodu tej sytuacji. Znam już całą Państwa rozmowę z naszym asystentem, więc nie trzeba niczego powtarzać. {next}", "damaged_item": "Dziękuję za cierpliwość. Mogę zlecić bezpłatną wymianę albo pełny zwrot środków; towar odbierzemy bezpłatnie. Którą opcję mam zrealizować?", "legal_threat": "Rozumiem, jak poważna jest ta sprawa, i chcę ją rzetelnie wyjaśnić. Sprawdzę pełną historię zamówienia i powiem, co mogę zrobić już dziś.", "generic": "Dziękuję za cierpliwość. Już sprawdzam tę sprawę.", "refund_terms": "Po odebraniu towaru zwrot środków trafi na tę samą metodę płatności, której użyto przy zakupie, w ciągu 5–7 dni roboczych."},
    "de": {"empathy": "Das tut mir wirklich leid, {name}. Ich habe alles gelesen, was Sie unserem Assistenten geschildert haben - Sie müssen nichts wiederholen. {next}", "damaged_item": "Danke für Ihre Geduld, {name}. Ich kann einen kostenlosen Ersatz oder die volle Erstattung veranlassen und den Artikel kostenlos abholen lassen - was möchten Sie?", "legal_threat": "Ich verstehe, wie ernst das für Sie ist, {name}, und möchte es ordentlich klären. Ich prüfe jetzt den gesamten Verlauf Ihrer Bestellung und sage Ihnen genau, was ich heute für Sie tun kann.", "generic": "Danke für Ihre Geduld, {name}. Ich prüfe das sofort.", "refund_terms": "Nach der Abholung erhalten Sie die Erstattung innerhalb von 5-7 Werktagen auf die ursprüngliche Zahlungsart."},
}
EMPATHY_RX = re.compile(r"\b(sorry|apolog|understand|regret|tut mir leid|entschuldig|verständnis|bedauer|przepraszam|przykro|rozumiem|ubolewam|współczuj)", re.IGNORECASE)


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


def tone_coaching(conv: Conversation, draft: str | None = None, lang: str | None = None) -> dict[str, Any]:
    lang = lang or i18n.current_locale()
    last_cust = next((m for m in reversed(conv.messages) if m.role == "customer"), None)
    sentiment = conv.sentiment_trajectory[-1] if conv.sentiment_trajectory else 0.0
    text = draft if draft is not None else next((m.text for m in reversed(conv.messages) if m.role == "agent_human"), "")
    tips: list[str] = []
    if sentiment <= -0.4 and not EMPATHY_RX.search(text):
        tips.append(i18n.msg("assist.tone.frustrated", lang))
    if text and len(text.split()) < 4:
        tips.append(i18n.msg("assist.tone.short", lang))
    if re.search(r"\b(you should have|your fault|as I said|wie gesagt|sie hätten|to pana wina|to pani wina|jak już mówiłem|jak już mówiłam|powinien pan|powinna pani)\b", text, re.IGNORECASE):
        tips.append(i18n.msg("assist.tone.blame", lang))
    if text and sum(c.isupper() for c in text) > 0.5 * max(sum(c.isalpha() for c in text), 1) and len(text) > 12:
        tips.append(i18n.msg("assist.tone.caps", lang))
    if find_risky_promises(text):
        tips.append(i18n.msg("assist.tone.promise", lang))
    if toxicity_rules(text)["Hate"] >= 2 or toxicity_rules(text)["Violence"] >= 4:
        tips.append(i18n.msg("assist.tone.abusive", lang))
    return {"customer_sentiment": sentiment, "customer_emotion": conv.understanding.emotion if conv.understanding else "neutral", "tips": tips, "ok": not tips, "last_customer": last_cust.text[:120] if last_cust else None}


def reminders(conv: Conversation, lang: str | None = None) -> list[dict[str, Any]]:
    lang = lang or i18n.current_locale()
    human = " ".join(m.text for m in conv.messages if m.role == "agent_human")
    intent = conv.understanding.intent if conv.understanding else "other"
    ok = {s["tool"] for s in conv.steps if s["status"] == "ok"}

    def item(rid: str, required: bool, done: bool, **params: Any) -> dict[str, Any]:
        return {"id": rid, "label": i18n.msg(f"assist.rem.{rid}", lang), "required": required, "done": done, "detail": i18n.msg(f"assist.rem.{rid}.detail", lang, **params)}

    out = [
        item("ai_disclosure", True, any("disclosure" in m.flags for m in conv.messages)),
        item("recording_consent", True, conv.consent.recording in ("granted", "declined"), status=conv.consent.recording),
        item("verify_identity", intent not in ("policy_question", "product_info", "greeting"), conv.identity.verified, level=conv.identity.level),
    ]
    if "issue_refund" in ok or intent in ("damaged_item", "refund_status", "return_request"):
        out.append(item("refund_terms", True, bool(re.search(r"5-7|business days|werktage|dni\s+robocz", human, re.IGNORECASE))))
    if "legal_threat" in conv.risk_flags:
        out.append(item("no_liability", True, not find_risky_promises(human)))
        out.append(item("complaint_logged", True, "create_ticket" in ok))
    if intent == "privacy_request":
        out.append(item("gdpr_log", True, "create_ticket" in ok))
    if intent == "address_change":
        out.append(item("address_readback", True, bool(re.search(r"address|adresse|adres", human, re.IGNORECASE))))
    return out


def autofill(conv: Conversation) -> dict[str, Any]:
    u = conv.understanding
    intent = u.intent if u else "other"
    cat = {"damaged_item": "returns", "return_request": "returns", "refund_status": "refund", "order_status": "delivery", "delivery_change": "delivery", "warranty_claim": "warranty", "billing_question": "billing", "complaint": "complaint", "installation_info": "installation"}.get(intent, "other")
    prio = "urgent" if {"legal_threat", "safety_issue", "fraud_suspected"} & set(conv.risk_flags) else "high" if (conv.sentiment_trajectory and conv.sentiment_trajectory[-1] <= -0.5) or "vulnerable_customer" in conv.risk_flags else "normal"
    amounts = [(pick(t.result, "amount") or pick(t.result, "refundable_amount"), t.result.get("currency") or "EUR") for m in conv.messages for t in m.tools if isinstance(t.result, dict) and (pick(t.result, "amount") or pick(t.result, "refundable_amount"))]
    first = next((m.text for m in conv.messages if m.role == "customer"), "")
    return {
        "category": cat, "priority": prio, "order_id": conv.entities.get("order_id"), "customer_id": conv.identity.customer_id, "language": conv.language,
        "product": conv.entities.get("product"), "carrier": conv.entities.get("carrier"), "amount_eur": amounts[-1][0] if amounts and amounts[-1][1] == "EUR" else (None if amounts else conv.entities.get("amount")),
        "amount": amounts[-1][0] if amounts else conv.entities.get("amount"), "currency": amounts[-1][1] if amounts else conv.entities.get("currency", "EUR"),
        "summary": f"{i18n.label('intent', intent, i18n.current_locale(), intent.replace('_', ' ')) if i18n.current_locale() != 'en' else intent.replace('_', ' ')}: {first[:140]}", "resolution_suggested": i18n.msg(f"assist.resolution.{intent}" if intent in ("damaged_item", "warranty_claim", "complaint") else "assist.resolution.default"),
        "legal_risk": "legal_threat" in conv.risk_flags,
    }  # fmt: skip


async def build_assist(svc: Any, conv: Conversation, draft: str | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    u = conv.understanding
    intent = u.intent if u else "other"
    lang = conv.language if conv.language in REPLIES else "en"
    name = (conv.customer_label or "").strip() or ("Kunde" if lang == "de" else "there")  # (Polish replies address the customer formally and need no name: no vocative guessing)
    pkg = (conv.handoff or {}).get("package") or {}
    kb_cache: dict[str, Any] = {}

    async def cite(doc_id: str) -> dict[str, Any] | None:
        if doc_id in kb_cache:
            return kb_cache[doc_id]
        pl_id = f"{doc_id}-pl" if i18n.current_locale() == "pl" else doc_id  # Polish operators get the Polish article when one exists
        chunk = next((c for c in svc.kb.chunks if c["doc_id"] == pl_id), None) or next((c for c in svc.kb.chunks if c["doc_id"] == doc_id), None)
        kb_cache[doc_id] = {"doc_id": chunk["doc_id"], "title": chunk["title"], "chunk_id": chunk["id"], "snippet": chunk["text"][:220], "version": chunk["version"]} if chunk else None
        return kb_cache[doc_id]

    nbas = []
    ui = i18n.current_locale()  # the operator's language: next-best-actions, reminders and coaching are for the human agent (customer replies below use the conversation language)

    def nba(key: str, i: int, doc: str, tool: str | None) -> tuple[str, str, str, str | None]:
        return (i18n.msg(f"nba.{key}.{i}.title", ui), i18n.msg(f"nba.{key}.{i}.why", ui), doc, tool)

    base = [nba(intent, i, doc, tool) for i, (doc, tool) in enumerate(NBA.get(intent, []))] or [nba("default", 0, "service-001", None)]
    specs = list(base)
    if "legal_threat" in conv.risk_flags:
        specs = [nba("legal", 0, "service-003", None), nba("legal", 1, "refunds-004", "goodwill_credit"), nba("legal", 2, "service-003", "create_ticket")] + base[:1]
    if "vulnerable_customer" in conv.risk_flags:
        specs = [nba("vulnerable", 0, "service-002", None)] + specs
    appr = await svc.repo.query("approvals", {"conv_id": conv.id, "status": "pending"})
    for a in appr:
        kind = i18n.label("assist.kind", a["kind"], ui, a["kind"])
        specs.insert(0, (i18n.msg("nba.approval.title", ui, id=a["id"], kind=kind, money=format_money(a["amount"], a.get("currency"), ui)), i18n.msg("nba.approval.why", ui), "refunds-001", None))
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
    agent_lang = ui
    translations: dict[str, Any] = {}
    if conv.language != agent_lang:
        for m in [m for m in conv.messages if m.role == "customer"][-4:]:
            if agent_lang not in m.translations:
                m.translations[agent_lang] = (await translate(svc, m.text, agent_lang, conv.language))["text"]
            translations[str(m.idx)] = m.translations[agent_lang]
    return {
        "conversation_id": conv.id, "generated_ms": round((time.perf_counter() - t0) * 1000, 1), "intent": intent, "language": conv.language,
        "next_best_actions": nbas, "suggested_replies": suggestions, "compliance_reminders": reminders(conv, ui), "form_autofill": autofill(conv),
        "tone": tone_coaching(conv, draft, ui), "translations": translations, "package_summary": pkg.get("summary"),
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
