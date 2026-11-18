"""Skills-based routing with Job-Router-style semantics, implemented in-process and provider-neutral (CC-06; ACS Job Router retires in 2028):
queues + classification policy (priority rules) + distribution policy (longest-idle) + exception policy (SLA risk),
and explicit, configurable escalation triggers. Pure, deterministic functions - fully table-testable."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .models import Conversation, Understanding
from .understanding import similar

QUEUES: dict[str, dict[str, Any]] = {
    "general": {"name": "General support", "sla_s": 120, "skills": ["support"], "distribution": "longest-idle"},
    "delivery": {"name": "Delivery & installation", "sla_s": 120, "skills": ["delivery"], "distribution": "longest-idle"},
    "returns": {"name": "Returns & refunds", "sla_s": 180, "skills": ["returns"], "distribution": "longest-idle"},
    "warranty": {"name": "Warranty & repairs", "sla_s": 240, "skills": ["warranty"], "distribution": "longest-idle"},
    "billing": {"name": "Billing & payments", "sla_s": 180, "skills": ["billing"], "distribution": "longest-idle"},
    "escalations": {"name": "Escalations & legal", "sla_s": 60, "skills": ["senior"], "distribution": "best-worker"},
    "vip": {"name": "VIP concierge", "sla_s": 30, "skills": ["vip"], "distribution": "best-worker"},
    "care": {"name": "Customer care (vulnerable)", "sla_s": 30, "skills": ["care"], "distribution": "best-worker"},
    "fraud": {"name": "Fraud & security", "sla_s": 60, "skills": ["fraud"], "distribution": "best-worker"},
}

ROUTING_RULES = [
    {"id": "R1", "when": "risk flag fraud_suspected", "queue": "fraud", "base": 90, "skills": ["fraud"]},
    {"id": "R2", "when": "risk flag legal_threat or regulatory_complaint", "queue": "escalations", "base": 100, "skills": ["legal", "senior"]},
    {"id": "R3", "when": "risk flag safety_issue or welfare_concern", "queue": "escalations", "base": 100, "skills": ["safety", "senior"]},
    {"id": "R4", "when": "vulnerable customer (profile flag or risk flag)", "queue": "care", "base": 95, "skills": ["care"]},
    {"id": "R5", "when": "VIP customer", "queue": "vip", "base": 70, "skills": ["vip"]},
    {"id": "R6", "when": "intent damaged_item/return_request/refund_status/goodwill_request/cancel_order", "queue": "returns", "base": 50, "skills": ["returns"]},
    {"id": "R7", "when": "intent order_status/delivery_change/installation_info/address_change", "queue": "delivery", "base": 50, "skills": ["delivery"]},
    {"id": "R8", "when": "intent warranty_claim", "queue": "warranty", "base": 50, "skills": ["warranty"]},
    {"id": "R9", "when": "intent billing_question", "queue": "billing", "base": 50, "skills": ["billing"]},
    {"id": "R10", "when": "intent complaint", "queue": "escalations", "base": 60, "skills": ["complaints", "senior"]},
    {"id": "R11", "when": "otherwise", "queue": "general", "base": 50, "skills": ["support"]},
]
RETURN_INTENTS = {"damaged_item", "return_request", "refund_status", "goodwill_request", "cancel_order"}
DELIVERY_INTENTS = {"order_status", "delivery_change", "installation_info", "address_change"}


@dataclass
class RoutingDecision:
    queue: str
    priority: int
    required_skills: list[str]
    language: str
    sla_s: int
    rule: str
    reasons: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    distribution: str = "longest-idle"
    exception_policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["queue_name"] = QUEUES[self.queue]["name"]
        return d


def route(
    u: Understanding,
    *,
    vip: bool = False,
    vulnerable: bool = False,
    language: str | None = None,
    channel: str = "web_chat",
    wait_s: float = 0.0,
    extra_risks: list[str] | None = None,
) -> RoutingDecision:
    risks = set(u.risk_flags) | set(extra_risks or [])
    vulnerable = vulnerable or "vulnerable_customer" in risks
    reasons: list[str] = []
    if "fraud_suspected" in risks:
        rule = ROUTING_RULES[0]
    elif risks & {"legal_threat", "regulatory_complaint"}:
        rule = ROUTING_RULES[1]
    elif risks & {"safety_issue", "welfare_concern"}:
        rule = ROUTING_RULES[2]
    elif vulnerable:
        rule = ROUTING_RULES[3]
    elif vip:
        rule = ROUTING_RULES[4]
    elif u.intent in RETURN_INTENTS:
        rule = ROUTING_RULES[5]
    elif u.intent in DELIVERY_INTENTS:
        rule = ROUTING_RULES[6]
    elif u.intent == "warranty_claim":
        rule = ROUTING_RULES[7]
    elif u.intent == "billing_question":
        rule = ROUTING_RULES[8]
    elif u.intent == "complaint":
        rule = ROUTING_RULES[9]
    else:
        rule = ROUTING_RULES[10]
    reasons.append(f"{rule['id']}: {rule['when']}")
    priority = int(rule["base"])
    if vip and rule["id"] != "R5":
        priority += 15
        reasons.append("+15 VIP")
    if vulnerable and rule["id"] != "R4":
        priority += 10
        reasons.append("+10 vulnerable")
    if u.sentiment <= -0.6:
        priority += 10
        reasons.append("+10 very negative sentiment")
    elif u.sentiment <= -0.3:
        priority += 5
        reasons.append("+5 negative sentiment")
    if u.urgency == "critical":
        priority += 10
        reasons.append("+10 critical urgency")
    elif u.urgency == "high":
        priority += 5
        reasons.append("+5 high urgency")
    queue = QUEUES[rule["queue"]]
    sla = int(queue["sla_s"])
    exception = {"at_risk": False, "threshold_s": int(sla * 0.8)}
    if wait_s >= sla * 0.8:
        priority += 20
        exception.update({"at_risk": True, "action": "raise_priority_by_20"})
        reasons.append("+20 SLA exception policy (waited >= 80 % of SLA)")
    skills = list(rule["skills"])
    lang = language or u.language
    return RoutingDecision(
        queue=rule["queue"],
        priority=min(priority, 120),
        required_skills=skills,
        language=lang,
        sla_s=sla,
        rule=rule["id"],
        reasons=reasons,
        inputs={"intent": u.intent, "risk_flags": sorted(risks), "sentiment": u.sentiment, "urgency": u.urgency, "vip": vip, "vulnerable": vulnerable, "channel": channel, "wait_s": wait_s},
        distribution=queue["distribution"],
        exception_policy=exception,
    )


# ---------------------------------------------------------------- workers (simulated human-agent population)
def default_workers() -> list[dict[str, Any]]:
    roster = [
        ("AG-01", "Lena Fischer", ["support", "delivery", "returns"], ["de", "en"]),
        ("AG-02", "Pieter van Dijk", ["support", "delivery", "installation"], ["nl", "en", "de"]),
        ("AG-03", "Camille Bernard", ["support", "returns", "billing", "vip"], ["fr", "en"]),
        ("AG-04", "Sofía Navarro", ["support", "delivery", "warranty"], ["es", "en"]),
        ("AG-05", "Giulia Romano", ["support", "returns", "billing"], ["it", "en"]),
        ("AG-06", "Anna Wiśniewska", ["support", "delivery", "returns"], ["pl", "en"]),
        ("AG-07", "Tiago Ferreira", ["support", "warranty", "billing"], ["pt", "en"]),
        ("AG-08", "Hannah Clarke", ["support", "returns", "senior", "legal", "complaints"], ["en", "de"]),
        ("AG-09", "Daniel Weber", ["senior", "legal", "complaints", "safety", "returns"], ["de", "en"]),
        ("AG-10", "Maya Patel", ["care", "support", "vip", "senior"], ["en", "fr"]),
        ("AG-11", "Jonas Keller", ["fraud", "senior", "billing"], ["de", "en"]),
        ("AG-12", "Isabel Ortega", ["care", "vip", "support", "returns"], ["es", "en", "pt"]),
    ]
    return [
        {"id": i, "name": n, "skills": s, "languages": ls, "capacity": {"voice": 1, "chat": 3}, "presence": "available", "active": [], "last_assigned_at": 0.0}
        for i, n, s, ls in roster
    ]


def select_worker(decision: RoutingDecision, channel: str, workers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Distribution policy: eligible = has ALL required skills, available, free capacity; prefer language match;
    longest-idle (oldest last assignment) breaks ties; 'best-worker' prefers the most specialised (most matching skills)."""
    kind = "voice" if channel == "voice" else "chat"
    eligible = [
        w for w in workers
        if w["presence"] == "available" and set(decision.required_skills) <= set(w["skills"]) and len(w["active"]) < w["capacity"][kind]
    ]  # fmt: skip
    if not eligible:
        return None

    def key(w: dict[str, Any]) -> tuple:
        lang_match = 0 if decision.language in w["languages"] else 1
        specialised = -len(set(decision.required_skills) & set(w["skills"])) if decision.distribution == "best-worker" else 0
        return (lang_match, specialised, w["last_assigned_at"], w["id"])

    return sorted(eligible, key=key)[0]


