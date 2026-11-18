"""Labelled RAG evaluation set (also used by the eval harness): in-scope questions with expected source documents,
unanswerable questions, and seeded fabricated answers for the groundedness check."""

from __future__ import annotations

IN_SCOPE: list[tuple[str, list[str]]] = [
    ("How long do I have to return an item?", ["returns-001"]),
    ("My sofa arrived damaged, what can I do?", ["damage-001"]),
    ("Is the pickup of a returned sofa free?", ["returns-001", "returns-003"]),
    ("When do I get my refund and how is it paid out?", ["refunds-001"]),
    ("What compensation can I get if my delivery is late?", ["refunds-004", "delivery-005"]),
    ("Can I change my delivery date?", ["delivery-003"]),
    ("What happens if nobody is home when the carrier comes?", ["delivery-004"]),
    ("How much does installing a washing machine cost?", ["install-001", "install-003"]),
    ("What if the installer does not show up for the appointment?", ["install-002"]),
    ("How long is the warranty on a mattress?", ["warranty-001"]),
    ("How do I make a warranty claim?", ["warranty-002"]),
    ("Which payment methods do you accept?", ["billing-001"]),
    ("Can I give you my card number in the chat?", ["billing-002"]),
    ("How do I get a VAT invoice?", ["billing-003"]),
    ("What are the benefits of the VIP tier of the Contoso Home Club?", ["loyalty-001"]),
    ("How can I have my personal data deleted?", ["privacy-001"]),
    ("Do you record calls and chats?", ["privacy-002"]),
    ("My washing machine shows error E18", ["care-003"]),
    ("I can smell gas from my new oven", ["care-006"]),
    ("What are your opening hours?", ["service-001"]),
    ("Which carriers deliver for you?", ["delivery-008"]),
    ("Can I change the delivery address after dispatch?", ["delivery-007"]),
    ("Mein Sofa wurde beschädigt geliefert, was nun?", ["damage-002", "damage-001"]),
    ("How should I clean my fabric sofa?", ["care-001"]),
    ("Do you take back my old appliance when installing a new one?", ["service-005"]),
]
UNANSWERABLE: list[str] = [
    "What's the weather in Berlin tomorrow?",
    "Who won the football match yesterday?",
    "Can you recommend a good divorce lawyer?",
    "What is the capital of Australia?",
    "How do I cook risotto?",
    "Tell me a joke about cats",
    "What is the stock price of Microsoft today?",
    "Can you help me with my tax return?",
]
# (question, fabricated answer, expected ungrounded) - sources are the KB chunks retrieved for the question
FABRICATED: list[tuple[str, str, bool]] = [
    ("How long do I have to return an item?", "You can return any item within 90 days of delivery, no questions asked.", True),
    ("How long is the warranty on a mattress?", "Mattresses come with a lifetime warranty that also covers normal wear and tear.", True),
    ("When do I get my refund?", "Refunds are paid within 1 business day directly to your PayPal account.", True),
    ("How much does installing a washing machine cost?", "Washing machine installation is free of charge for all customers.", True),
    ("How long do I have to return an item?", "You can return most items within 30 days of delivery, free of charge.", False),
    ("How long is the warranty on a mattress?", "Mattresses carry a 36-month warranty from the delivery date.", False),
    ("What if the installer does not show up?", "You get priority rebooking within 48 hours and a goodwill credit of 30 EUR.", False),
]
