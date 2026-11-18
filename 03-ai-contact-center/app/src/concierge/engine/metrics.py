"""CX metrics (CC-13) computed from stored interaction records: the synthetic baseline history (`history`) plus live conversations of this deployment.
Containment, verified resolution, AHT, FCR, predicted CSAT, cost per contact and per *resolved* contact (human minutes x cost per minute + metered Azure
cost for the AI part), deflection, SLA and abandon - with AI-vs-human comparison, per-queue and per-interval roll-ups and reconciliation checks."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from .routing import DELIVERY_INTENTS, QUEUES, RETURN_INTENTS
from .voc import HUMAN_COST_PER_MIN_USD


def queue_for_intent(intent: str | None) -> str:
    if intent in RETURN_INTENTS:
        return "returns"
    if intent in DELIVERY_INTENTS:
        return "delivery"
    return {"warranty_claim": "warranty", "billing_question": "billing", "complaint": "escalations"}.get(intent or "", "general")


def live_record(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Maps a stored conversation document onto the history record shape (ended conversations only)."""
    if doc.get("status") not in ("resolved", "closed") or doc.get("eval_run_id") or doc.get("sim"):
        return None
    created, closed = doc.get("created_at", 0.0), doc.get("closed_at") or doc.get("updated_at") or doc.get("created_at", 0.0)
    h = doc.get("handoff") or {}
    escalated = bool(h)
    handled_human = escalated and bool(h.get("accepted_at"))
    intent = (doc.get("understanding") or {}).get("intent") or "other"
    sent = (doc.get("sentiment_trajectory") or [0.0])[-1]
    dispo = (doc.get("wrapup") or {}).get("disposition") or ""
    resolved = doc.get("status") == "resolved" or dispo.startswith("RESOLVED")
    if handled_human:
        aht = max(5.0, closed - h["accepted_at"])
        wait = max(0.0, h["accepted_at"] - h["created_at"])
    else:
        aht = max(5.0, closed - created)
        wait = 0.0
    abandoned = escalated and not h.get("accepted_at") and doc.get("status") == "closed"
    ts = created
    dt = datetime.fromtimestamp(ts, UTC)
    return {
        "id": doc["id"], "ts": ts, "date": dt.strftime("%Y-%m-%d"), "hour": dt.hour, "queue": doc.get("queue") or queue_for_intent(intent), "intent": intent, "channel": doc.get("channel", "web_chat"),
        "customer_id": (doc.get("identity") or {}).get("customer_id") or doc["id"], "handled_by": "human" if handled_human else "ai", "contained": not escalated, "escalated": escalated, "resolved": bool(resolved) and not abandoned,
        "abandoned": abandoned, "wait_s": wait, "aht_s": aht if not abandoned else 0.0, "acw_s": float((doc.get("wrapup") or {}).get("acw_seconds_auto", 30.0)) if handled_human else 0.0,
        "sentiment_end": sent, "csat_pred": max(1.0, min(5.0, 3.1 + 1.9 * sent)), "ai_cost_usd": float((doc.get("usage") or {}).get("cost_usd", 0.0)), "source": "live",
    }  # fmt: skip


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 2) if xs else None


def fcr_flags(rs: list[dict[str, Any]]) -> dict[str, bool]:
    """First-contact resolution: True when the same customer did NOT contact again about the same intent within 7 days."""
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in sorted(rs, key=lambda r: r["ts"]):
        by_key[(r["customer_id"], r["intent"])].append(r)
    out: dict[str, bool] = {}
    for rows in by_key.values():
        for i, r in enumerate(rows):
            out[r["id"]] = not (i + 1 < len(rows) and rows[i + 1]["ts"] - r["ts"] <= 7 * 86400)
    return out


def human_minutes(r: dict[str, Any]) -> float:
    return (r["aht_s"] + r["acw_s"]) / 60.0 if r["handled_by"] == "human" else 0.0


def cost_of(r: dict[str, Any], cost_per_min: float) -> float:
    return human_minutes(r) * cost_per_min + r.get("ai_cost_usd", 0.0)