# ---------------------------------------------------------------- escalation triggers
PRIORITY_ORDER = ["legal_threat", "fraud_suspected", "safety_issue", "welfare_concern", "vulnerable_customer", "explicit_request", "policy_block", "sentiment", "tool_failure", "loop", "knowledge_gap", "regulatory_complaint"]
DEFAULT_THRESHOLDS = {"sentiment_threshold": -0.6, "sentiment_streak_threshold": -0.4, "loop_repeats": 3, "tool_failures": 2, "kb_misses": 2}


@dataclass
class Trigger:
    code: str
    reason: str
    severity: str = "high"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def evaluate_triggers(
    conv: Conversation,
    u: Understanding,
    *,
    explicit_request: bool = False,
    thresholds: dict[str, float] | None = None,
    fired: set[str] | None = None,
) -> list[Trigger]:
    """All escalation triggers currently active, highest priority first. `fired` suppresses codes already raised."""
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    fired = fired or set()
    out: list[Trigger] = []
    risks = set(u.risk_flags) | set(conv.risk_flags)
    if "legal_threat" in risks:
        out.append(Trigger("legal_threat", "Customer mentioned legal action / consumer authority", "critical"))
    if "fraud_suspected" in risks:
        out.append(Trigger("fraud_suspected", "Possible fraud or account takeover", "critical"))
    if risks & {"safety_issue"}:
        out.append(Trigger("safety_issue", "Product safety issue reported", "critical"))
    if "welfare_concern" in risks:
        out.append(Trigger("welfare_concern", "Customer welfare concern", "critical"))
    if "vulnerable_customer" in risks:
        out.append(Trigger("vulnerable_customer", "Customer appears vulnerable - hand to care team", "high"))
    if explicit_request or u.intent == "human_request":
        out.append(Trigger("explicit_request", "Customer asked for a human", "high"))
    if conv.identity.locked:
        out.append(Trigger("policy_block", "Identity verification locked after repeated failures", "high"))
    traj = conv.sentiment_trajectory
    if traj and (traj[-1] <= th["sentiment_threshold"] or (len(traj) >= 2 and traj[-1] <= th["sentiment_streak_threshold"] and traj[-2] <= th["sentiment_streak_threshold"])):
        out.append(Trigger("sentiment", f"Sentiment {traj[-1]:.2f} crossed the escalation threshold", "high"))
    if conv.counters.get("tool_failures", 0) >= th["tool_failures"]:
        out.append(Trigger("tool_failure", "Repeated tool failures", "medium"))
    cust = [m.text for m in conv.messages if m.role == "customer"][-int(th["loop_repeats"]) :]
    trail = conv.intent_trail[-int(th["loop_repeats"]) :]
    if len(cust) >= th["loop_repeats"] and len(set(trail)) == 1 and trail[0] not in ("greeting", "goodbye", "other") and all(similar(cust[i], cust[i + 1]) >= 0.5 for i in range(len(cust) - 1)):
        out.append(Trigger("loop", "Customer is repeating themselves - conversation is not progressing", "medium"))
    elif sum(1 for m in conv.messages if m.role == "agent_ai" and "not_understood" in m.flags) >= 2:
        out.append(Trigger("loop", "Agent could not understand the customer twice", "medium"))
    if conv.counters.get("kb_misses", 0) >= th["kb_misses"]:
        out.append(Trigger("knowledge_gap", "No grounded answer found repeatedly", "medium"))
    if "regulatory_complaint" in risks:
        out.append(Trigger("regulatory_complaint", "Regulatory complaint mentioned", "high"))
    out = [t for t in out if t.code not in fired]
    out.sort(key=lambda t: PRIORITY_ORDER.index(t.code) if t.code in PRIORITY_ORDER else 99)
    return out
