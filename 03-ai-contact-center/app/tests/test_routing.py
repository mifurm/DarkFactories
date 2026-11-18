"""Routing & escalation (brief §5): the deterministic routing matrix (skills / priority / VIP / vulnerable / legal-risk), the distribution policy and
the escalation triggers on seeded transcripts - all pure functions, so the whole matrix is table-tested."""

from __future__ import annotations

import pytest

from concierge.engine.handoff import completeness
from concierge.engine.models import Conversation, Understanding
from concierge.engine.routing import (
    PRIORITY_ORDER,
    QUEUES,
    ROUTING_RULES,
    default_workers,
    evaluate_triggers,
    route,
    select_worker,
)
from conftest import say


def u(intent="other", risks=(), sentiment=0.0, urgency="normal", language="en"):
    return Understanding(intent=intent, risk_flags=list(risks), sentiment=sentiment, urgency=urgency, language=language)


# (id, understanding kwargs, route kwargs, expected queue, expected priority, expected rule)
MATRIX = [
    ("returns/damaged", dict(intent="damaged_item"), {}, "returns", 50, "R6"),
    ("returns/return", dict(intent="return_request"), {}, "returns", 50, "R6"),
    ("returns/refund", dict(intent="refund_status"), {}, "returns", 50, "R6"),
    ("returns/goodwill", dict(intent="goodwill_request"), {}, "returns", 50, "R6"),
    ("returns/cancel", dict(intent="cancel_order"), {}, "returns", 50, "R6"),
    ("delivery/status", dict(intent="order_status"), {}, "delivery", 50, "R7"),
    ("delivery/change", dict(intent="delivery_change"), {}, "delivery", 50, "R7"),
    ("delivery/install", dict(intent="installation_info"), {}, "delivery", 50, "R7"),
    ("delivery/address", dict(intent="address_change"), {}, "delivery", 50, "R7"),
    ("warranty", dict(intent="warranty_claim"), {}, "warranty", 50, "R8"),
    ("billing", dict(intent="billing_question"), {}, "billing", 50, "R9"),
    ("complaint", dict(intent="complaint"), {}, "escalations", 60, "R10"),
    ("general/other", dict(intent="other"), {}, "general", 50, "R11"),
    ("general/policy", dict(intent="policy_question"), {}, "general", 50, "R11"),
    ("vip", dict(intent="damaged_item"), dict(vip=True), "vip", 70, "R5"),
    ("vip+legal", dict(intent="damaged_item", risks=["legal_threat"]), dict(vip=True), "escalations", 115, "R2"),
    ("vip+fraud", dict(intent="billing_question", risks=["fraud_suspected"]), dict(vip=True), "fraud", 105, "R1"),
    ("vulnerable", dict(intent="damaged_item"), dict(vulnerable=True), "care", 95, "R4"),
    ("vulnerable/billing", dict(intent="billing_question"), dict(vulnerable=True), "care", 95, "R4"),
    ("vulnerable via risk flag", dict(intent="order_status", risks=["vulnerable_customer"]), {}, "care", 95, "R4"),
    ("vulnerable+vip", dict(intent="order_status"), dict(vulnerable=True, vip=True), "care", 110, "R4"),
    ("legal+vulnerable", dict(intent="order_status", risks=["legal_threat"]), dict(vulnerable=True), "escalations", 110, "R2"),
    ("fraud beats legal", dict(intent="order_status", risks=["legal_threat", "fraud_suspected"]), {}, "fraud", 90, "R1"),
    ("safety", dict(intent="other", risks=["safety_issue"]), {}, "escalations", 100, "R3"),
    ("welfare", dict(intent="other", risks=["welfare_concern"]), {}, "escalations", 100, "R3"),
    ("regulatory", dict(intent="complaint", risks=["regulatory_complaint"]), {}, "escalations", 100, "R2"),
    ("negative sentiment", dict(intent="order_status", sentiment=-0.35), {}, "delivery", 55, "R7"),
    ("very negative sentiment", dict(intent="order_status", sentiment=-0.7), {}, "delivery", 60, "R7"),
    ("sentiment boundary -0.3", dict(intent="order_status", sentiment=-0.3), {}, "delivery", 55, "R7"),
    ("neutral sentiment", dict(intent="order_status", sentiment=-0.29), {}, "delivery", 50, "R7"),
    ("critical urgency + very negative", dict(intent="damaged_item", sentiment=-0.8, urgency="critical"), {}, "returns", 70, "R6"),
    ("high urgency", dict(intent="billing_question", urgency="high"), {}, "billing", 55, "R9"),
    ("SLA exception (waited 80 % of 180 s)", dict(intent="damaged_item"), dict(wait_s=144), "returns", 70, "R6"),
    ("below SLA exception", dict(intent="damaged_item"), dict(wait_s=143), "returns", 50, "R6"),
    ("priority is capped at 120", dict(intent="other", risks=["legal_threat"], sentiment=-0.9, urgency="critical"), dict(vip=True, vulnerable=True, wait_s=500), "escalations", 120, "R2"),
]


