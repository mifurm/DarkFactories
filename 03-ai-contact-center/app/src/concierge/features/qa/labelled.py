"""Labelled QA transcripts: synthetic conversations with reference ('human QA') scores per dimension (1-5) for agreement testing."""

from __future__ import annotations

from typing import Any

from ...engine.models import Conversation, ToolRecord
from ...engine.understanding import analyze

DISC_EN = "You're chatting with Concierge, Contoso Home's AI assistant. A human colleague is available at any time - just ask. This conversation may be recorded and analysed to improve service."
DISC_DE = "Sie schreiben mit Concierge, dem KI-Assistenten von Contoso Home. Auf Wunsch verbinde ich Sie jederzeit mit einem Mitarbeiter. Das Gespräch kann zur Qualitätssicherung aufgezeichnet und ausgewertet werden."
OK_STEPS = [{"tool": "customer_confirmation", "status": "ok", "summary": "customer confirmed", "ts": 100.0}, {"tool": "issue_refund", "status": "ok", "summary": "Refund EUR 379.00", "ts": 101.0}]
ORDER_TOOL = ToolRecord(id="t1", name="lookup_order", args={}, status="ok", result={"total_eur": 379.0, "items": [{"unit_price_eur": 379.0}]}, ts=99.0)
REFUND_TOOL = ToolRecord(id="t2", name="issue_refund", args={}, status="ok", result={"amount_eur": 379.0, "status": "issued"}, idempotency_key="k", actor="ai", ts=101.0)

