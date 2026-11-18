"""Deterministic synthetic history for analytics (VoC, QA dashboards, CX metrics, WFM). Everything here is SYNTHETIC and seeded:

* `generate_history`  - >= 1,500 interaction records over 90 days x 8 markets with QA scores, sentiment, topics, dispositions and a
  planted emerging issue ("damaged on delivery" for carrier NordFreight in the last 8 days) that the anomaly detector must find.
  Records are a 1:SAMPLE_FACTOR sample of the demo tenant's traffic (about 1,800 contacts/day).
* `generate_wfm_history` - 30-minute interval volumes per queue (full volume) with weekly/daily seasonality, trend, promotions.

No wall-clock or global randomness is used: the same seed always yields the same data.
"""

from __future__ import annotations

import json
import math
import random
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import qa as qa_engine
from . import synth_pl
from .backoffice import CARRIERS, MARKETS

SEED = 20260901
SAMPLE_FACTOR = 90  # history holds 1 in 90 interactions of the demo tenant (about 1,800 contacts/day)
DAYS = 90
SPIKE_DAYS = 8
SPIKE_CARRIER = "NordFreight"
AI_AGENT = "concierge-ai"
HUMAN_AGENTS = [f"AG-{i:02d}" for i in range(1, 13)]
MARKET_WEIGHTS = {"DE": 0.24, "UK": 0.20, "FR": 0.15, "ES": 0.11, "IT": 0.10, "NL": 0.08, "PL": 0.07, "PT": 0.05}
CHANNELS = [("voice", 0.52), ("chat", 0.38), ("messaging", 0.10)]
DOW_FACTOR = [1.15, 1.05, 1.0, 1.0, 1.05, 0.85, 0.55]  # Monday .. Sunday

# topic -> label, engine intent, routing queue, share, AI containment probability, human AHT / AI AHT (s), mean opening sentiment
TOPICS: dict[str, dict[str, Any]] = {
    "order_status": {"label": "Where is my order?", "intent": "order_status", "queue": "delivery", "w": 0.22, "ai": 0.84, "aht_h": 330, "aht_ai": 120, "sent": -0.12, "carrier": True},
    "delivery_reschedule": {"label": "Reschedule a delivery", "intent": "delivery_change", "queue": "delivery", "w": 0.09, "ai": 0.72, "aht_h": 360, "aht_ai": 150, "sent": -0.05, "carrier": True},
    "damaged_on_delivery": {"label": "Damaged on delivery", "intent": "damaged_item", "queue": "returns", "w": 0.07, "ai": 0.58, "aht_h": 600, "aht_ai": 210, "sent": -0.45, "carrier": True},
    "return_request": {"label": "Return or exchange", "intent": "return_request", "queue": "returns", "w": 0.10, "ai": 0.66, "aht_h": 420, "aht_ai": 170, "sent": -0.08, "carrier": False},
    "refund_status": {"label": "Refund status", "intent": "refund_status", "queue": "returns", "w": 0.09, "ai": 0.78, "aht_h": 300, "aht_ai": 110, "sent": -0.2, "carrier": False},
    "installation_issue": {"label": "Installation appointment issue", "intent": "installation_info", "queue": "delivery", "w": 0.07, "ai": 0.38, "aht_h": 540, "aht_ai": 200, "sent": -0.3, "carrier": False},
    "warranty_claim": {"label": "Warranty & repair", "intent": "warranty_claim", "queue": "warranty", "w": 0.05, "ai": 0.42, "aht_h": 660, "aht_ai": 240, "sent": -0.18, "carrier": False},
    "billing_dispute": {"label": "Billing & payment question", "intent": "billing_question", "queue": "billing", "w": 0.07, "ai": 0.48, "aht_h": 420, "aht_ai": 160, "sent": -0.22, "carrier": False},
    "address_change": {"label": "Change delivery address", "intent": "address_change", "queue": "delivery", "w": 0.04, "ai": 0.74, "aht_h": 300, "aht_ai": 130, "sent": 0.0, "carrier": False},
    "product_info": {"label": "Product & availability question", "intent": "product_info", "queue": "general", "w": 0.08, "ai": 0.92, "aht_h": 270, "aht_ai": 90, "sent": 0.1, "carrier": False},
    "loyalty_points": {"label": "Loyalty points & vouchers", "intent": "policy_question", "queue": "general", "w": 0.04, "ai": 0.9, "aht_h": 240, "aht_ai": 80, "sent": 0.12, "carrier": False},
    "complaint_service": {"label": "Service complaint", "intent": "complaint", "queue": "escalations", "w": 0.04, "ai": 0.12, "aht_h": 780, "aht_ai": 260, "sent": -0.6, "carrier": False},
    "cancel_order": {"label": "Cancel an order", "intent": "cancel_order", "queue": "returns", "w": 0.04, "ai": 0.7, "aht_h": 270, "aht_ai": 100, "sent": -0.1, "carrier": False},
}