def kpis(rs: list[dict[str, Any]], *, cost_per_min: float = HUMAN_COST_PER_MIN_USD, fcr: dict[str, bool] | None = None) -> dict[str, Any]:
    n = len(rs)
    if n == 0:
        return {"contacts": 0}
    contained = [r for r in rs if r["contained"]]
    ai_resolved = [r for r in contained if r["resolved"]]
    human = [r for r in rs if r["handled_by"] == "human" and not r["abandoned"]]
    queued = [r for r in rs if r["escalated"]]
    resolved = [r for r in rs if r["resolved"]]
    total_cost = sum(cost_of(r, cost_per_min) for r in rs)
    ai_cost = sum(r.get("ai_cost_usd", 0.0) for r in rs)
    sla_ok = [r for r in human if r["wait_s"] <= QUEUES.get(r["queue"], {}).get("sla_s", 120)]
    fl = fcr if fcr is not None else fcr_flags(rs)
    return {
        "contacts": n, "contained": len(contained), "containment_pct": round(100 * len(contained) / n, 1), "ai_verified_resolved": len(ai_resolved), "verified_resolution_pct": round(100 * len(ai_resolved) / n, 1),
        "resolved_pct": round(100 * len(resolved) / n, 1), "deflection_pct": round(100 * len(ai_resolved) / n, 1), "escalated_pct": round(100 * len(queued) / n, 1),
        "aht_human_s": _mean([r["aht_s"] + r["acw_s"] for r in human]), "aht_ai_s": _mean([r["aht_s"] for r in contained if r["aht_s"] > 0]),
        "aht_blended_s": _mean([r["aht_s"] + r["acw_s"] for r in rs if r["aht_s"] > 0]), "fcr_pct": round(100 * sum(1 for r in rs if fl.get(r["id"], True)) / n, 1),
        "csat_pred": _mean([r["csat_pred"] for r in rs]), "sentiment_end": _mean([r["sentiment_end"] for r in rs]), "sla_pct": round(100 * len(sla_ok) / len(human), 1) if human else None,
        "abandon_pct": round(100 * sum(1 for r in queued if r["abandoned"]) / len(queued), 1) if queued else 0.0,
        "cost_total_usd": round(total_cost, 2), "cost_ai_usd": round(ai_cost, 2), "cost_human_usd": round(total_cost - ai_cost, 2),
        "cost_per_contact_usd": round(total_cost / n, 3), "cost_per_resolved_usd": round(total_cost / len(resolved), 3) if resolved else None, "human_minutes": round(sum(human_minutes(r) for r in rs), 1),
    }  # fmt: skip


def ai_vs_human(rs: list[dict[str, Any]], cost_per_min: float = HUMAN_COST_PER_MIN_USD) -> dict[str, Any]:
    """Contained-by-AI contacts vs contacts a human had to handle (the human side includes the AI attempt that preceded the handoff)."""
    fl = fcr_flags(rs)
    ai = [r for r in rs if r["contained"]]
    hu = [r for r in rs if not r["contained"]]
    out = {}
    for label, grp in (("ai", ai), ("human", hu)):
        k = kpis(grp, cost_per_min=cost_per_min, fcr=fl)
        out[label] = {key: k.get(key) for key in ("contacts", "resolved_pct", "aht_blended_s", "csat_pred", "fcr_pct", "cost_per_contact_usd", "cost_per_resolved_usd", "cost_total_usd", "cost_ai_usd", "cost_human_usd")}
    a, h = out["ai"].get("cost_per_resolved_usd"), out["human"].get("cost_per_resolved_usd")
    out["cost_per_resolved_ratio"] = round(h / a, 1) if a and h else None
    return out


def rollup(rs: list[dict[str, Any]], key: Any, cost_per_min: float = HUMAN_COST_PER_MIN_USD) -> dict[Any, dict[str, Any]]:
    fl = fcr_flags(rs)
    groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for r in rs:
        groups[key(r)].append(r)
    return {k: kpis(v, cost_per_min=cost_per_min, fcr=fl) for k, v in sorted(groups.items(), key=lambda kv: str(kv[0]))}


def reconcile(rs: list[dict[str, Any]], overall: dict[str, Any], by_queue: dict[str, Any], by_hour: dict[int, Any], by_day: dict[str, Any]) -> list[dict[str, Any]]:
    """Asserts that the views agree with each other (shown in the UI and covered by the unit tests)."""

    def check(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
        return {"name": name, "ok": bool(ok), "detail": detail}

    n = overall.get("contacts", 0)
    cost = overall.get("cost_total_usd", 0.0)
    return [
        check("contacts: sum over queues = total", sum(v["contacts"] for v in by_queue.values()) == n, f"{sum(v['contacts'] for v in by_queue.values())} vs {n}"),
        check("contacts: sum over hours = total", sum(v["contacts"] for v in by_hour.values()) == n),
        check("contacts: sum over days = total", sum(v["contacts"] for v in by_day.values()) == n),
        check("containment >= verified resolution", n == 0 or overall["contained"] >= overall["ai_verified_resolved"], f"{overall.get('contained')} >= {overall.get('ai_verified_resolved')}"),
        check("deflection never exceeds containment", n == 0 or overall["deflection_pct"] <= overall["containment_pct"] + 1e-9),
        check("cost: AI + human = total", abs(overall.get("cost_ai_usd", 0) + overall.get("cost_human_usd", 0) - cost) < 0.011, f"{overall.get('cost_ai_usd')} + {overall.get('cost_human_usd')} = {cost}"),
        check("cost: sum over queues = total", abs(sum(v["cost_total_usd"] for v in by_queue.values()) - cost) < 0.05),
        check("cost per resolved >= cost per contact", n == 0 or overall["cost_per_resolved_usd"] is None or overall["cost_per_resolved_usd"] >= overall["cost_per_contact_usd"] - 1e-9),
    ]  # fmt: skip