# (name, messages[(role, text, flags)], steps, tools_on_last_ai, extra, reference dims)
CASES: list[dict[str, Any]] = [
    {"name": "excellent_ai_resolution", "msgs": [("agent_ai", DISC_EN, ["disclosure"]), ("customer", "My sofa arrived damaged, order CH-100231.", []), ("agent_ai", "I'm so sorry about that - a damaged sofa is frustrating. Under our damage policy you can choose a free replacement or a full refund of EUR 379.00, and pickup is free. Which would you prefer?", []), ("customer", "Refund please.", []), ("agent_ai", "Here is the plan: refund EUR 379.00 and a free pickup. Shall I go ahead?", []), ("customer", "Yes.", []), ("agent_ai", "Done - the refund of EUR 379.00 is on its way and the pickup is booked. Anything else?", [])], "steps": OK_STEPS, "tools": [ORDER_TOOL, REFUND_TOOL], "ref": {"greeting": 5, "empathy": 5, "accuracy": 5, "policy": 5, "resolution": 5, "compliance": 5, "clarity": 5}},
    {"name": "no_empathy_ai", "msgs": [("agent_ai", DISC_EN, ["disclosure"]), ("customer", "My sofa arrived damaged and I am really annoyed!", []), ("agent_ai", "Please provide the order number.", []), ("customer", "CH-100231", []), ("agent_ai", "Refund of EUR 379.00 processed.", [])], "steps": OK_STEPS, "tools": [ORDER_TOOL, REFUND_TOOL], "ref": {"greeting": 5, "empathy": 1, "accuracy": 5, "policy": 5, "resolution": 5, "compliance": 5, "clarity": 4}},
    {"name": "missing_disclosure", "msgs": [("agent_ai", "Hi, what can I do for you?", []), ("customer", "Where is my order CH-100232?", []), ("agent_ai", "Your order is in transit and should arrive tomorrow.", [])], "steps": [{"tool": "track_shipment", "status": "ok", "summary": "track", "ts": 1.0}], "tools": [], "ref": {"greeting": 3, "empathy": 4, "accuracy": 5, "policy": 5, "resolution": 5, "compliance": 1, "clarity": 5}},
    {"name": "risky_promise_delivered", "msgs": [("agent_ai", DISC_EN, ["disclosure"]), ("customer", "My table is cracked.", []), ("agent_ai", "I'm sorry to hear that. I guarantee you a full refund, no matter what.", []), ("customer", "Great.", [])], "steps": [], "tools": [], "ref": {"greeting": 5, "empathy": 5, "accuracy": 3, "policy": 3, "resolution": 1, "compliance": 1, "clarity": 5}},
    {"name": "wrong_amount", "msgs": [("agent_ai", DISC_EN, ["disclosure"]), ("customer", "My sofa arrived damaged.", []), ("agent_ai", "Sorry about that. I can refund EUR 429.00 for the sofa.", [])], "steps": OK_STEPS, "tools": [ORDER_TOOL, REFUND_TOOL], "ref": {"greeting": 5, "empathy": 5, "accuracy": 3, "policy": 5, "resolution": 5, "compliance": 5, "clarity": 5}},
    {"name": "long_winded", "msgs": [("agent_ai", DISC_EN, ["disclosure"]), ("customer", "How do I return something?", []), ("agent_ai", " ".join(["Thank you very much for contacting Contoso Home today regarding your return request and we truly appreciate your patience and understanding while we explain the entire process in great detail so that everything is perfectly clear."] * 3), [])], "steps": [], "tools": [], "ref": {"greeting": 5, "empathy": 4, "accuracy": 4, "policy": 5, "resolution": 2, "compliance": 5, "clarity": 2}},
    {"name": "abandoned", "msgs": [("agent_ai", DISC_EN, ["disclosure"]), ("customer", "Hi", [])], "steps": [], "tools": [], "status": "abandoned", "ref": {"greeting": 5, "empathy": 4, "accuracy": 5, "policy": 5, "resolution": 1, "compliance": 5, "clarity": 5}},
    {"name": "good_escalation", "msgs": [("agent_ai", DISC_EN, ["disclosure"]), ("customer", "This is outrageous, I will contact my lawyer about my broken washing machine!", []), ("agent_ai", "I'm very sorry about this experience. I'm bringing in a colleague who can see our conversation so you won't need to repeat anything.", ["handoff_notice"])], "steps": [], "tools": [], "handoff": True, "ref": {"greeting": 5, "empathy": 5, "accuracy": 5, "policy": 5, "resolution": 4, "compliance": 5, "clarity": 5}},
    {"name": "good_human", "msgs": [("agent_ai", DISC_EN, ["disclosure"]), ("customer", "The installer missed me twice, this is unacceptable.", []), ("agent_human", "Hello, my name is Hannah and I'm happy to help. I'm so sorry that the installer missed you twice - I understand how frustrating that is. I'll rebook you with priority within 48 hours and add a goodwill credit. Is that okay?", []), ("customer", "Yes, thank you.", [])], "steps": [{"tool": "goodwill_credit", "status": "ok", "summary": "credit", "ts": 5.0}], "tools": [], "ref": {"greeting": 5, "empathy": 5, "accuracy": 5, "policy": 5, "resolution": 5, "compliance": 5, "clarity": 4}},
    {"name": "curt_human", "msgs": [("agent_ai", DISC_EN, ["disclosure"]), ("customer", "This is terrible service, I am furious!", []), ("agent_human", "What is your order number.", []), ("customer", "CH-100250!", []), ("agent_human", "Wait.", [])], "steps": [], "tools": [], "ref": {"greeting": 1, "empathy": 1, "accuracy": 5, "policy": 5, "resolution": 1, "compliance": 5, "clarity": 4}},
    {"name": "late_empathy", "msgs": [("agent_ai", DISC_EN, ["disclosure"]), ("customer", "My delivery is two weeks late and I am really frustrated.", []), ("agent_ai", "Please share your order number.", []), ("customer", "CH-100280", []), ("agent_ai", "Thanks. Your order is delayed at the hub.", []), ("customer", "OK", []), ("agent_ai", "I'm sorry for the delay. I've added a goodwill credit.", [])], "steps": [{"tool": "goodwill_credit", "status": "ok", "summary": "credit", "ts": 5.0}], "tools": [], "ref": {"greeting": 5, "empathy": 3, "accuracy": 5, "policy": 3, "resolution": 5, "compliance": 5, "clarity": 5}},
    {"name": "no_confirmation", "msgs": [("agent_ai", DISC_EN, ["disclosure"]), ("customer", "Refund my sofa please, order CH-100231.", []), ("agent_ai", "Sorry about that. I've refunded EUR 379.00 right away.", [])], "steps": [{"tool": "issue_refund", "status": "ok", "summary": "Refund EUR 379.00", "ts": 101.0}], "tools": [ORDER_TOOL, REFUND_TOOL], "ref": {"greeting": 5, "empathy": 5, "accuracy": 5, "policy": 2, "resolution": 5, "compliance": 5, "clarity": 5}},
    {"name": "ticket_deferral", "msgs": [("agent_ai", DISC_EN, ["disclosure"]), ("customer", "I have a complaint about the service.", []), ("agent_ai", "I'm sorry to hear that. I created a ticket and a colleague will follow up.", [])], "steps": [{"tool": "create_ticket", "status": "ok", "summary": "ticket", "ts": 3.0}], "tools": [], "ref": {"greeting": 5, "empathy": 5, "accuracy": 5, "policy": 5, "resolution": 3, "compliance": 5, "clarity": 5}},
    {"name": "german_good_ai", "msgs": [("agent_ai", DISC_DE, ["disclosure"]), ("customer", "Mein Sofa ist beschädigt angekommen.", []), ("agent_ai", "Das tut mir leid. Sie können einen kostenlosen Ersatz oder die volle Erstattung von 379.00 EUR wählen. Was möchten Sie?", []), ("customer", "Erstattung.", []), ("agent_ai", "Erledigt: Die Erstattung von 379.00 EUR ist veranlasst. Noch etwas?", [])], "steps": OK_STEPS, "tools": [ORDER_TOOL, REFUND_TOOL], "ref": {"greeting": 5, "empathy": 5, "accuracy": 5, "policy": 5, "resolution": 5, "compliance": 5, "clarity": 5}},
    {"name": "shouting_human", "msgs": [("agent_ai", DISC_EN, ["disclosure"]), ("customer", "Where is my refund?", []), ("agent_human", "Hello, this is Max. YOU NEED TO WAIT FOR THE BANK, THIS IS NOT OUR PROBLEM AND I ALREADY TOLD YOU.", []), ("customer", "ok", [])], "steps": [], "tools": [], "ref": {"greeting": 4, "empathy": 4, "accuracy": 5, "policy": 5, "resolution": 1, "compliance": 5, "clarity": 3}},
]


def build_case(case: dict[str, Any]) -> Conversation:
    conv = Conversation(id=f"lab-{case['name']}", language="de" if "german" in case["name"] else "en")
    t = 10.0
    for role, text, flags in case["msgs"]:
        m = conv.add(role, text, flags=list(flags), ts=t)
        t += 2
        if role == "customer":
            u = analyze(text)
            m.meta["understanding"] = {"intent": u.intent, "sentiment": u.sentiment, "emotion": u.emotion}
            conv.sentiment_trajectory.append(u.sentiment)
            conv.understanding = u
    ai = [m for m in conv.messages if m.role == "agent_ai"]
    if case.get("tools") and ai:
        ai[-1].tools = list(case["tools"])
    conv.steps = list(case.get("steps", []))
    conv.status = case.get("status", "resolved")
    if case.get("handoff"):
        conv.handler = "queue"
        conv.handoff = {"trigger": {"code": "legal_threat", "reason": "legal"}, "package": {"completeness": 95}}
    if any(m.role == "agent_human" for m in conv.messages):
        conv.handler = "human"
    return conv
