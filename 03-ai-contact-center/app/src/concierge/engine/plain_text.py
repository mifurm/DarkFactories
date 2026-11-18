"""Plain-language guard for the text an LLM writes for operators (hand-off note, wrap-up summary).

The prompts carry platform codes (`legal_threat`, `initiate_return`, `RESOLVED_REFUND_ISSUED`) and the model sometimes echoes them inside the prose
("... zapowiada podjęcie kroków prawnych (legal_threat)"). Polish prompts therefore get the localized words instead of the codes (`steps_for_prompt`), and
whatever still slips through is removed or replaced by its Polish phrase (`plain`). English is passed through untouched."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from ..core import i18n

# Triggers and risk flags as a short noun phrase inside a sentence (the full localized reasons are the catalog keys `trigger.<code>`)
TRIGGER_PL = {
    "legal_threat": "groźba kroków prawnych", "fraud_suspected": "podejrzenie oszustwa", "safety_issue": "problem z bezpieczeństwem produktu", "welfare_concern": "obawa o dobrostan klienta",
    "vulnerable_customer": "klient wymagający wsparcia", "explicit_request": "prośba o konsultanta", "policy_block": "blokada wynikająca z zasad", "sentiment": "negatywny nastrój klienta",
    "tool_failure": "powtarzające się błędy narzędzi", "loop": "rozmowa nie posuwa się naprzód", "knowledge_gap": "brak odpowiedzi w bazie wiedzy", "regulatory_complaint": "skarga do organu nadzoru",
    "takeover": "ręczne przejęcie rozmowy", "agent_decision": "decyzja asystenta", "churn_risk": "ryzyko utraty klienta",
}  # fmt: skip
# What a tool call is, as a noun phrase (the platform's tool names must never reach a Polish reader)
TOOL_PL = {
    "search_knowledge": "wyszukanie w bazie wiedzy", "start_verification": "wysłanie kodu weryfikacyjnego", "verify_otp": "weryfikacja kodem", "verify_kba": "weryfikacja pytaniami",
    "lookup_customer": "sprawdzenie danych klienta", "list_orders": "przegląd zamówień", "lookup_order": "sprawdzenie zamówienia", "track_shipment": "sprawdzenie przesyłki",
    "check_return_eligibility": "sprawdzenie możliwości zwrotu", "initiate_return": "rozpoczęcie zwrotu", "get_available_slots": "sprawdzenie wolnych terminów", "schedule_pickup": "zaplanowanie odbioru",
    "reschedule_delivery": "zmiana terminu dostawy", "update_address": "zmiana adresu dostawy", "issue_refund": "zwrot środków", "goodwill_credit": "bon rekompensacyjny",
    "warranty_claim": "zgłoszenie gwarancyjne", "create_ticket": "zgłoszenie", "update_ticket": "aktualizacja zgłoszenia", "send_confirmation": "wysłanie potwierdzenia",
    "request_payment": "link do bezpiecznej płatności", "escalate_to_human": "przekazanie konsultantowi", "end_conversation": "zakończenie rozmowy",
}  # fmt: skip
STATUS_PL = {"error": "nie powiodło się", "blocked": "zablokowane", "confirmation_required": "czeka na potwierdzenie klienta", "approval_required": "czeka na zatwierdzenie"}
ROLE_PL = {"customer": "klient", "agent_ai": "asystent AI", "agent_human": "konsultant"}


def role_label(role: str, lang: str) -> str:
    """The speaker of a transcript line in an LLM prompt (`agent_ai` is an internal code)."""
    return ROLE_PL.get(role, role) if lang == "pl" else role

_SNAKE = r"[a-z]+(?:_[a-z]+)+"  # legal_threat, initiate_return (letters only: ids such as cv_680c7e64eb or CH-100250 are not codes)
_UPPER = r"[A-Z]+(?:_[A-Z]+)+"  # RESOLVED_REFUND_ISSUED
_CODE = rf"(?:{_SNAKE}|{_UPPER})"
_PAREN = re.compile(rf"[ \t]*[(\[][ \t]*{_CODE}(?:[ \t]*[,;/][ \t]*{_CODE})*[ \t]*[)\]]")
_BARE = re.compile(rf"(?<![\w@/.:=-]){_CODE}(?![\w@/:=-]|\.\w)")


def _phrase(token: str) -> str:
    if token in TRIGGER_PL:
        return TRIGGER_PL[token]
    if token in TOOL_PL:
        return TOOL_PL[token]
    if token.islower() and i18n.has(f"intent.{token}"):
        return i18n.msg(f"intent.{token}", "pl")
    if token.isupper() and i18n.has(f"disposition.{token}"):
        return i18n.msg(f"disposition.{token}", "pl")
    return ""


def plain(text: str, lang: str) -> str:
    """Polish operator text without internal codes: a parenthesised code is dropped (the trigger is shown next to the note anyway), a bare known code becomes its Polish phrase,
    an unknown snake_case token is removed. Anything else - order numbers, ids, e-mail addresses, URLs - is untouched. Other languages are returned unchanged."""
    if lang != "pl" or not text:
        return text
    out = _PAREN.sub("", text)
    out = _BARE.sub(lambda m: _phrase(m.group(0)), out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"[ \t]+([,.;:!?])", r"\1", out)
    return out.strip()


def steps_for_prompt(steps: Iterable[dict[str, Any]], lang: str) -> str:
    """The steps already tried, for an LLM prompt: Polish prompts carry noun phrases and a plain status instead of `tool_name:status`."""
    if lang != "pl":
        return "; ".join(f"{s['tool']}:{s['status']}" for s in steps)
    parts = []
    for s in steps:
        phrase = TOOL_PL.get(s["tool"])
        if phrase:
            parts.append(f"{phrase} ({STATUS_PL[s['status']]})" if s["status"] in STATUS_PL else phrase)
    return "; ".join(parts)
