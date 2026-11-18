"""Read-time localization of persisted machine-written records (spec §11.2): triggers, routing decisions, handoff packages, SLA alerts, QA results.

The stored records keep their stable codes (`trigger.code`, `routing.rule`, `queue`, ...) and the original English text; these helpers render the
human-readable parts in the REQUEST locale (en/pl) from the message catalogs, without touching the stored documents (audit hashes stay valid)."""

from __future__ import annotations

import re
from typing import Any

from ..core import i18n
from ..core.money import format_money, format_number, parse_money
from .routing import QUEUES

_REASON_KEYS = {
    "+15 VIP": "route.reason.vip", "+10 vulnerable": "route.reason.vulnerable", "+10 very negative sentiment": "route.reason.sentiment_very_negative",
    "+5 negative sentiment": "route.reason.sentiment_negative", "+10 critical urgency": "route.reason.urgency_critical", "+5 high urgency": "route.reason.urgency_high",
    "+20 SLA exception policy (waited >= 80 % of SLA)": "route.reason.sla_exception",
}
_TRIGGER_TEXT_KEYS = {
    "Identity verification locked after repeated failures": "trigger.policy_block.locked",
    "Customer declined recording consent; policy routes to a human": "trigger.policy_block.consent",
    "model content filter triggered": "trigger.policy_block.content_filter",
    "approval required": "trigger.policy_block.approval",
    "Agent could not understand the customer twice": "trigger.loop.not_understood",
}
_SENTIMENT_RX = re.compile(r"^Sentiment (-?\d+(?:\.\d+)?) crossed the escalation threshold$")
_TAKEOVER_RX = re.compile(r"^(\w+) took over the AI conversation$")
_ABOVE_CAP_RX = re.compile(r"^(refund|goodwill) of (.+) above cap - approval (\S+)$")


def queue_name(queue_id: str, lang: str | None = None) -> str:
    return i18n.label("queue", queue_id, lang, QUEUES.get(queue_id, {}).get("name", queue_id))


def trigger_reason(code: str, stored: str, lang: str | None = None) -> str:
    """Localized reason of an escalation trigger; free text written by the assistant or a human is returned unchanged."""
    lang = i18n.normalize(lang) or i18n.current_locale()
    if lang == "en":
        return stored
    if (key := _TRIGGER_TEXT_KEYS.get(stored)) and i18n.has(key):
        return i18n.msg(key, lang)
    if m := _SENTIMENT_RX.match(stored):
        return i18n.msg("trigger.sentiment", lang, value=format_number(float(m.group(1)), lang, 2))
    if m := _TAKEOVER_RX.match(stored):
        return i18n.msg("trigger.takeover", lang, by=m.group(1))
    if m := _ABOVE_CAP_RX.match(stored):
        kind = i18n.label("assist.kind", m.group(1), lang, m.group(1))
        amounts = parse_money(m.group(2))
        money = format_money(amounts[0][0], amounts[0][1], lang) if amounts else m.group(2)
        return i18n.msg("trigger.policy_block.above_cap", lang, kind=kind, money=money, id=m.group(3))
    fixed = {"legal_threat", "fraud_suspected", "safety_issue", "welfare_concern", "vulnerable_customer", "explicit_request", "tool_failure", "knowledge_gap", "regulatory_complaint"}
    if code in fixed and stored == i18n.msg(f"trigger.{code}", "en"):
        return i18n.msg(f"trigger.{code}", lang)
    if code == "loop" and stored == i18n.msg("trigger.loop", "en"):
        return i18n.msg("trigger.loop", lang)
    return stored


def localize_trigger(trigger: dict[str, Any] | None, lang: str | None = None) -> dict[str, Any] | None:
    if not trigger:
        return trigger
    return {**trigger, "reason": trigger_reason(trigger.get("code", ""), trigger.get("reason", ""), lang)}


def localize_routing(routing: dict[str, Any] | None, lang: str | None = None) -> dict[str, Any] | None:
    """Queue name and the explanation lines of a routing decision (the rule id, priority and every machine field are unchanged)."""
    if not routing:
        return routing
    lang = i18n.normalize(lang) or i18n.current_locale()
    out = {**routing, "queue_name": queue_name(routing.get("queue", ""), lang)}
    reasons = []
    for r in routing.get("reasons", []):
        if m := re.match(r"^(R\d+): ", r):
            key = f"route.rule.{m.group(1)}"
            reasons.append(f"{m.group(1)}: {i18n.msg(key, lang)}" if i18n.has(key) else r)
        elif r in _REASON_KEYS:
            reasons.append(i18n.msg(_REASON_KEYS[r], lang))
        else:
            reasons.append(r)
    out["reasons"] = reasons
    return out


def localize_package(pkg: dict[str, Any] | None, conv: Any = None, lang: str | None = None) -> dict[str, Any] | None:
    """Handoff package for the console: trigger, routing and - for machine-written (extractive) text - summary and suggested resolution in the request locale."""
    if not pkg:
        return pkg
    lang = i18n.normalize(lang) or i18n.current_locale()
    out = {**pkg, "trigger": localize_trigger(pkg.get("trigger"), lang), "routing": localize_routing(pkg.get("routing"), lang)}
    code = (pkg.get("trigger") or {}).get("code", "")
    if pkg.get("summary_source") == "extractive" and pkg.get("text_lang") != lang and conv is not None:
        from .handoff import _extractive_summary

        out["summary"] = _extractive_summary(conv, lang)
        out["text_lang"] = lang
        key = f"ho.suggested.{code}"
        out["suggested_resolution"] = i18n.msg(key if i18n.has(key) else "ho.suggested.explicit_request", lang)
    return out