@pytest.mark.parametrize(("name", "ukw", "rkw", "queue", "priority", "rule"), MATRIX, ids=[m[0] for m in MATRIX])
def test_routing_matrix(name, ukw, rkw, queue, priority, rule):
    d = route(u(**ukw), **rkw)
    assert (d.queue, d.priority, d.rule) == (queue, priority, rule), d.reasons
    assert d.sla_s == QUEUES[queue]["sla_s"] and d.reasons[0].startswith(rule)
    assert set(d.required_skills) == set(next(r for r in ROUTING_RULES if r["id"] == rule)["skills"])


def test_routing_is_deterministic_and_explains_itself():
    a, b = route(u("damaged_item", sentiment=-0.7), vip=True), route(u("damaged_item", sentiment=-0.7), vip=True)
    assert a.to_dict() == b.to_dict()
    assert any("VIP" in r for r in a.reasons) or a.rule == "R5"
    assert route(u("order_status"), language="pt").language == "pt"
    assert route(u("order_status", language="pl")).language == "pl"
    assert route(u("x"), wait_s=0).exception_policy == {"at_risk": False, "threshold_s": 96}
    assert len(MATRIX) >= 30


def test_worker_selection_by_skill_language_capacity_presence_and_distribution():
    ws = default_workers()
    pl = select_worker(route(u("damaged_item", language="pl")), "web_chat", ws)
    assert pl["id"] == "AG-06", "returns skill + Polish speaker"
    assert select_worker(route(u("damaged_item"), language="pt"), "web_chat", ws)["id"] == "AG-12", "Portuguese-speaking returns agent"
    legal = route(u("other", risks=["legal_threat"], language="de"))
    first = select_worker(legal, "web_chat", ws)
    assert first["id"] in ("AG-08", "AG-09") and {"legal", "senior"} <= set(first["skills"])
    first["last_assigned_at"] = 9e9  # longest-idle breaks ties between equally specialised agents
    assert select_worker(legal, "web_chat", ws)["id"] != first["id"]
    fraud = route(u("other", risks=["fraud_suspected"]))
    assert select_worker(fraud, "web_chat", ws)["id"] == "AG-11"
    ws11 = next(w for w in ws if w["id"] == "AG-11")
    ws11["presence"] = "away"
    assert select_worker(fraud, "web_chat", ws) is None, "nobody eligible -> caller offers a callback"
    ws11["presence"] = "available"
    ws11["active"] = ["a", "b", "c"]
    assert select_worker(fraud, "web_chat", ws) is None, "chat capacity is 3"
    ws11["active"] = ["a"]
    assert select_worker(fraud, "voice", ws) is None, "voice capacity is 1"


def conv_with(messages=(), **kw) -> Conversation:
    c = Conversation(id="cv_test")
    for text in messages:
        c.add("customer", text)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def codes(c: Conversation, uu: Understanding | None = None, **kw) -> list[str]:
    return [t.code for t in evaluate_triggers(c, uu or u(), **kw)]


