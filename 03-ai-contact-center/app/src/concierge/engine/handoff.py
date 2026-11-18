"""Warm handoff (CC-07): context-package builder, routing + worker offer, customer notice, live delivery to consoles."""

from __future__ import annotations

import time
import uuid
from typing import Any

from ..core.redaction import mask_email, mask_phone, redact_text
from .models import Citation, Conversation, now
from .routing import Trigger, route, select_worker

NOTICE = {
    "en": "I'm bringing in a colleague who can see our conversation so far, so you won't have to repeat anything. {wait}",
    "de": "Ich hole eine Kollegin bzw. einen Kollegen dazu, die/der unser Gespräch bereits sieht - Sie müssen nichts wiederholen. {wait}",
    "fr": "Je fais appel à un collègue qui voit déjà notre conversation, vous n'aurez rien à répéter. {wait}",
    "es": "Voy a pasar la conversación a un compañero que ya ve todo lo hablado, no tendrá que repetir nada. {wait}",
    "it": "Passo la conversazione a un collega che vede già tutto, non dovrà ripetere nulla. {wait}",
    "nl": "Ik schakel een collega in die ons gesprek al kan zien, u hoeft niets te herhalen. {wait}",
    "pl": "Przekazuję rozmowę koledze, który widzi już naszą rozmowę - nie musi Pan/Pani niczego powtarzać. {wait}",
    "pt": "Vou chamar um colega que já vê a nossa conversa, por isso não precisa de repetir nada. {wait}",
    "sv": "Jag kopplar in en kollega som redan ser vårt samtal, du behöver inte upprepa något. {wait}",
}
WAIT = {"en": "Estimated wait: about {m} min.", "de": "Voraussichtliche Wartezeit: ca. {m} Min.", "fr": "Attente estimée : environ {m} min.", "es": "Espera estimada: unos {m} min.", "it": "Attesa stimata: circa {m} min.", "nl": "Geschatte wachttijd: ca. {m} min.", "pl": "Szacowany czas oczekiwania: ok. {m} min.", "pt": "Espera estimada: cerca de {m} min.", "sv": "Beräknad väntetid: ca {m} min."}
CALLBACK = {"en": "No colleague is available right now - I can arrange a callback instead and attach everything we discussed.", "de": "Gerade ist niemand verfügbar - ich kann stattdessen einen Rückruf vereinbaren und alles Besprochene anhängen."}

SUGGESTED = {
    "legal_threat": "Acknowledge the frustration and the seriousness of the complaint; do not admit liability or promise outcomes. Review the order history, offer the policy remedy and (within limits) goodwill, open a complaint ticket and notify the legal/complaints desk.",
    "vulnerable_customer": "Slow down, use plain language, offer a callback and a single point of contact; arrange the practical help (pickup/redelivery) on the customer's behalf.",
    "fraud_suspected": "Do not discuss account details; run full step-up verification and follow the fraud procedure; flag the account.",
    "safety_issue": "Tell the customer to stop using the product and follow emergency guidance; open a priority safety ticket and notify the product-safety team.",
    "explicit_request": "Greet the customer by name, confirm what the assistant already established, continue from the last step - do not re-ask for verified details.",
    "sentiment": "Lead with empathy and ownership; summarise what was done; offer the most generous remedy allowed by policy.",
    "policy_block": "Review the blocked/pending action; approve within your authority or escalate to a supervisor.",
    "tool_failure": "Complete the failed step manually in the back-office and confirm to the customer.",
    "loop": "Re-state the customer's problem in your own words, confirm understanding, then resolve directly.",
    "knowledge_gap": "Answer from the policy library or create a knowledge-gap ticket; confirm with the customer.",
}
INTENT_QUERY = {"damaged_item": "damaged on delivery replacement refund pickup", "return_request": "returns policy 30 days", "refund_status": "refund timing method", "delivery_change": "rescheduling a delivery", "order_status": "tracking delivery status", "warranty_claim": "warranty claim", "complaint": "complaints procedure", "goodwill_request": "goodwill gestures delay compensation", "billing_question": "double charges authorisation holds", "installation_info": "installation missed appointments", "address_change": "changing the delivery address"}


def _extractive_summary(conv: Conversation) -> str:
    u = conv.understanding
    cust = conv.customer_label or "an unverified customer"
    intent = (u.intent if u else "other").replace("_", " ")
    first = next((m.text for m in conv.messages if m.role == "customer"), "")
    done = [s["summary"] for s in conv.steps if s["status"] == "ok" and s["tool"] in ("initiate_return", "schedule_pickup", "issue_refund", "reschedule_delivery", "update_address", "goodwill_credit", "warranty_claim")]
    bits = [f"{cust} contacted us via {conv.channel.replace('_', ' ')} in {conv.language.upper()} about: {intent}.", f"Opening message: \"{redact_text(first)[:160]}\"."]
    if conv.entities.get("order_id"):
        bits.append(f"Order {conv.entities['order_id']} is involved.")
    bits.append("Identity: " + (f"verified (level L{conv.identity.level}, {conv.identity.method})." if conv.identity.verified else "NOT verified."))
    if done:
        bits.append("Completed by the assistant: " + "; ".join(done[:4]) + ".")
    return " ".join(bits)


