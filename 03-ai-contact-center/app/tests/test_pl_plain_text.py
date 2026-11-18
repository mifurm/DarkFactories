"""LLM-written Polish operator text never shows the platform's internal codes (found on the live app: "... zapowiada podjęcie kroków prawnych (legal_threat)").
Polish prompts carry words instead of codes, the answer is cleaned of any code that still slips through, and English prompts / output are untouched."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from concierge.core import i18n
from concierge.engine import handoff as handoff_mod
from concierge.engine import plain_text, wrapup

NOTE_WITH_CODES = "Klient skarży się na brak montażu pralki CH-100250 i zapowiada podjęcie kroków prawnych, asystent wykonał lookup_order (legal_threat)."


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("Klient zapowiada podjęcie kroków prawnych (legal_threat).", "Klient zapowiada podjęcie kroków prawnych."),
        ("Eskalacja [legal_threat, vulnerable_customer] do zespołu.", "Eskalacja do zespołu."),
        ("Asystent wykonał initiate_return i schedule_pickup.", "Asystent wykonał rozpoczęcie zwrotu i zaplanowanie odbioru."),
        ("Wynik: RESOLVED_REFUND_ISSUED.", f"Wynik: {i18n.msg('disposition.RESOLVED_REFUND_ISSUED', 'pl')}."),
        ("Powód: damaged_item, zamówienie CH-100350.", "Powód: uszkodzony towar, zamówienie CH-100350."),
        ("Przekazano z powodu unknown_internal_flag w rozmowie.", "Przekazano z powodu w rozmowie."),
        ("Bez żadnych kodów, tylko zwykły tekst – 1 599,00 zł.", "Bez żadnych kodów, tylko zwykły tekst – 1 599,00 zł."),
    ],
)
def test_internal_codes_are_removed_or_translated_in_polish_text(raw, clean):
    assert plain_text.plain(raw, "pl") == clean


def test_ids_addresses_and_links_are_not_mistaken_for_codes_and_english_is_untouched():
    keep = "Rozmowa cv_680c7e64eb, zamówienie CH-100250, e-mail anna_kowalska@example.com, link /agent?conversation=cv_680c7e64eb oraz ho_ab12cd34."
    assert plain_text.plain(keep, "pl") == keep
    english = "The customer threatens legal action (legal_threat) after lookup_order."
    assert plain_text.plain(english, "en") == english and plain_text.plain("", "pl") == ""


def test_prompt_helpers_speak_polish_to_the_model_and_leave_english_alone():
    steps = [{"tool": "lookup_order", "status": "ok"}, {"tool": "initiate_return", "status": "confirmation_required"}, {"tool": "issue_refund", "status": "error"}, {"tool": "made_up_tool", "status": "ok"}]
    assert plain_text.steps_for_prompt(steps, "pl") == "sprawdzenie zamówienia; rozpoczęcie zwrotu (czeka na potwierdzenie klienta); zwrot środków (nie powiodło się)"
    assert plain_text.steps_for_prompt(steps, "en") == "lookup_order:ok; initiate_return:confirmation_required; issue_refund:error; made_up_tool:ok"
    assert plain_text.role_label("agent_ai", "pl") == "asystent AI" and plain_text.role_label("agent_ai", "en") == "agent_ai"


def fake_llm(svc, monkeypatch, reply: dict) -> dict:
    seen: dict = {}

    async def chat(messages, **kwargs):
        seen["system"], seen["user"] = messages[0]["content"], messages[1]["content"]
        return SimpleNamespace(text=json.dumps(reply), cost_usd=0.0)

    monkeypatch.setattr(svc.llm, "deterministic", False, raising=False)
    monkeypatch.setattr(svc.llm, "chat", chat)
    return seen


async def legal_conversation(svc, language: str):
    conv = await svc.orchestrator.start(language=language, recording_consent="granted")
    conv.steps.append({"tool": "lookup_order", "status": "ok", "summary": "lookup order", "ts": 1.0})
    conv.add("customer", "To skandal, skieruję sprawę do sądu." if language == "pl" else "This is outrageous, I will take this to court.", lang=language)
    return conv


async def test_polish_handoff_note_prompt_carries_words_and_the_note_is_cleaned(svc, monkeypatch):
    seen = fake_llm(svc, monkeypatch, {"summary": NOTE_WITH_CODES, "suggested_resolution": "Przejrzyj historię zamówienia i zaoferuj rozwiązanie (legal_threat)."})
    conv = await legal_conversation(svc, "pl")
    ho = await handoff_mod.initiate(svc, conv, {"code": "legal_threat", "reason": i18n.msg("trigger.legal_threat", "en")}, notify=False)
    pkg = ho["package"]
    assert seen["user"].startswith("Powód eskalacji: Klient wspomniał o krokach prawnych lub organie ochrony konsumentów.\nPodjęte kroki: sprawdzenie zamówienia\nRozmowa:\n") and "\nklient: To skandal" in seen["user"]
    assert not any(code in seen["user"] for code in ("legal_threat", "lookup_order", "agent_ai")) and "Never write internal codes or identifiers" in seen["system"]
    assert pkg["summary_source"] == "llm" and pkg["summary"] == "Klient skarży się na brak montażu pralki CH-100250 i zapowiada podjęcie kroków prawnych, asystent wykonał sprawdzenie zamówienia."
    assert pkg["suggested_resolution"] == "Przejrzyj historię zamówienia i zaoferuj rozwiązanie."


async def test_english_handoff_note_prompt_and_output_are_unchanged(svc, monkeypatch):
    seen = fake_llm(svc, monkeypatch, {"summary": "The customer threatens legal action (legal_threat).", "suggested_resolution": "Acknowledge and review (legal_threat)."})
    conv = await legal_conversation(svc, "en")
    reason = i18n.msg("trigger.legal_threat", "en")
    ho = await handoff_mod.initiate(svc, conv, {"code": "legal_threat", "reason": reason}, notify=False)
    assert seen["user"].startswith(f"Escalation trigger: legal_threat ({reason}).\nSteps tried: lookup_order:ok\nConversation:\n") and "\ncustomer: This is outrageous" in seen["user"]
    assert "Never write internal codes" not in seen["system"]
    assert ho["package"]["summary"] == "The customer threatens legal action (legal_threat)." and ho["package"]["suggested_resolution"] == "Acknowledge and review (legal_threat)."


async def test_polish_wrapup_summary_is_cleaned_of_codes_and_english_is_untouched(svc, monkeypatch):
    summary = "Klientka zgłosiła uszkodzenie sofy w zamówieniu CH-100350 i poprosiła o zwrot; asystent wykonał initiate_return (RESOLVED_REFUND_ISSUED). Zwrot nastąpi po odbiorze."
    seen = fake_llm(svc, monkeypatch, {"summary": summary})
    conv = await legal_conversation(svc, "pl")
    wrap = await wrapup.generate_wrapup(svc, conv)
    assert wrap["summary_source"] == "llm" and "initiate_return" not in wrap["summary"] and "RESOLVED_" not in wrap["summary"].split(" Wynik:")[0]
    assert "asystent wykonał rozpoczęcie zwrotu." in wrap["summary"] and "never internal codes or identifiers" in seen["system"]
    assert "agent_ai" not in seen["user"] and "klient: To skandal" in seen["user"]

    english = await legal_conversation(svc, "en")
    seen_en = fake_llm(svc, monkeypatch, {"summary": "The customer asked for a refund; the assistant ran initiate_return (RESOLVED_REFUND_ISSUED) and agreed next steps."})
    en = await wrapup.generate_wrapup(svc, english)
    assert "initiate_return (RESOLVED_REFUND_ISSUED)" in en["summary"], "English output is not post-processed"
    assert "never internal codes" not in seen_en["system"] and "customer: This is outrageous" in seen_en["user"]