PRODUCTS = ["3-seater sofa", "oak dining table", "wardrobe", "king-size mattress", "washing machine", "bookshelf", "coffee table", "armchair", "dishwasher", "bed frame", "kitchen island", "floor lamp"]
PRODUCTS_BULKY = ["3-seater sofa", "wardrobe", "king-size mattress", "washing machine", "dishwasher", "bed frame", "oak dining table"]

SUMMARY_TEMPLATES: dict[str, list[str]] = {
    "order_status": [
        "Customer asks where the {product} order is and when the {carrier} delivery will arrive; tracking shows in transit.",
        "Tracking enquiry: customer cannot see a delivery date for the {product}; checked shipment status with {carrier}.",
        "Customer wants the estimated delivery time for the {product} order and a tracking link.",
    ],
    "delivery_reschedule": [
        "Customer needs to reschedule the {carrier} delivery of the {product} to a different day.",
        "Request to move the delivery appointment for the {product}; the customer is not at home on the planned date.",
        "Customer asks for a new delivery slot because of travel; rebooked the {product} delivery.",
    ],
    "damaged_on_delivery": [
        "Customer reports the {product} arrived damaged on delivery by {carrier}: dented panel and scratches; asks for replacement or refund.",
        "Item damaged in transit: the {product} delivered by {carrier} has visible damage; photos supplied, wants pickup and refund.",
        "The {product} arrived broken when {carrier} delivered it; customer upset and requests a replacement.",
    ],
    "return_request": [
        "Customer wants to return the {product} within the return window because it does not fit the room.",
        "Return request for the {product}: changed mind, asks about the return pickup and refund timing.",
        "Customer asks how to exchange the {product} for a different colour and how the return works.",
    ],
    "refund_status": [
        "Customer asks when the refund for the returned {product} will arrive on the card; refund was issued, takes 3-5 days.",
        "Refund status enquiry: the customer has not yet seen the money back for the cancelled {product} order.",
        "Customer wants confirmation that the refund for the {product} was processed and which method was used.",
    ],
    "installation_issue": [
        "Installer did not arrive for the {product} installation appointment; customer wants a new date and an apology.",
        "Installation appointment issue: the fitting of the {product} is incomplete and a technician must return.",
        "Customer complains the assembly team of the {product} was late and left parts behind; asks for a revisit.",
    ],
    "warranty_claim": [
        "The {product} stopped working after 14 months; customer asks for a warranty repair under the 24-month guarantee.",
        "Warranty claim for the {product}: defect appeared after the return window; documents the fault with a photo.",
        "Customer reports a manufacturing defect on the {product} and wants to open a repair case.",
    ],
    "billing_dispute": [
        "Customer sees a double charge on the card for the {product} order and asks for the duplicate payment to be reversed.",
        "Billing question: the invoice amount for the {product} differs from the checkout total; customer wants an explanation.",
        "Customer disputes a payment authorisation hold for the {product} order that is still pending.",
    ],
    "address_change": [
        "Customer moved house and needs the delivery address of the {product} order updated before dispatch.",
        "Address correction for the {product} order: wrong postal code entered at checkout.",
        "Customer wants the {product} delivered to a work address instead of the home address.",
    ],
    "product_info": [
        "Customer asks for the dimensions and available colours of the {product} before ordering.",
        "Product question: does the {product} come with assembly instructions and is it in stock in the nearest store.",
        "Customer compares two {product} models and asks about materials and delivery lead time.",
    ],
    "loyalty_points": [
        "Customer asks how many loyalty points are on the account and how to redeem a voucher on the next order.",
        "Loyalty question: points from the {product} purchase are missing; customer asks when they will be credited.",
        "Customer wants to know the loyalty tier benefits and whether the voucher can be combined with a promotion.",
    ],
    "complaint_service": [
        "Customer complains about repeated poor service and unanswered emails regarding the {product}; demands a manager callback.",
        "Formal complaint: the customer was passed between departments three times and nobody solved the {product} problem.",
        "Angry customer says the promised callback never happened and threatens to escalate the complaint.",
    ],
    "cancel_order": [
        "Customer wants to cancel the {product} order before it ships because the delivery date is too late.",
        "Cancellation request for the {product} order placed by mistake; asks for confirmation and refund.",
        "Customer asks to cancel the order for the {product} after finding a better offer elsewhere.",
    ],
}
GENERIC_SUMMARY = "Short contact about the {product} order, handled and closed."
REASON = {  # wrap-up summaries start with the contact reason (CC-09 wrap-up format)
    "order_status": "Reason: delivery tracking and ETA", "delivery_reschedule": "Reason: reschedule delivery slot", "damaged_on_delivery": "Reason: item damaged on delivery",
    "return_request": "Reason: return or exchange request", "refund_status": "Reason: refund status and payout", "installation_issue": "Reason: installation appointment problem",
    "warranty_claim": "Reason: warranty repair claim", "billing_dispute": "Reason: billing and payment dispute", "address_change": "Reason: change of delivery address",
    "product_info": "Reason: product information and stock", "loyalty_points": "Reason: loyalty points and vouchers", "complaint_service": "Reason: service complaint and manager callback",
    "cancel_order": "Reason: order cancellation",
}  # fmt: skip
TEXTS_PATH = Path(__file__).resolve().parent.parent / "data" / "reason_texts.jsonl"