async def build_package(svc: Any, conv: Conversation, trigger: Trigger | dict[str, Any], decision: Any) -> dict[str, Any]:
    t = trigger.to_dict() if hasattr(trigger, "to_dict") else dict(trigger)
    u = conv.understanding
    cust = await svc.oms.get_customer(conv.identity.customer_id) if conv.identity.customer_id else None
    summary = _extractive_summary(conv)
    suggested = SUGGESTED.get(t["code"], SUGGESTED["explicit_request"])
    llm_used = False
    if not svc.llm.deterministic:
        try:
            convo = "\n".join(f"{m.role}: {m.text}" for m in conv.messages[-14:] if m.visible_to_customer)[:3500]
            steps = "; ".join(f"{s['tool']}:{s['status']}" for s in conv.steps[-8:])
            res = await svc.llm.chat(
                [{"role": "system", "content": "You write handoff notes for human contact-center agents. Be factual, 3-4 sentences, no PII beyond first names. Return JSON {\"summary\": str, \"suggested_resolution\": str}."},
                 {"role": "user", "content": f"Escalation trigger: {t['code']} ({t['reason']}).\nSteps tried: {steps}\nConversation:\n{convo}"}],
                role="nano", max_tokens=420, reasoning_effort="minimal", json_mode=True, feature="handoff", conv_id=conv.id,
            )  # fmt: skip
            import json as _json

            data = _json.loads(res.text or "{}")
            if data.get("summary"):
                summary, llm_used = str(data["summary"])[:900], True
            if data.get("suggested_resolution"):
                suggested = str(data["suggested_resolution"])[:700]
        except Exception:
            llm_used = False
    cites: list[dict[str, Any]] = []
    try:
        q = INTENT_QUERY.get(u.intent if u else "other", "returns policy")
        if t["code"] == "legal_threat":
            q = "complaints procedure escalation"
        res = await svc.kb.search(q, k=3)
        cites = [Citation(ref=f"K{i}", doc_id=h["doc_id"], title=h["title"], chunk_id=h["chunk_id"], snippet=h["text"][:200], score=h["score"], version=h["version"]).model_dump() for i, h in enumerate(res["hits"], 1)]
    except Exception:
        cites = []
    approvals = await svc.repo.query("approvals", {"conv_id": conv.id})
    traj = conv.sentiment_trajectory[-12:]
    pkg: dict[str, Any] = {
        "conversation_id": conv.id, "created_at": now(), "trigger": t, "language": conv.language, "channel": conv.channel,
        "customer": {"id_masked": (conv.identity.customer_id or "")[:3] + "•••" if conv.identity.customer_id else None, "first_name": cust["first_name"] if cust else conv.customer_label, "tier": cust["tier"] if cust else None, "market": cust["market"] if cust else None, "phone_masked": mask_phone(cust["phone"]) if cust else None, "email_masked": mask_email(cust["email"]) if cust else None, "vulnerable": bool(cust and cust.get("vulnerable"))},
        "verification": {"verified": conv.identity.verified, "level": conv.identity.level, "method": conv.identity.method},
        "summary": summary, "summary_source": "llm" if llm_used else "extractive",
        "intent": u.intent if u else "other", "entities": conv.entities | (u.entities if u else {}),
        "steps_tried": [{"tool": s["tool"], "status": s["status"], "summary": s["summary"], "ts": s["ts"]} for s in conv.steps],
        "sentiment": {"current": traj[-1] if traj else 0.0, "trajectory": traj, "emotion": u.emotion if u else "neutral"},
        "risk_flags": sorted(set(conv.risk_flags) | set(u.risk_flags if u else [])),
        "suggested_resolution": suggested, "policy_citations": cites,
        "pending_approvals": [{"id": a["id"], "kind": a["kind"], "amount": a["amount"], "status": a["status"]} for a in approvals],
        "routing": decision.to_dict(), "sla_s": decision.sla_s,
        "transcript_tail": [{"role": m.role, "text": m.text, "ts": m.ts} for m in conv.messages[-12:] if m.visible_to_customer],
        "transcript_link": f"/agent?conversation={conv.id}", "pii_minimised": True,
    }  # fmt: skip
    pkg["completeness"] = completeness(pkg)
    return pkg


REQUIRED = ["summary", "intent", "entities", "steps_tried", "sentiment", "risk_flags", "suggested_resolution", "policy_citations", "language", "verification", "sla_s", "transcript_link", "customer", "routing"]


def completeness(pkg: dict[str, Any]) -> int:
    ok = 0
    for k in REQUIRED:
        v = pkg.get(k)
        if k == "steps_tried":
            ok += 1 if isinstance(v, list) else 0
        elif k == "policy_citations":
            ok += 1 if v else 0
        elif k == "entities":
            ok += 1 if isinstance(v, dict) else 0
        elif v not in (None, "", [], {}):
            ok += 1
    return round(100 * ok / len(REQUIRED))