def test_each_escalation_trigger_fires_on_its_seeded_signal():
    assert codes(conv_with(), u(risks=["legal_threat"])) == ["legal_threat"]
    assert codes(conv_with(), u(risks=["fraud_suspected"])) == ["fraud_suspected"]
    assert codes(conv_with(), u(risks=["safety_issue"])) == ["safety_issue"]
    assert codes(conv_with(), u(risks=["welfare_concern"])) == ["welfare_concern"]
    assert codes(conv_with(), u(risks=["vulnerable_customer"])) == ["vulnerable_customer"]
    assert codes(conv_with(), u(risks=["regulatory_complaint"])) == ["regulatory_complaint"]
    assert codes(conv_with(), u(intent="human_request")) == ["explicit_request"]
    assert codes(conv_with(), explicit_request=True) == ["explicit_request"]
    c = conv_with()
    c.identity.locked = True
    assert codes(c) == ["policy_block"]
    assert codes(conv_with(sentiment_trajectory=[0.0, -0.65])) == ["sentiment"]
    assert codes(conv_with(sentiment_trajectory=[-0.45, -0.42])) == ["sentiment"], "two consecutive negative turns"
    assert codes(conv_with(sentiment_trajectory=[-0.1, -0.45])) == [], "a single mildly negative turn does not escalate"
    assert codes(conv_with(counters={"tool_failures": 2, "kb_misses": 0, "no_progress": 0, "turns": 3})) == ["tool_failure"]
    assert codes(conv_with(counters={"tool_failures": 0, "kb_misses": 2, "no_progress": 0, "turns": 3})) == ["knowledge_gap"]


def test_loop_trigger_needs_three_similar_repeats_of_a_real_intent():
    rep = ["Where is my order CH-100232?"] * 3
    assert codes(conv_with(rep, intent_trail=["order_status"] * 3)) == ["loop"]
    assert codes(conv_with(rep, intent_trail=["greeting"] * 3)) == []
    assert codes(conv_with(rep[:2], intent_trail=["order_status"] * 2)) == []
    assert codes(conv_with(["Where is my order?", "I want a refund for my sofa please", "The wardrobe is broken"], intent_trail=["order_status"] * 3)) == []
    c = conv_with()
    for _ in range(2):
        c.add("agent_ai", "Sorry?", flags=["not_understood"])
    assert codes(c) == ["loop"]


def test_triggers_are_prioritised_deduplicated_and_suppressed_once_fired():
    c = conv_with(sentiment_trajectory=[-0.8], counters={"tool_failures": 3, "kb_misses": 0, "no_progress": 0, "turns": 2})
    uu = u(risks=["fraud_suspected", "legal_threat"], intent="human_request")
    got = codes(c, uu)
    assert got == sorted(got, key=PRIORITY_ORDER.index) and got[0] == "legal_threat" and {"fraud_suspected", "explicit_request", "sentiment", "tool_failure"} <= set(got)
    assert codes(c, uu, fired={"legal_threat", "fraud_suspected"})[0] == "explicit_request", "a trigger that already fired is not raised again"
    assert codes(conv_with(sentiment_trajectory=[-0.5]), thresholds={"sentiment_threshold": -0.4}) == ["sentiment"]


async def test_escalation_fires_exactly_once_and_the_ai_stops_answering(svc):
    conv = await svc.orchestrator.start(language="en", recording_consent="granted")
    r1 = await say(svc, conv.id, "This is unacceptable! If this isn't fixed today I will contact my lawyer about order CH-100250.")
    c1 = await svc.store.get(conv.id)
    assert c1.handoff and c1.handoff["trigger"]["code"] == "legal_threat" and c1.queue == "escalations" and c1.status == "waiting_human"
    assert r1["status"] == "waiting_human"
    await say(svc, conv.id, "I will sue you, my lawyer will call you. This is a disgrace!")
    await say(svc, conv.id, "Hello? Is anybody there? I want my money back now.")
    c2 = await svc.store.get(conv.id)
    initiated = [a for a in await svc.audit.recent(100) if a["action"] == "handoff.initiated" and a["conv_id"] == conv.id]
    assert len(initiated) == 1, "one handoff per conversation, however often the trigger condition is met"
    notices = [m for m in c2.messages if m.role == "agent_ai" and "colleague" in m.text.lower() and "see" in m.text.lower()]
    assert len(notices) <= 2
    pkg = c2.handoff["package"]
    assert completeness(pkg) >= 90 and pkg["trigger"]["code"] == "legal_threat" and pkg["routing"]["queue"] == "escalations", "the human sees a complete context package"