@lru_cache(maxsize=1)
def reason_texts() -> dict[tuple[str, str], list[str]]:
    """Optional pre-generated customer opening messages (topic, language) -> texts, created once with a cheap model (see scripts/gen_reason_texts.py)."""
    pool: dict[tuple[str, str], list[str]] = {}
    if TEXTS_PATH.exists():
        for line in TEXTS_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                pool.setdefault((row["topic"], row["lang"]), []).append(row["text"])
    return pool


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _choice(rng: random.Random, weighted: list[tuple[str, float]]) -> str:
    r, acc = rng.random() * sum(w for _, w in weighted), 0.0
    for key, w in weighted:
        acc += w
        if r <= acc:
            return key
    return weighted[-1][0]


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _emotion(sent: float) -> str:
    return "angry" if sent <= -0.6 else "frustrated" if sent <= -0.3 else "anxious" if sent <= -0.1 else "satisfied" if sent >= 0.35 else "neutral"


def _agent_skill() -> dict[str, dict[str, float]]:
    """Per human agent quality offsets per QA dimension (fixed so coaching has recurring weak spots to find)."""
    base = {a: {d: 0.0 for d in qa_engine.DIMENSIONS} for a in HUMAN_AGENTS}
    base["AG-07"].update({"empathy": -1.0, "greeting": -0.6})
    base["AG-04"].update({"accuracy": -0.7, "policy": -0.5})
    base["AG-11"].update({"clarity": -0.8, "resolution": -0.4})
    base["AG-03"].update({"empathy": 0.4, "resolution": 0.3})
    base["AG-10"].update({"empathy": 0.5, "accuracy": 0.3})
    return base


def _qa(rng: random.Random, human: bool, agent_id: str, topic: str, resolved: bool, sent_start: float) -> tuple[dict[str, int], float, str, bool]:
    skill = _agent_skill().get(agent_id, {})
    mean = {"greeting": 4.6, "empathy": 4.0, "accuracy": 4.4, "policy": 4.5, "resolution": 4.2, "compliance": 4.8, "clarity": 4.4}
    if not human:
        mean.update({"greeting": 4.9, "empathy": 3.8, "accuracy": 4.5, "policy": 4.8, "compliance": 4.9, "clarity": 4.7})
        if sent_start < -0.4:
            mean["empathy"] -= 0.5
    dims: dict[str, int] = {}
    for d in qa_engine.DIMENSIONS:
        m = mean[d] + skill.get(d, 0.0)
        if d == "resolution" and not resolved:
            m -= 1.8
        if d == "empathy" and sent_start < -0.4 and human:
            m -= 0.2
        dims[d] = int(_clamp(round(rng.gauss(m, 0.55)), 1, 5))
    auto_fail = rng.random() < (0.007 if not human else 0.011)
    if auto_fail:
        dims["compliance"] = 1
    overall = qa_engine.overall_score(dims)
    return dims, overall, qa_engine.band(overall, auto_fail), auto_fail


