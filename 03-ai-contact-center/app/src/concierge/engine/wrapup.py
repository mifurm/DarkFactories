"""Auto wrap-up (CC-09): summary, disposition code, CRM note, follow-up tasks, QA flags; idempotent per conversation."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from ..core.redaction import redact_text
from .models import Conversation, now

DISPOSITIONS: dict[str, str] = {
    "RESOLVED_REFUND_ISSUED": "Resolved - refund issued",
    "RESOLVED_REPLACEMENT_ARRANGED": "Resolved - replacement arranged",
    "RESOLVED_DELIVERY_RESCHEDULED": "Resolved - delivery rescheduled",
    "RESOLVED_ADDRESS_UPDATED": "Resolved - address updated",
    "RESOLVED_WARRANTY_OPENED": "Resolved - warranty claim opened",
    "RESOLVED_GOODWILL_CREDIT": "Resolved - goodwill credit granted",
    "RESOLVED_INFO_PROVIDED": "Resolved - information provided",
    "RESOLVED_ORDER_STATUS": "Resolved - order status provided",
    "TICKET_CREATED": "Follow-up ticket created",
    "ESCALATED_LEGAL": "Escalated - legal / consumer-authority threat",
    "ESCALATED_VULNERABLE": "Escalated - vulnerable customer",
    "ESCALATED_FRAUD": "Escalated - suspected fraud",
    "ESCALATED_SAFETY": "Escalated - product safety",
    "ESCALATED_APPROVAL": "Escalated - approval required",
    "ESCALATED_CUSTOMER_REQUEST": "Escalated - customer asked for a human",
    "ESCALATED_OTHER": "Escalated - other",
    "VERIFICATION_FAILED": "Identity verification failed",
    "NO_RESOLUTION_ABANDONED": "No resolution - customer left",
    "OUT_OF_SCOPE": "Out of scope",
}
ESC_MAP = {"legal_threat": "ESCALATED_LEGAL", "vulnerable_customer": "ESCALATED_VULNERABLE", "fraud_suspected": "ESCALATED_FRAUD", "safety_issue": "ESCALATED_SAFETY", "explicit_request": "ESCALATED_CUSTOMER_REQUEST", "policy_block": "ESCALATED_APPROVAL"}
BASELINE_ACW_S = 300.0  # assumption: manual after-call work per contact (editable in assumptions / CC-13)


def classify_disposition(conv: Conversation) -> str:
    ok = [s["tool"] for s in conv.steps if s["status"] == "ok"]
    trig = (conv.handoff or {}).get("trigger", {}).get("code")
    if conv.identity.locked:
        return "VERIFICATION_FAILED"
    if conv.handoff and trig and trig != "takeover" and conv.handler != "ai":
        # a human finished the conversation: still record why it was escalated
        return ESC_MAP.get(trig, "ESCALATED_OTHER")
    if "issue_refund" in ok:
        return "RESOLVED_REFUND_ISSUED"
    if "initiate_return" in ok and any(s["tool"] == "initiate_return" and "replacement" in s["summary"] for s in conv.steps):
        return "RESOLVED_REPLACEMENT_ARRANGED"
    if "initiate_return" in ok:
        return "RESOLVED_REFUND_ISSUED" if "issue_refund" in ok else "RESOLVED_REPLACEMENT_ARRANGED"
    if "reschedule_delivery" in ok:
        return "RESOLVED_DELIVERY_RESCHEDULED"
    if "update_address" in ok:
        return "RESOLVED_ADDRESS_UPDATED"
    if "warranty_claim" in ok:
        return "RESOLVED_WARRANTY_OPENED"
    if "goodwill_credit" in ok:
        return "RESOLVED_GOODWILL_CREDIT"
    if "create_ticket" in ok:
        return "TICKET_CREATED"
    if conv.handoff:
        return ESC_MAP.get(trig or "", "ESCALATED_OTHER")
    if "track_shipment" in ok or "lookup_order" in ok:
        return "RESOLVED_ORDER_STATUS"
    if conv.kb_used or (conv.understanding and conv.understanding.intent in ("policy_question", "product_info", "installation_info")):
        return "RESOLVED_INFO_PROVIDED"
    if conv.status == "abandoned" or not any(m.role == "customer" for m in conv.messages[1:]):
        return "NO_RESOLUTION_ABANDONED"
    return "OUT_OF_SCOPE" if not ok else "RESOLVED_INFO_PROVIDED"


def _facts(conv: Conversation) -> dict[str, Any]:
    amounts: list[float] = []
    for m in conv.messages:
        for t in m.tools:
            if t.status == "ok":
                for key in ("amount_eur", "refundable_amount_eur"):
                    if isinstance(t.result.get(key), int | float):
                        amounts.append(float(t.result[key]))
    refunds = [t for m in conv.messages for t in m.tools if t.name == "issue_refund" and t.status == "ok"]
    return {"amounts": amounts, "refunds": refunds}


def extractive_summary(conv: Conversation, disposition: str) -> str:
    u = conv.understanding
    intent = (u.intent if u else "other").replace("_", " ")
    who = conv.customer_label or "Customer"
    steps = [s for s in conv.steps if s["status"] == "ok" and s["tool"] in ("initiate_return", "schedule_pickup", "issue_refund", "reschedule_delivery", "update_address", "goodwill_credit", "warranty_claim", "create_ticket")]
    facts = _facts(conv)
    parts = [f"{who} contacted us via {conv.channel.replace('_', ' ')} ({conv.language.upper()}) about {intent}"]
    if conv.entities.get("order_id"):
        parts[0] += f" (order {conv.entities['order_id']})"
    parts[0] += "."
    if steps:
        parts.append("Actions taken: " + "; ".join(s["summary"] for s in steps[:4]) + ".")
    if facts["refunds"]:
        r = facts["refunds"][-1].result
        parts.append(f"Refund of EUR {r.get('amount_eur', 0):.2f} issued ({r.get('eta', '')}).")
    elif facts["amounts"]:
        parts.append(f"Amounts discussed: EUR {max(facts['amounts']):.2f}.")
    if conv.handoff:
        t = conv.handoff["trigger"]
        parts.append(f"Escalated to a human colleague ({t.get('code')}: {t.get('reason')}).")
    parts.append(f"Outcome: {DISPOSITIONS[disposition]}.")
    nxt = follow_ups(conv, disposition)
    if nxt:
        parts.append("Next steps: " + "; ".join(n["title"] for n in nxt[:3]) + ".")
    return " ".join(parts)


def follow_ups(conv: Conversation, disposition: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    ok = {s["tool"] for s in conv.steps if s["status"] == "ok"}
    if "schedule_pickup" in ok:
        tasks.append({"title": "Confirm pickup was completed and item scanned at warehouse", "due_days": 3, "owner": "logistics"})
    if "issue_refund" in ok:
        tasks.append({"title": "Verify refund is released after pickup scan (5-7 business days)", "due_days": 8, "owner": "finance"})
    if conv.handoff and conv.handler != "ai" and disposition.startswith("ESCALATED"):
        tasks.append({"title": f"Complete follow-up promised to customer ({disposition})", "due_days": 2, "owner": "agent"})
    if disposition == "ESCALATED_LEGAL":
        tasks.append({"title": "Notify complaints/legal desk and log complaint reference", "due_days": 1, "owner": "legal"})
    if "warranty_claim" in ok:
        tasks.append({"title": "Specialist to contact customer about warranty claim", "due_days": 10, "owner": "warranty"})
    if disposition == "TICKET_CREATED":
        tasks.append({"title": "Work the open support ticket", "due_days": 2, "owner": "support"})
    return tasks


def qa_flags(conv: Conversation) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    for m in conv.messages:
        for f in m.flags:
            if f == "ungrounded":
                flags.append({"flag": "possible_ungrounded_answer", "evidence": f"turn {m.idx}"})
            if f.startswith("risky_promise"):
                flags.append({"flag": "risky_promise_blocked", "evidence": f"turn {m.idx}: {f}"})
            if f.startswith("pii_in_output"):
                flags.append({"flag": "pii_in_output_redacted", "evidence": f"turn {m.idx}"})
    if not any("disclosure" in m.flags for m in conv.messages):
        flags.append({"flag": "missing_ai_disclosure", "evidence": "no disclosure message in transcript"})
    if conv.consent.recording == "pending" and conv.channel == "voice":
        flags.append({"flag": "recording_consent_missing", "evidence": "voice call without consent decision"})
    if conv.pending:
        flags.append({"flag": "unresolved_promise", "evidence": "pending confirmation never completed: " + "; ".join(p.summary[:80] for p in conv.pending)})
    return flags


async def generate_wrapup(svc: Any, conv: Conversation, *, force: bool = False) -> dict[str, Any]:
    t0 = time.perf_counter()
    disposition = classify_disposition(conv)
    summary = extractive_summary(conv, disposition)
    source = "extractive"
    if not svc.llm.deterministic:
        try:
            convo = "\n".join(f"{m.role}: {m.text}" for m in conv.messages if m.visible_to_customer)[-3800:]
            acts = "; ".join(s["summary"] for s in conv.steps if s["status"] == "ok")[:600]
            res = await svc.llm.chat(
                [{"role": "system", "content": "Summarise a customer-service conversation for the CRM in 3-4 factual sentences: intent, what was done (with amounts and dates), outcome and next steps. English. No PII beyond first name. Return JSON {\"summary\": str}."},
                 {"role": "user", "content": f"Disposition: {DISPOSITIONS[disposition]}\nActions: {acts}\nConversation:\n{convo}"}],
                role="nano", max_tokens=380, reasoning_effort="minimal", json_mode=True, feature="wrapup", conv_id=conv.id,
            )  # fmt: skip
            data = json.loads(res.text or "{}")
            if data.get("summary") and len(data["summary"]) > 40:
                summary, source = redact_text(str(data["summary"]))[:900], "llm"
                # the required facts must survive: append deterministic outcome line if the model omitted it
                if DISPOSITIONS[disposition].split(" - ")[-1].lower() not in summary.lower():
                    summary += f" Outcome: {DISPOSITIONS[disposition]}."
        except Exception:
            source = "extractive"
    tasks = follow_ups(conv, disposition)
    flags = qa_flags(conv)
    note = f"[Concierge auto wrap-up {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC] {summary} Disposition: {disposition}."
    acw_auto = round(time.perf_counter() - t0 + (1.5 if source == "llm" else 0.2), 2)
    wrap = {
        "conversation_id": conv.id, "generated_at": now(), "summary": summary, "summary_source": source, "disposition": disposition, "disposition_label": DISPOSITIONS[disposition],
        "crm_note": note, "follow_up_tasks": tasks, "qa_flags": flags, "intent": conv.understanding.intent if conv.understanding else "other",
        "acw_seconds_auto": acw_auto, "acw_seconds_baseline": BASELINE_ACW_S, "acw_reduction_pct": round(100 * (1 - acw_auto / BASELINE_ACW_S), 1),
        "edited_by": None, "edit_ratio": None, "submitted": conv.handler == "ai",
    }  # fmt: skip
    crm = svc.ext.get("crm")
    if crm is not None and conv.identity.customer_id:
        await crm.write_note(conv.identity.customer_id, wrap["crm_note"], conv.id)
        for i, t in enumerate(tasks):
            await crm.write_task(conv.identity.customer_id, t["title"], t["owner"], t["due_days"], conv.id, i)
    return wrap


def edit_ratio(a: str, b: str) -> float:
    ta, tb = re.findall(r"\w+", a.lower()), re.findall(r"\w+", b.lower())
    if not ta and not tb:
        return 0.0
    common = len(set(ta) & set(tb))
    return round(1 - common / max(len(set(ta) | set(tb)), 1), 3)