def localize_sla_alert(alert: dict[str, Any], lang: str | None = None) -> dict[str, Any]:
    """SLA-risk alert (`reason` is rebuilt from the stored numbers; alerts stored before `params` existed keep their text)."""
    lang = i18n.normalize(lang) or i18n.current_locale()
    p = alert.get("params") or {}
    out = {**alert, "name": queue_name(alert.get("queue", ""), lang)}
    if p:
        out["reason"] = i18n.msg("sla.reason", lang, **p)
    return out


def localize_queue_stats(row: dict[str, Any], lang: str | None = None) -> dict[str, Any]:
    return {**row, "name": queue_name(row.get("queue", ""), lang)}


def heat_label(key: str, lang: str | None = None) -> str:
    """Row label of the sentiment heat map: the AI agent, a queue (by its English name) or the generic human queue."""
    if key == "AI agent":
        return i18n.msg("sup.heat.ai", lang)
    if key == "Human queue":
        return i18n.msg("sup.heat.human_queue", lang)
    queue_id = next((q for q, spec in QUEUES.items() if spec["name"] == key), None)
    return queue_name(queue_id, lang) if queue_id else key


def localize_overview(ov: dict[str, Any], lang: str | None = None) -> dict[str, Any]:
    """Supervisor overview in the request locale: queue names, SLA alert texts and heat-map labels (stable `queue` / `key` fields never change)."""
    lang = i18n.normalize(lang) or i18n.current_locale()
    if lang == "en":
        return ov
    return {
        **ov,
        "queues": [localize_queue_stats(q, lang) for q in ov.get("queues", [])],
        "alerts": [localize_sla_alert(a, lang) for a in ov.get("alerts", [])],
        "alert_history": [localize_sla_alert(a, lang) for a in ov.get("alert_history", [])],
        "heat_map": [{**h, "label": heat_label(h["key"], lang)} for h in ov.get("heat_map", [])],
    }


def money_in(amount: float, currency: str | None, lang: str | None = None) -> str:
    return format_money(amount, currency, i18n.normalize(lang) or i18n.current_locale())


# ------------------------------------------------------------------------------------------------ VoC (CC-12)
def voc_labels(doc: dict[str, Any], lang: str) -> dict[int, str]:
    """Display label of every topic cluster: the Polish label of its dominant contact driver (+ its main carrier); clusters that would share a label get a number."""
    from .synth_pl import TOPIC_LABEL_PL

    out: dict[int, str] = {}
    seen: dict[str, int] = {}
    for c in doc.get("clusters", []):
        base = TOPIC_LABEL_PL.get(c.get("dominant_driver", ""), c.get("label", ""))
        carrier = next(iter(c.get("carriers") or {}), None)
        label = f"{base} · {carrier}" if carrier else base
        seen[label] = seen.get(label, 0) + 1
        out[c["id"]] = label if seen[label] == 1 else f"{label} ({seen[label]})"
    return out


def _voc_alert_message(a: dict[str, Any], label: str, lang: str) -> str:
    fmt = lambda v: format_number(float(v), lang, 1)  # noqa: E731
    params = {"label": label, "recent": fmt(a["recent_per_day"]), "base": fmt(a["baseline_per_day"]), "ratio": fmt(a["ratio"])}
    n_related = len(a.get("clusters") or [a["cluster"]]) - 1
    text = i18n.msg("voc.alert.merged" if n_related > 0 else "voc.alert", lang, n=n_related, **params)
    carrier = a.get("carrier")
    if carrier:
        return text + i18n.msg("voc.alert.carrier", lang, name=carrier["name"], share=round(100 * carrier["share_recent"]), base_share=round(100 * carrier["share_baseline"]))
    return text + "."


def localize_voc(doc: dict[str, Any], lang: str | None = None) -> dict[str, Any]:
    """Stored VoC aggregates in the request locale: topic labels, alert messages and the Polish summaries of the example / evidence records.
    Stable ids, numbers and the stored English texts are untouched (English requests get the document as stored)."""
    lang = i18n.normalize(lang) or i18n.current_locale()
    if lang == "en":
        return doc
    labels = voc_labels(doc, lang)
    out = dict(doc)
    out["clusters"] = [
        {**c, "label_en": c.get("label"), "label": labels.get(c["id"], c.get("label")), "examples": [{**e, "summary": e.get("summary_pl") or e["summary"]} for e in c.get("examples", [])]}
        for c in doc.get("clusters", [])
    ]
    for key in ("pareto_volume", "pareto_cost"):
        out[key] = [{**row, "label": labels.get(row["id"], row.get("label"))} for row in doc.get(key, [])]
    alerts = []
    for a in doc.get("alerts", []):
        label = labels.get(a["cluster"], a.get("label"))
        alerts.append({**a, "label": label, "message": _voc_alert_message(a, label, lang), "evidence_summaries": a.get("evidence_summaries_pl") or a.get("evidence_summaries", [])})
    out["alerts"] = alerts
    return out


def localize_history_rows(rows: list[dict[str, Any]], lang: str | None = None) -> list[dict[str, Any]]:
    """History records for the Polish UI: the machine-written `summary` becomes `summary_pl` (the English text stays available as `summary_en`)."""
    lang = i18n.normalize(lang) or i18n.current_locale()
    if lang == "en":
        return rows
    return [{**r, "summary_en": r.get("summary"), "summary": r.get("summary_pl") or r.get("summary")} for r in rows]
