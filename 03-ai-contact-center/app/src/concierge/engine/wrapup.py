"""Auto wrap-up (CC-09): summary, disposition code, CRM note, follow-up tasks, QA flags; idempotent per conversation.

Language: the stored summary / CRM note are written in the conversation's operator language (Polish for Polish conversations, English otherwise) and
carry `lang`; codes (`disposition`, task `code`, flag `evidence_code`) are stable and their labels are re-rendered at read time in the request locale
(`localize_wrapup`)."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from ..core import i18n
from ..core.money import format_money, pick
from ..core.redaction import redact_text
from . import plain_text, plan_text
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


def doc_lang(conv: Conversation) -> str:
    """Language of the generated operator-facing text: Polish for Polish conversations, English otherwise."""
    return "pl" if conv.language == "pl" else "en"


def disposition_label(code: str, lang: str | None = None) -> str:
    return i18n.label("disposition", code, lang, DISPOSITIONS.get(code))


def _facts(conv: Conversation) -> dict[str, Any]:
    amounts: list[tuple[float, str]] = []
    for m in conv.messages:
        for t in m.tools:
            if t.status == "ok":
                cur = t.result.get("currency") or "EUR"
                for key in ("amount", "refundable_amount"):
                    v = pick(t.result, key)
                    if v is not None:
                        amounts.append((v, cur))
    refunds = [t for m in conv.messages for t in m.tools if t.name == "issue_refund" and t.status == "ok"]
    return {"amounts": amounts, "refunds": refunds}


def _intent_label(intent: str, lang: str) -> str:
    return i18n.label("intent", intent, lang, intent.replace("_", " "))


STEP_TEXT_PL = {"create_ticket": "utworzono zgłoszenie do dalszej obsługi"}  # steps that carry no plan sentence (their stored summary is the English tool name)


def step_text(step: dict[str, Any], lang: str) -> str:
    """One executed step for a summary list: the plan sentence as a record of what was done (Polish: `zlecono zwrot ...`), English unchanged."""
    if lang == "pl" and step["tool"] in STEP_TEXT_PL and step["summary"] == step["tool"].replace("_", " "):
        return STEP_TEXT_PL[step["tool"]]
    return plan_text.done_text(lang, step["summary"])


def lower_first(title: str, lang: str) -> str:
    """A task title inside a running sentence (`Następne kroki: potwierdzić ...`): Polish continues in lower case, except an acronym or a name."""
    return title[:1].lower() + title[1:] if lang == "pl" and title[1:2].islower() else title


def primary_intent(conv: Conversation) -> str:
    """The contact reason: the first substantive intent of the conversation (a closing 'thanks, bye' must not become the topic of the summary)."""
    for intent in conv.intent_trail:
        if intent not in ("greeting", "goodbye", "other"):
            return intent
    return conv.understanding.intent if conv.understanding else "other"


def extractive_summary(conv: Conversation, disposition: str, lang: str | None = None) -> str:
    lang = lang or doc_lang(conv)
    intent = _intent_label(primary_intent(conv), lang)
    who = conv.customer_label or i18n.msg("wrap.customer", lang)
    steps = [s for s in conv.steps if s["status"] == "ok" and s["tool"] in ("initiate_return", "schedule_pickup", "issue_refund", "reschedule_delivery", "update_address", "goodwill_credit", "warranty_claim", "create_ticket")]
    facts = _facts(conv)
    channel = i18n.label("channel", conv.channel, lang, conv.channel.replace("_", " "))
    parts = [i18n.msg("wrap.contact", lang, who=who, channel=channel, lang=conv.language.upper(), intent=intent)]
    if conv.entities.get("order_id"):
        parts[0] += i18n.msg("wrap.contact_order", lang, order=conv.entities["order_id"])
    parts[0] += "."
    if steps:
        parts.append(i18n.msg("wrap.actions", lang, actions="; ".join(step_text(s, lang) for s in steps[:4])))
    if facts["refunds"]:
        r = facts["refunds"][-1].result
        parts.append(i18n.msg("wrap.refund_issued", lang, money=format_money(pick(r, "amount") or 0, r.get("currency"), lang), eta=plan_text.eta_text(lang, r.get("eta", ""))))
    elif facts["amounts"]:
        value, cur = max(facts["amounts"])
        parts.append(i18n.msg("wrap.amounts", lang, money=format_money(value, cur, lang)))
    if conv.handoff:
        t = conv.handoff["trigger"]
        reason = i18n.msg(f"trigger.{t.get('code')}", lang) if i18n.has(f"trigger.{t.get('code')}") and lang != "en" else t.get("reason")
        parts.append(i18n.msg("wrap.escalated", lang, code=t.get("code"), reason=reason))
    parts.append(i18n.msg("wrap.outcome", lang, label=disposition_label(disposition, lang)))
    nxt = follow_ups(conv, disposition, lang)
    if nxt:
        parts.append(i18n.msg("wrap.next", lang, steps="; ".join(lower_first(n["title"], lang) for n in nxt[:3])))
    return " ".join(parts)


def follow_ups(conv: Conversation, disposition: str, lang: str | None = None) -> list[dict[str, Any]]:
    lang = lang or doc_lang(conv)
    tasks: list[dict[str, Any]] = []
    ok = {s["tool"] for s in conv.steps if s["status"] == "ok"}

    def task(code: str, due: int, owner: str, **params: Any) -> None:
        tasks.append({"code": code, "title": i18n.msg(f"task.{code}", lang, **params), "due_days": due, "owner": owner, **({"params": params} if params else {})})

    if "schedule_pickup" in ok:
        task("confirm_pickup", 3, "logistics")
    if "issue_refund" in ok:
        task("verify_refund", 8, "finance")
    if conv.handoff and conv.handler != "ai" and disposition.startswith("ESCALATED"):
        task("follow_up", 2, "agent", disposition=disposition)
    if disposition == "ESCALATED_LEGAL":
        task("legal", 1, "legal")
    if "warranty_claim" in ok:
        task("warranty", 10, "warranty")
    if disposition == "TICKET_CREATED":
        task("ticket", 2, "support")
    return tasks


def qa_flags(conv: Conversation, lang: str | None = None) -> list[dict[str, Any]]:
    lang = lang or doc_lang(conv)
    flags: list[dict[str, Any]] = []

    def flag(code: str, ev_code: str, **params: Any) -> None:
        flags.append({"flag": code, "evidence": i18n.msg(f"qaev.{ev_code}", lang, **params), "evidence_code": ev_code, "params": params, "label": i18n.msg(f"qaflag.{code}", lang)})

    for m in conv.messages:
        for f in m.flags:
            if f == "ungrounded":
                flag("possible_ungrounded_answer", "turn", idx=m.idx)
            if f.startswith("risky_promise"):
                flag("risky_promise_blocked", "turn_flag", idx=m.idx, flag=f)
            if f.startswith("pii_in_output"):
                flag("pii_in_output_redacted", "turn", idx=m.idx)
    if not any("disclosure" in m.flags for m in conv.messages):
        flag("missing_ai_disclosure", "no_disclosure")
    if conv.consent.recording == "pending" and conv.channel == "voice":
        flag("recording_consent_missing", "voice_no_consent")
    if conv.pending:
        flag("unresolved_promise", "pending", plans="; ".join(p.summary[:80] for p in conv.pending))
    return flags


def localize_wrapup(wrap: dict[str, Any], conv: Conversation | None, lang: str | None = None) -> dict[str, Any]:
    """Render the stable codes of a stored wrap-up in the request locale (labels, task titles, QA-flag evidence); a machine-written (extractive)
    summary that nobody edited is re-rendered too. Free text written by the LLM or by a human keeps its own language (`lang`)."""
    lang = i18n.normalize(lang) or i18n.current_locale()
    out = {**wrap}
    code = out.get("disposition")
    if code:
        out["disposition_label"] = disposition_label(code, lang)
    out["follow_up_tasks"] = [{**t, "title": i18n.msg(f"task.{t['code']}", lang, **t.get("params", {})) if t.get("code") and i18n.has(f"task.{t['code']}") else t.get("title")} for t in wrap.get("follow_up_tasks", [])]
    out["qa_flags"] = [{**f, "label": i18n.msg(f"qaflag.{f['flag']}", lang) if i18n.has(f"qaflag.{f['flag']}") else f["flag"], **({"evidence": i18n.msg(f"qaev.{f['evidence_code']}", lang, **f.get("params", {}))} if f.get("evidence_code") and i18n.has(f"qaev.{f['evidence_code']}") else {})} for f in wrap.get("qa_flags", [])]
    if conv is not None and code and wrap.get("summary_source") == "extractive" and not wrap.get("edited_by") and wrap.get("lang") != lang:
        out["summary"] = extractive_summary(conv, code, lang)
        out["lang"] = lang
    return out


async def generate_wrapup(svc: Any, conv: Conversation, *, force: bool = False) -> dict[str, Any]:
    t0 = time.perf_counter()
    lang = doc_lang(conv)
    disposition = classify_disposition(conv)
    summary = extractive_summary(conv, disposition, lang)
    source = "extractive"
    if not svc.llm.deterministic:
        try:
            convo = "\n".join(f"{plain_text.role_label(m.role, lang)}: {m.text}" for m in conv.messages if m.visible_to_customer)[-3800:]
            acts = "; ".join(step_text(s, lang) for s in conv.steps if s["status"] == "ok")[:600]
            language = "Polish. Write the whole summary in Polish (third person, no English words or labels such as 'Outcome' or 'Next steps', and never internal codes or identifiers such as legal_threat, initiate_return or RESOLVED_REFUND_ISSUED)" if lang == "pl" else "English"
            res = await svc.llm.chat(
                [{"role": "system", "content": f"Summarise a customer-service conversation for the CRM in 3-4 factual sentences: intent, what was done (with amounts, currency and dates exactly as in the conversation), outcome and next steps. {language}. No PII beyond first name. Return JSON {{\"summary\": str}}."},
                 {"role": "user", "content": f"Disposition: {disposition_label(disposition, lang)}\nActions: {acts}\nConversation:\n{convo}"}],
                role="nano", max_tokens=380, reasoning_effort="minimal", json_mode=True, feature="wrapup", conv_id=conv.id,
            )  # fmt: skip
            data = json.loads(res.text or "{}")
            if data.get("summary") and len(data["summary"]) > 40:
                summary, source = plain_text.plain(redact_text(str(data["summary"]))[:900], lang), "llm"
                # the required facts must survive: append deterministic outcome line if the model omitted it
                if re.split(r"\s[-–]\s", disposition_label(disposition, lang))[-1].lower() not in summary.lower():
                    summary += " " + i18n.msg("wrap.outcome", lang, label=disposition_label(disposition, lang))
        except Exception:
            source = "extractive"
    tasks = follow_ups(conv, disposition, lang)
    flags = qa_flags(conv, lang)
    note = f"[{i18n.msg('wrap.note_head', lang, stamp=time.strftime('%Y-%m-%d %H:%M', time.gmtime()))}] {summary} {i18n.msg('wrap.note_disposition', lang, code=disposition)}"
    acw_auto = round(time.perf_counter() - t0 + (1.5 if source == "llm" else 0.2), 2)
    wrap = {
        "conversation_id": conv.id, "generated_at": now(), "summary": summary, "summary_source": source, "lang": lang, "disposition": disposition, "disposition_label": disposition_label(disposition, lang),
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