async def initiate(svc: Any, conv: Conversation, trigger: Trigger | dict[str, Any], *, notify: bool = True) -> dict[str, Any]:
    """Escalate: route, build the context package, notify the customer, push to consoles. Idempotent per conversation."""
    if conv.handler != "ai" and conv.handoff:
        return conv.handoff
    t0 = time.perf_counter()
    t = trigger if hasattr(trigger, "to_dict") else Trigger(trigger.get("code", "agent_decision"), trigger.get("reason", ""), trigger.get("severity", "high"))
    cust = await svc.oms.get_customer(conv.identity.customer_id) if conv.identity.customer_id else None
    u = conv.understanding
    if u is None:
        from .models import Understanding

        u = Understanding(language=conv.language)
    if t.code in ("legal_threat", "fraud_suspected", "safety_issue", "vulnerable_customer", "regulatory_complaint") and t.code not in u.risk_flags:
        u.risk_flags = sorted({*u.risk_flags, t.code})
    decision = route(u, vip=bool(cust and cust["tier"] == "vip"), vulnerable=bool(cust and cust.get("vulnerable")), language=conv.language, channel=conv.channel, extra_risks=conv.risk_flags)
    workers = svc.ext.setdefault("workers", [])
    worker = select_worker(decision, conv.channel, workers)
    pkg = await build_package(svc, conv, t, decision)
    handoff_id = f"ho_{uuid.uuid4().hex[:8]}"
    conv.handler, conv.status, conv.queue, conv.priority = "queue", "waiting_human", decision.queue, decision.priority
    depth = sum(1 for c in svc.store.cache.values() if c.status == "waiting_human" and c.queue == decision.queue and c.id != conv.id)
    est_min = max(1, round((depth + 1) * (1.5 if worker else 4)))
    conv.handoff = {"id": handoff_id, "created_at": now(), "trigger": t.to_dict(), "routing": decision.to_dict(), "offered_to": worker["id"] if worker else None, "package": pkg, "state": "offered" if worker else "no_agent_available", "package_ms": round((time.perf_counter() - t0) * 1000, 1), "accepted_at": None, "queue_depth": depth, "est_wait_min": est_min}
    if notify:
        lang = conv.language if conv.language in NOTICE else "en"
        text = NOTICE[lang].format(wait=WAIT.get(lang, WAIT["en"]).format(m=est_min))
        if not worker:
            text += " " + CALLBACK.get(lang, CALLBACK["en"])
        conv.add("agent_ai", text, lang=conv.language, flags=["handoff_notice"], meta={"handoff_id": handoff_id})
    conv.active_agent = "escalation"
    conv.agent_trace.append({"ts": now(), "agent": "escalation", "event": "handoff", "trigger": t.code})
    await svc.audit.log("handoff.initiated", actor="ai", resource=conv.id, conv_id=conv.id, detail={"trigger": t.code, "queue": decision.queue, "priority": decision.priority, "completeness": pkg["completeness"], "worker": worker["id"] if worker else None})
    event = {"type": "handoff.created", "conversation_id": conv.id, "queue": decision.queue, "priority": decision.priority, "trigger": t.to_dict(), "completeness": pkg["completeness"], "offered_to": worker["id"] if worker else None, "package": pkg}
    await svc.bus.publish("agents", event)
    await svc.bus.publish(f"queue:{decision.queue}", event)
    await svc.bus.publish("supervisor", {**event, "package": {"summary": pkg["summary"]}})
    return conv.handoff


async def accept(svc: Any, conv: Conversation, agent_id: str, agent_name: str | None = None) -> dict[str, Any]:
    workers = svc.ext.setdefault("workers", [])
    w = next((x for x in workers if x["id"] == agent_id), None)
    name = agent_name or (w["name"] if w else agent_id)
    conv.handler, conv.status, conv.assigned_agent = "human", "with_human", agent_id
    if conv.handoff:
        conv.handoff["state"] = "accepted"
        conv.handoff["accepted_at"] = now()
        conv.handoff["accepted_by"] = agent_id
        conv.handoff["wait_s"] = round(now() - conv.handoff["created_at"], 1)
    if w and conv.id not in w["active"]:
        w["active"].append(conv.id)
        w["last_assigned_at"] = now()
    lang = conv.language
    notice = {"en": f"{name} has joined the conversation and can see everything we discussed.", "de": f"{name} ist jetzt im Gespräch und sieht alles, was wir besprochen haben."}.get(lang, f"{name} has joined the conversation and can see everything we discussed.")
    conv.add("system_notice", notice, lang=lang, author=agent_id, flags=["agent_joined"])
    conv.agent_trace.append({"ts": now(), "agent": "human", "event": "accepted", "agent_id": agent_id})
    await svc.audit.log("handoff.accepted", actor=f"human:{agent_id}", resource=conv.id, conv_id=conv.id, detail={"wait_s": conv.handoff.get("wait_s") if conv.handoff else None})
    return conv.handoff or {}


def release_worker(svc: Any, conv: Conversation) -> None:
    for w in svc.ext.get("workers", []):
        if conv.id in w["active"]:
            w["active"].remove(conv.id)