def _text(rng: random.Random, topic: str, lang: str, summary: str) -> str:
    pool = reason_texts().get((topic, lang))
    return rng.choice(pool) if pool else summary


def generate_history(anchor_ts: float, *, days: int = DAYS, seed: int = SEED, spike: bool = True, per_day: float = 21.0) -> list[dict[str, Any]]:
    """Interaction records for [anchor - days, anchor). `anchor_ts` should be midnight UTC."""
    rng = random.Random(seed)
    anchor = datetime.fromtimestamp(anchor_ts, UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    topic_w = [(t, v["w"]) for t, v in TOPICS.items()]
    market_w = list(MARKET_WEIGHTS.items())
    customers = [f"CU-{n}" for n in range(2000, 2900)]
    followups: list[tuple[datetime, str, str]] = []  # (earliest, customer, topic) of unresolved contacts
    out: list[dict[str, Any]] = []
    n = 0
    for d in range(days):
        day = anchor - timedelta(days=days - d)
        dow = day.weekday()
        trend = 1.0 + 0.0012 * d
        promo = 1.35 if d in (days - 31, days - 30) else 1.0  # two promotion days
        lam = per_day * DOW_FACTOR[dow] * trend * promo
        count = _poisson(rng, lam)
        plan: list[tuple[str, str | None]] = [(_choice(rng, topic_w), None) for _ in range(count)]
        if spike and d >= days - SPIKE_DAYS:
            plan += [("damaged_on_delivery", SPIKE_CARRIER if rng.random() < 0.92 else rng.choice(CARRIERS)) for _ in range(_poisson(rng, 8.5))]
        for topic, forced_carrier in plan:
            n += 1
            spec = TOPICS[topic]
            customer = None
            due = [f for f in followups if f[0] <= day and f[2] == topic]
            if due and rng.random() < 0.55:
                fu = rng.choice(due)
                followups.remove(fu)
                customer = fu[1]
            customer = customer or rng.choice(customers)
            market = _choice(rng, market_w)
            lang = MARKETS[market]
            channel = _choice(rng, CHANNELS)
            hour = int(_clamp(rng.gauss(14, 4.6), 7, 22))
            ts = (day + timedelta(hours=hour, minutes=rng.randint(0, 59), seconds=rng.randint(0, 59))).timestamp()
            ramp = 0.8 + 0.2 * d / max(days - 1, 1)
            ai_p = spec["ai"] * ramp
            if forced_carrier == SPIKE_CARRIER:
                ai_p *= 0.7
            contained = rng.random() < ai_p
            handled_by = "ai" if contained else "human"
            escalated = not contained and rng.random() < 0.85
            agent_id = AI_AGENT if contained else rng.choice(HUMAN_AGENTS)
            sent0 = _clamp(rng.gauss(spec["sent"] - (0.12 if forced_carrier == SPIKE_CARRIER else 0), 0.28), -1, 1)
            carrier = forced_carrier or (rng.choice(CARRIERS) if spec["carrier"] else None)
            wait = 0.0 if contained else max(5.0, rng.lognormvariate(math.log(55), 0.55) * (1.6 if (forced_carrier or topic == "damaged_on_delivery") and d >= days - SPIKE_DAYS else 1.0))
            abandoned = (not contained) and rng.random() < min(0.35, 0.02 + max(0.0, wait - 120) / 900)
            resolved = False if abandoned else rng.random() < (0.93 if contained else 0.9)
            aht = (spec["aht_ai"] * rng.lognormvariate(0, 0.25)) if contained else spec["aht_h"] * rng.lognormvariate(0, 0.28)
            if abandoned:
                aht = 0.0
            sent1 = _clamp(sent0 + (0.35 if resolved else -0.12) + rng.gauss(0, 0.12), -1, 1)
            dims, overall, band_, auto_fail = _qa(rng, not contained, agent_id, topic, resolved, sent0)
            product = rng.choice(PRODUCTS_BULKY if topic in ("damaged_on_delivery", "installation_issue") else PRODUCTS)
            template = rng.choice(SUMMARY_TEMPLATES[topic]) if rng.random() > 0.06 else GENERIC_SUMMARY
            template_index = SUMMARY_TEMPLATES[topic].index(template) if template in SUMMARY_TEMPLATES[topic] else None
            summary = f"{REASON[topic]}. " + template.format(product=product, carrier=carrier or "the carrier")
            ai_cost = 0.0
            if contained or escalated:
                ai_cost = (0.085 if channel == "voice" else 0.011) * rng.lognormvariate(0, 0.3) * (1.0 if contained else 0.45)
            rec = {
                "id": f"H-{n:05d}", "ts": ts, "date": datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d"), "week": datetime.fromtimestamp(ts, UTC).strftime("%G-W%V"), "hour": hour,
                "market": market, "language": lang, "channel": channel, "topic": topic, "intent": spec["intent"], "queue": spec["queue"], "carrier": carrier, "product": product,
                "customer_id": customer, "handled_by": handled_by, "agent_id": agent_id, "escalated": escalated, "contained": contained, "resolved": resolved, "abandoned": abandoned,
                "wait_s": round(wait, 1), "aht_s": round(aht, 1), "acw_s": 0.0 if contained else round(max(30.0, rng.gauss(125, 35)), 1),
                "sentiment_start": round(sent0, 3), "sentiment_end": round(sent1, 3), "emotion": _emotion(sent0), "csat_pred": round(_clamp(3.1 + 1.9 * sent1 + rng.gauss(0, 0.3), 1, 5), 2),
                "qa_overall": overall, "qa_dims": dims, "qa_band": band_, "qa_auto_fail": auto_fail,
                "disposition": "abandoned" if abandoned else ("resolved_ai" if contained and resolved else "resolved_agent" if resolved else "escalated" if escalated else "unresolved"),
                "summary": summary, "text": _text(rng, topic, lang, summary), "ai_cost_usd": round(ai_cost, 5),
            }  # fmt: skip
            rec.update(synth_pl.record_fields(topic, product, carrier, template_index, n, market))  # Polish fields: no random draw, no other field changes
            out.append(rec)
            if not resolved and rng.random() < 0.7:
                followups.append((day + timedelta(days=rng.randint(1, 5)), customer, topic))
    out.sort(key=lambda r: r["ts"])
    return out


# ------------------------------------------------------------------------------------------------------ WFM interval history
WFM_QUEUES: dict[str, dict[str, Any]] = {
    "general": {"daily": 520, "aht_s": 400, "peaks": [(10.5, 2.2, 0.45), (14.5, 2.0, 0.25), (19.5, 1.8, 0.30)]},
    "delivery": {"daily": 640, "aht_s": 470, "peaks": [(8.5, 1.8, 0.40), (12.0, 2.4, 0.35), (18.5, 2.0, 0.25)]},
    "returns": {"daily": 390, "aht_s": 520, "peaks": [(11.0, 2.2, 0.40), (15.0, 2.2, 0.30), (20.0, 1.8, 0.30)]},
    "warranty": {"daily": 130, "aht_s": 620, "peaks": [(10.0, 2.2, 0.50), (14.0, 2.4, 0.35), (18.0, 2.0, 0.15)]},
    "billing": {"daily": 240, "aht_s": 430, "peaks": [(9.5, 2.0, 0.40), (13.0, 2.4, 0.40), (17.5, 2.0, 0.20)]},
}
INTERVALS_PER_DAY = 48

# Polish-market queues: a separate generator and random stream, so the five global queues (and every number planned from them) stay exactly as before.
# The 30-minute intervals of these queues are in Europe/Warsaw local time; Polish public holidays carry `event: "holiday"` (excluded from back-tests).
WFM_QUEUES_PL: dict[str, dict[str, Any]] = {
    "general-pl": {"daily": 42, "aht_s": 410, "peaks": [(10.0, 2.0, 0.45), (14.0, 2.0, 0.30), (19.0, 1.8, 0.25)], "market": "PL", "timezone": "Europe/Warsaw"},
    "delivery-pl": {"daily": 58, "aht_s": 480, "peaks": [(8.5, 1.8, 0.40), (12.0, 2.2, 0.35), (18.0, 2.0, 0.25)], "market": "PL", "timezone": "Europe/Warsaw"},
}


def queue_spec(queue: str) -> dict[str, Any]:
    return WFM_QUEUES.get(queue) or WFM_QUEUES_PL[queue]


def pl_holidays(year: int) -> set[str]:
    """Polish public holidays (fixed dates plus Easter Monday, Pentecost Sunday and Corpus Christi) as ISO dates."""
    a, b, c = year % 19, year // 100, year % 100  # Easter Sunday: Meeus / Jones / Butcher algorithm
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month, day = divmod(h + el - 7 * m + 114, 31)
    easter = datetime(year, month, day + 1, tzinfo=UTC)
    fixed = [(1, 1), (1, 6), (5, 1), (5, 3), (8, 15), (11, 1), (11, 11), (12, 25), (12, 26)]
    days = {datetime(year, mo, dd, tzinfo=UTC) for mo, dd in fixed} | {easter, easter + timedelta(days=1), easter + timedelta(days=49), easter + timedelta(days=60)}
    return {f"{d:%Y-%m-%d}" for d in days}


def intraday_profile(queue: str) -> list[float]:
    peaks = queue_spec(queue)["peaks"]
    raw = []
    for i in range(INTERVALS_PER_DAY):
        h = i / 2 + 0.25
        raw.append(0.012 + sum(w * math.exp(-0.5 * ((h - mu) / sd) ** 2) / sd for mu, sd, w in peaks))
    total = sum(raw)
    return [v / total for v in raw]


def generate_wfm_history(anchor_ts: float, *, days: int = DAYS, seed: int = SEED, spike: bool = True) -> list[dict[str, Any]]:
    rng = random.Random(seed + 7)
    anchor = datetime.fromtimestamp(anchor_ts, UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    docs: list[dict[str, Any]] = []
    for queue, spec in WFM_QUEUES.items():
        profile = intraday_profile(queue)
        for d in range(days):
            day = anchor - timedelta(days=days - d)
            factor = DOW_FACTOR[day.weekday()] * (1 + 0.0012 * d) * (1.35 if d in (days - 31, days - 30) else 1.0)
            if spike and queue in ("returns", "delivery") and d >= days - SPIKE_DAYS:
                factor *= 1.22 if queue == "returns" else 1.08
            level = spec["daily"] * factor * rng.lognormvariate(0, 0.04)
            intervals = [_poisson(rng, level * p) for p in profile]
            docs.append({"id": f"{queue}:{day:%Y-%m-%d}", "queue": queue, "date": f"{day:%Y-%m-%d}", "dow": day.weekday(), "intervals": intervals, "total": sum(intervals), "aht_s": spec["aht_s"], "interval_minutes": 30, "event": "promo" if d in (days - 31, days - 30) else None})
    return docs


def generate_wfm_history_pl(anchor_ts: float, *, days: int = DAYS, seed: int = SEED, spike: bool = True) -> list[dict[str, Any]]:
    """Interval history of the Polish-market queues (local time, Europe/Warsaw); deterministic, own random stream."""
    rng = random.Random(seed + 11)
    anchor = datetime.fromtimestamp(anchor_ts, UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    holidays = pl_holidays(anchor.year) | pl_holidays(anchor.year - 1)
    docs: list[dict[str, Any]] = []
    for queue, spec in WFM_QUEUES_PL.items():
        profile = intraday_profile(queue)
        for d in range(days):
            day = anchor - timedelta(days=days - d)
            date = f"{day:%Y-%m-%d}"
            holiday = date in holidays
            factor = DOW_FACTOR[day.weekday()] * (1 + 0.0012 * d) * (1.35 if d in (days - 31, days - 30) else 1.0) * (0.25 if holiday else 1.0)
            if spike and queue == "delivery-pl" and d >= days - SPIKE_DAYS:
                factor *= 1.08
            level = spec["daily"] * factor * rng.lognormvariate(0, 0.04)
            intervals = [_poisson(rng, level * p) for p in profile]
            docs.append({
                "id": f"{queue}:{date}", "queue": queue, "date": date, "dow": day.weekday(), "intervals": intervals, "total": sum(intervals), "aht_s": spec["aht_s"], "interval_minutes": 30,
                "event": "holiday" if holiday else ("promo" if d in (days - 31, days - 30) else None), "market": "PL", "timezone": "Europe/Warsaw",
            })  # fmt: skip
    return docs


def anchor_midnight(now_ts: float) -> float:
    return datetime.fromtimestamp(now_ts, UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
