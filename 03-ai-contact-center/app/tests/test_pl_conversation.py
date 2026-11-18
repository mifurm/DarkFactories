"""Polish conversations end to end (spec §5): AI disclosure + recording consent, tool confirmations in PLN, caps on the EUR-equivalent of PLN amounts
(boundaries, approval, idempotency), OTP SMS, wrap-up / disposition / CRM note, handoff / escalation and Agent Assist in Polish, the golden persona
(Anna Kowalska, Warszawa, damaged sofa) and the demo customers / orders of the Polish market (PLN, InPost / DPD Polska / DHL)."""

from __future__ import annotations

import asyncio
import re

from concierge.core import i18n
from concierge.core.money import FX_PER_EUR, to_eur
from concierge.engine import wrapup
from concierge.engine.guard import AI_DISCLOSURE, DISCLOSURE_MARKERS, RECORDING_CONSENT, RECORDING_MARKERS
from concierge.engine.tools import ToolContext
from conftest import otp_of, say

NBSP = "\u00a0"


def plain(text: str) -> str:
    """The text with ordinary spaces: customer-facing Polish prose carries no-break spaces after one-letter words and inside amounts."""
    return text.replace(NBSP, " ")

async def make_ctx(svc, customer="CU-1009", level=1, agent="resolution", actor="ai", approved=False, lang="pl"):
    conv = await svc.orchestrator.start(language=lang, recording_consent="granted")
    if customer:
        conv.identity.verified, conv.identity.level, conv.identity.customer_id, conv.identity.method = True, level, customer, "otp"
    return ToolContext(svc=svc, conv=conv, agent=agent, actor=actor, cfg=await svc.configs.active(), approved=approved)


async def call(ctx, name, **args):
    return await ctx.svc.tools.execute(ctx, name, args)


def confirm_all(ctx) -> None:
    for p in ctx.conv.pending:
        p.confirmed = True


async def start_refund_return(ctx, order_id: str) -> None:
    ctx.conv.entities["choice"] = "refund"
    assert (await call(ctx, "initiate_return", order_id=order_id, reason="damaged", resolution="refund")).status == "confirmation_required"
    confirm_all(ctx)
    assert (await call(ctx, "initiate_return", order_id=order_id, reason="damaged", resolution="refund")).status == "ok"


async def set_item_price(svc, order_id: str, price: float) -> None:
    o = await svc.repo.get("bo_orders", order_id)
    o["items"][0]["unit_price"] = price
    o["total"] = price
    await svc.repo.put("bo_orders", o)


# ------------------------------------------------------------------------------------------------------------------ demo data of the Polish market
async def test_polish_demo_customers_and_orders_are_in_pln_with_polish_carriers_and_addresses(svc):
    anna = await svc.repo.get("bo_customers", "CU-1009")
    assert (anna["name"], anna["language"], anna["market"]) == ("Anna Kowalska", "pl", "PL")
    assert anna["address"] == {"street": "ul. Marszałkowska 12/4", "postal_code": "00-001", "city": "Warszawa", "country": "PL"}
    order = await svc.repo.get("bo_orders", "CH-100350")
    assert order["currency"] == "PLN" and order["total"] == 1599.0 and order["carrier"] == "DPD Polska" and order["items"][0]["name"] == "Sofa 2-osobowa Nordby (szara)"
    assert order["payment"] == {"method": "card", "brand": "Mastercard", "last4": "2245"}
    orders = [o for o in await svc.repo.query("bo_orders") if o["customer_id"] in {"CU-1009", "CU-1010", "CU-1011", "CU-1012", "CU-1013"}]
    assert len(orders) == 8 and {o["currency"] for o in orders} == {"PLN"} and {o["carrier"] for o in orders} == {"InPost", "DPD Polska", "DHL"}
    cities = {(await svc.repo.get("bo_customers", c))["address"]["city"] for c in ("CU-1009", "CU-1010", "CU-1011", "CU-1012", "CU-1013")}
    assert cities == {"Warszawa", "Kraków", "Gdańsk", "Poznań", "Wrocław"}
    english = await svc.repo.get("bo_orders", "CH-100231")
    assert english.get("currency") in (None, "EUR") and english["total"] == 379.0, "the English demo data is untouched"


async def test_back_office_seed_upgrades_an_already_seeded_repository_without_wiping_it(svc):
    """The deployed Cosmos DB was seeded before the Polish personas existed: re-seeding must add them (upsert) and keep everything else."""
    for coll, ids in (("bo_customers", ["CU-1009", "CU-1010", "CU-1011", "CU-1012", "CU-1013"]), ("bo_orders", ["CH-100350", "CH-100351", "CH-100352", "CH-100360", "CH-100370", "CH-100371", "CH-100380", "CH-100390"])):
        for i in ids:
            await svc.repo.delete(coll, i)
    before = len(await svc.repo.query("bo_orders"))
    german = await svc.repo.get("bo_customers", "CU-1001")
    assert await svc.repo.get("bo_customers", "CU-1009") is None
    counts = await svc.backoffice.seed()  # `existing and not force`: the upgrade path
    assert counts.get("bo_customers") == 5 and await svc.repo.get("bo_customers", "CU-1009") and await svc.repo.get("bo_orders", "CH-100350")
    assert len(await svc.repo.query("bo_orders")) == before + 8 - 0 and await svc.repo.get("bo_customers", "CU-1001") == german
    again = await svc.backoffice.seed()
    assert again == {"skipped": 1}, "a second run changes nothing"


async def test_the_polish_warranty_persona_of_the_original_seed_buys_in_pln(svc):
    o = await svc.repo.get("bo_orders", "CH-100300")
    assert o["currency"] == "PLN" and all(i["unit_price"] > 100 for i in o["items"]) and o["total"] == sum(i["unit_price"] * i["qty"] for i in o["items"])


# ------------------------------------------------------------------------------------------------------------------ disclosure, consent, greeting
async def test_polish_chat_opens_with_the_ai_disclosure_and_the_recording_notice_in_polish(svc):
    conv = await svc.orchestrator.start(language="pl", recording_consent="granted")
    first = conv.messages[0]
    assert first.role == "agent_ai" and "disclosure" in first.flags and first.text == AI_DISCLOSURE["pl"]
    assert DISCLOSURE_MARKERS.search(first.text) and RECORDING_MARKERS.search(first.text) and "RODO" in first.text and "konsultant" in first.text
    assert not re.search(r"\b(the|and|recorded|assistant)\b", first.text), "no English in the Polish disclosure"
    assert "AI" in RECORDING_CONSENT["pl"] or "nagryw" in RECORDING_CONSENT["pl"]
    assert RECORDING_MARKERS.search(RECORDING_CONSENT["pl"]) and "Państwa" in RECORDING_CONSENT["pl"]


def test_every_language_disclosure_is_recognised_by_the_marker_regex_so_the_voice_relay_never_repeats_it_needlessly():
    from concierge.engine.guard import AI_DISCLOSURE as ALL

    assert {lang for lang, text in ALL.items() if not DISCLOSURE_MARKERS.search(text)} == set(), "the relay compares the spoken greeting with these markers"


async def test_the_pl_disclosure_is_recognised_by_the_compliance_checks_for_pl_and_en_alike(svc):
    from concierge.engine.guard import find_risky_promises

    assert DISCLOSURE_MARKERS.search("Jestem wirtualnym asystentem Contoso Home.") and DISCLOSURE_MARKERS.search("Rozmawia Pan z chatbotem.") and DISCLOSURE_MARKERS.search("I am an AI assistant")
    assert not DISCLOSURE_MARKERS.search("Dzień dobry, w czym mogę pomóc?")
    assert find_risky_promises("Dzień dobry, w czym mogę pomóc?") == []


async def test_polish_voice_call_from_a_polish_number_gets_the_consent_prompt_in_polish(svc):
    from concierge.features.voice.telephony import CallMachine, TelephonyEvent

    m = CallMachine("call-pl", media_url="wss://x/ws", provider="sip")
    m.on(TelephonyEvent("incoming_call", "call-pl", {"from": "+48 600 123 456"}))
    acts = m.on(TelephonyEvent("call_connected", "call-pl", {}))
    play = next(a for a in acts if a.kind == "play")
    assert play.params["language"] == "pl" and "nagrywan" in play.params["prompt"] and "RODO" in play.params["prompt"] and "nacisnąć 1" in play.params["prompt"]
    en = CallMachine("call-en", media_url="wss://x/ws", provider="sip")
    en.on(TelephonyEvent("incoming_call", "call-en", {"from": "+4915550001234"}))
    play_en = next(a for a in en.on(TelephonyEvent("call_connected", "call-en", {})) if a.kind == "play")
    assert play_en.params["prompt"] == "AI disclosure + recording consent: press 1 to accept, 2 to decline" and "language" not in play_en.params


# ------------------------------------------------------------------------------------------------------------------ OTP SMS
async def test_otp_sms_is_polish_and_formal_in_a_polish_conversation_english_otherwise(svc):
    ctx = await make_ctx(svc, customer=None, agent="authentication")
    r = await call(ctx, "start_verification", identifier="CH-100350")
    assert r.status == "ok" and r.data["status"] == "challenge_sent"
    sms = next(o for o in ctx.conv.outbox if o["kind"] == "otp")
    assert re.fullmatch(r"Contoso Home: kod weryfikacyjny to \d{6}\. Wygasa za 5 min\. Prosimy nie udostępniać go nikomu\.", sms["body"]) and sms["simulated"]
    en = await make_ctx(svc, customer=None, agent="authentication", lang="en")
    await call(en, "start_verification", identifier="CH-100231")
    assert re.fullmatch(r"Contoso Home: your verification code is \d{6}\. It expires in 5 minutes\. Never share it with anyone\.", next(o for o in en.conv.outbox if o["kind"] == "otp")["body"])


# ------------------------------------------------------------------------------------------------------------------ confirmations in PLN
async def test_refund_confirmation_is_read_back_in_polish_with_the_amount_in_zloty_and_the_card(svc):
    ctx = await make_ctx(svc)
    await start_refund_return(ctx, "CH-100350")
    plan = await call(ctx, "issue_refund", order_id="CH-100350", amount=1599.0, reason="uszkodzenie towaru")
    assert plan.status == "confirmation_required"
    summary = ctx.conv.pending[-1].summary
    assert f"zwrot środków w{NBSP}wysokości 1{NBSP}599,00{NBSP}zł" in summary and "Mastercard kończącą się na 2245" in summary and "5–7 dni roboczych" in summary
    assert summary.startswith("Zarejestruję zwrot środków"), "a formal first-person sentence, not an infinitive"
    assert "EUR" not in summary and "refund" not in summary.lower()
    done = (confirm_all(ctx), await call(ctx, "issue_refund", order_id="CH-100350", amount=1599.0, reason="uszkodzenie towaru"))[1]
    assert done.status == "ok" and done.data["amount"] == 1599.0 and done.data["currency"] == "PLN" and "amount_eur" not in done.data, "a PLN amount is never published under an `_eur` key"
    rf = (await svc.backoffice.refunds_for("CH-100350"))[0]
    assert rf["currency"] == "PLN" and rf["amount"] == 1599.0 and rf["status"] == "issued"


async def test_english_refund_keeps_its_historic_eur_result_keys_and_wording(svc):
    ctx = await make_ctx(svc, customer="CU-1001", lang="en")
    await start_refund_return(ctx, "CH-100231")
    plan = await call(ctx, "issue_refund", order_id="CH-100231", amount=379.0, reason="damaged on delivery")
    assert plan.status == "confirmation_required" and ctx.conv.pending[-1].summary.startswith("Refund EUR 379.00 for ")
    confirm_all(ctx)
    done = await call(ctx, "issue_refund", order_id="CH-100231", amount=379.0, reason="damaged on delivery")
    assert done.data["amount_eur"] == 379.0 and "currency" not in done.data


async def test_other_confirmations_are_polish_too_pickup_reschedule_address_goodwill_warranty(svc):
    ctx = await make_ctx(svc, customer="CU-1011", level=2)
    slots = (await call(ctx, "get_available_slots", kind="delivery", order_id="CH-100371")).data["slots"]
    r = await call(ctx, "reschedule_delivery", order_id="CH-100371", slot_id=slots[0]["slot_id"])
    assert r.status == "confirmation_required"
    assert re.fullmatch(r"Przeniosę dostawę zamówienia CH-100371 na [a-zęó]+ \d\d\.\d\d\.\d{4}, w godzinach \d\d:\d\d–\d\d:\d\d; zmiana jest bezpłatna\.", plain(ctx.conv.pending[-1].summary))
    r = await call(ctx, "update_address", order_id="CH-100371", street="ul. Długa 5/12", postal_code="80-001", city="Gdańsk")
    assert r.status == "confirmation_required" and plain(ctx.conv.pending[-1].summary) == "Zmienię adres dostawy zamówienia CH-100371 na: ul. Długa 5/12, 80-001 Gdańsk."
    gw = await make_ctx(svc, customer="CU-1012")
    assert (await call(gw, "goodwill_credit", order_id="CH-100380", amount=150.0, reason="opóźniona dostawa")).status == "confirmation_required"
    assert plain(gw.conv.pending[-1].summary) == "Dodam do konta Contoso Home bon rekompensacyjny w wysokości 150,00 zł (ważny 12 miesięcy, nie podlega wymianie na gotówkę)." and f"150,00{NBSP}zł" in gw.conv.pending[-1].summary
    wc = await make_ctx(svc, customer="CU-1007")
    assert (await call(wc, "warranty_claim", order_id="CH-100300", description="blender przestał działać")).status == "confirmation_required"
    assert plain(wc.conv.pending[-1].summary) == "Zarejestruję reklamację towaru „Blender Mixo Pro” (zamówienie CH-100300); opis usterki: „blender przestał działać”."


def test_slot_phrases_use_the_accusative_after_na_the_nominative_after_a_colon_and_an_en_dash_window():
    from concierge.engine import plan_text

    slot = {"date": "2026-11-18", "window": "09:00-13:00", "weekday": "Wednesday"}  # a Wednesday: `środa` -> `na środę`
    assert plain(plan_text.reschedule_plan("pl", order="CH-100371", slot=slot)) == "Przeniosę dostawę zamówienia CH-100371 na środę 18.11.2026, w godzinach 09:00–13:00; zmiana jest bezpłatna."
    assert plain(plan_text.pickup_plan("pl", slot=slot, city="Warszawa")) == "Zarezerwuję bezpłatny odbiór towaru z adresu dostawy (Warszawa): środa 18.11.2026, w godzinach 09:00–13:00."
    assert plan_text.reschedule_plan("en", order="CH-100371", slot=slot) == "Move the delivery of order CH-100371 to Wednesday 2026-11-18 between 09:00-13:00 (free of charge)."
    assert i18n.slot_when("2026-11-21", "08:00-12:00", "pl", accusative=True) == "sobotę 21.11.2026, w godzinach 08:00–12:00"


def test_done_text_turns_a_plan_sentence_into_the_record_of_what_was_done():
    from concierge.engine import plan_text

    plan = "Zlecę zwrot towaru „Sofa” z zamówienia CH-100350 (powód: uszkodzenie towaru); odbiór towaru będzie bezpłatny."
    assert plan_text.done_text("pl", plan) == "zlecono zwrot towaru „Sofa” z zamówienia CH-100350 (powód: uszkodzenie towaru); odbiór towaru będzie bezpłatny"
    assert plan_text.done_text("pl", "Zarezerwuję bezpłatny odbiór towaru.", capitalize=True) == "Zarezerwowano bezpłatny odbiór towaru"
    assert plan_text.done_text("pl", "Zlecić zwrot towaru.") == "Zlecić zwrot towaru.", "a summary stored by an older version is left alone"
    assert plan_text.done_text("en", "Start a return for 'Sofa'.") == "Start a return for 'Sofa'."


def test_the_polish_warranty_description_is_the_customers_own_words_not_the_one_time_code_message():
    from concierge.engine.stub_brain import _issue_text

    messages = [
        {"role": "system", "content": "prompt"},
        {"role": "user", "content": "Mój blender z zamówienia CH-100300 przestał działać, chcę skorzystać z gwarancji."},
        {"role": "assistant", "content": "Proszę podać kod."},
        {"role": "user", "content": "Mój kod to 015753"},
    ]
    assert _issue_text(messages) == "Mój blender z zamówienia CH-100300 przestał działać, chcę skorzystać z gwarancji."
    assert _issue_text(messages[:1]) == ""


async def test_a_rescheduled_polish_delivery_leaves_a_polish_carrier_note(svc):
    ctx = await make_ctx(svc, customer="CU-1011", level=2)
    slots = (await call(ctx, "get_available_slots", kind="delivery", order_id="CH-100371")).data["slots"]
    assert (await call(ctx, "reschedule_delivery", order_id="CH-100371", slot_id=slots[0]["slot_id"])).status == "confirmation_required"
    confirm_all(ctx)
    assert (await call(ctx, "reschedule_delivery", order_id="CH-100371", slot_id=slots[0]["slot_id"])).status == "ok"
    event = (await svc.backoffice.shipment("CH-100371"))["events"][-1]
    assert re.fullmatch(r"Nowy termin dostawy: \d\d\.\d\d\.\d{4}, \d\d:\d\d–\d\d:\d\d", event["note"]) and event["location"] == "Obsługa klienta", "a Polish order never gets an English note in the tracking"
    english = await make_ctx(svc, customer="CU-1001", lang="en")
    eslots = (await call(english, "get_available_slots", kind="delivery", order_id="CH-100232")).data["slots"]
    await call(english, "reschedule_delivery", order_id="CH-100232", slot_id=eslots[0]["slot_id"])
    confirm_all(english)
    await call(english, "reschedule_delivery", order_id="CH-100232", slot_id=eslots[0]["slot_id"])
    assert (await svc.backoffice.shipment("CH-100232"))["events"][-1]["note"].startswith("New delivery slot ")


async def test_a_polish_conversation_keeps_the_offered_slot_ids_in_the_prompt_until_a_booking_happens(svc):
    from concierge.engine.models import ToolRecord
    from concierge.engine.prompts import build_system_prompt

    ctx = await make_ctx(svc, customer="CU-1011", level=2)
    offered = await call(ctx, "get_available_slots", kind="delivery", order_id="CH-100371")
    ctx.conv.add("agent_ai", "Proszę wybrać termin dostawy.", lang="pl", tools=[offered.record])
    notes = (await svc.orchestrator._extras(ctx.conv, None))["notes"]
    first = offered.data["slots"][0]
    slot_note = next(n for n in notes if n.startswith("SLOTS OFFERED"))
    assert f"{first['slot_id']} = {first['date']} {first['window']}" in slot_note and "do not escalate" in slot_note
    assert "SLOTS OFFERED" in build_system_prompt(await svc.configs.active(), ctx.conv, "resolution", extras={"notes": notes})
    ctx.conv.add("agent_ai", "Zmieniłem termin.", lang="pl", tools=[ToolRecord(id="t1", name="reschedule_delivery", status="ok")])
    assert not any(n.startswith("SLOTS OFFERED") for n in (await svc.orchestrator._extras(ctx.conv, None))["notes"]), "nothing to offer once the booking is done"
    ctx.conv.language = "en"
    ctx.conv.messages.pop()
    assert not any(n.startswith("SLOTS OFFERED") for n in (await svc.orchestrator._extras(ctx.conv, None))["notes"]), "English prompts are unchanged"


# ------------------------------------------------------------------------------------------------------------------ caps on the EUR-equivalent
def test_the_fixed_demo_rate_is_documented_in_one_place_and_consistent():
    assert FX_PER_EUR["PLN"] == 4.30 and FX_PER_EUR["EUR"] == 1.0
    assert round(to_eur(2150.0, "PLN"), 4) == 500.0, "the autonomous refund cap of EUR 500 is exactly 2 150,00 zł"
    assert round(to_eur(1720.0, "PLN"), 4) == 400.0, "the step-up threshold of EUR 400 is exactly 1 720,00 zł"
    assert round(to_eur(215.0, "PLN"), 4) == 50.0, "the autonomous goodwill cap of EUR 50 is exactly 215,00 zł"


async def test_refund_exactly_at_the_cap_is_autonomous_one_grosz_above_needs_a_specialist(svc):
    for price, expected in ((2150.0, "ok"), (2150.01, "approval_required")):
        await set_item_price(svc, "CH-100350", price)
        ctx = await make_ctx(svc, level=2)  # above EUR 400 the refund also needs step-up (L2), which the customer passed here
        await start_refund_return(ctx, "CH-100350")
        r = await call(ctx, "issue_refund", order_id="CH-100350", amount=price, reason="uszkodzenie")
        if expected == "ok":
            assert r.status == "confirmation_required"
            confirm_all(ctx)
            r = await call(ctx, "issue_refund", order_id="CH-100350", amount=price, reason="uszkodzenie")
        assert r.status == expected, (price, r.status, r.data)
        for rf in await svc.backoffice.refunds_for("CH-100350"):
            await svc.repo.delete("bo_refunds", rf["id"])
        for ret in await svc.backoffice.returns_for("CH-100350"):
            await svc.repo.delete("bo_returns", ret["id"])


async def test_pln_refund_above_the_cap_creates_an_approval_in_pln_with_its_eur_equivalent_and_a_polish_handoff_reason(svc):
    ctx = await make_ctx(svc, customer="CU-1010", level=2)
    await start_refund_return(ctx, "CH-100360")
    r = await call(ctx, "issue_refund", order_id="CH-100360", amount=3849.0, reason="uszkodzenie materaca")
    assert r.status == "approval_required" and r.escalate["code"] == "policy_block"
    assert await svc.backoffice.refunds_for("CH-100360") == [], "nothing is paid before the specialist decides"
    appr = (await svc.repo.query("approvals"))[0]
    assert (appr["amount"], appr["currency"], appr["amount_eur"], appr["status"]) == (3849.0, "PLN", 895.12, "pending")
    from concierge.engine.localize import trigger_reason

    reason = trigger_reason("policy_block", r.escalate["reason"], "pl")
    assert reason.startswith("zwrot środków w wysokości 3\u00a0849,00\u00a0zł przekracza limit — zatwierdzenie APR-") and "refund" not in reason
    from concierge.engine import handoff as handoff_mod

    pkg = await handoff_mod.initiate(svc, ctx.conv, {"code": "policy_block", "reason": r.escalate["reason"]}, notify=False)
    approvals = pkg["package"]["pending_approvals"]
    assert [(a["amount"], a["currency"]) for a in approvals] == [(3849.0, "PLN")], "the agent console shows the approval in the currency of the order"


async def test_a_refund_above_the_step_up_amount_needs_level_2_in_pln_too(svc):
    ctx = await make_ctx(svc, customer="CU-1010", level=1)
    await start_refund_return(ctx, "CH-100360")
    r = await call(ctx, "issue_refund", order_id="CH-100360", amount=3849.0, reason="uszkodzenie")
    assert r.status == "blocked" and r.data["error"] == "step_up_required" and r.data["required_level"] == 2
    small = await make_ctx(svc, customer="CU-1009", level=1)  # 1 599 zł = EUR 371.86 <= 400: L1 is enough
    await start_refund_return(small, "CH-100350")
    assert (await call(small, "issue_refund", order_id="CH-100350", amount=1599.0, reason="uszkodzenie")).status == "confirmation_required"


async def test_the_refund_can_never_exceed_the_item_value_and_must_be_in_the_orders_currency(svc):
    ctx = await make_ctx(svc)
    await start_refund_return(ctx, "CH-100350")
    r = await call(ctx, "issue_refund", order_id="CH-100350", amount=1600.0, reason="uszkodzenie")
    assert r.status == "error" and r.data["error"] == "refund_exceeds_order_value" and r.data["message"] == "Refunds for this order would exceed the order value (PLN 1599.00)."
    r = await call(ctx, "issue_refund", order_id="CH-100350", amount=371.86, reason="the EUR amount typed into a PLN order")
    assert r.status == "confirmation_required", "a smaller amount is accepted (partial refund) - and it is booked in PLN, not EUR"
    confirm_all(ctx)
    done = await call(ctx, "issue_refund", order_id="CH-100350", amount=371.86, reason="częściowy zwrot")
    assert done.data["currency"] == "PLN" and done.data["amount"] == 371.86


async def test_goodwill_caps_use_the_eur_equivalent_of_pln_per_credit_and_over_90_days(svc):
    ctx = await make_ctx(svc, customer="CU-1012")
    assert (await call(ctx, "goodwill_credit", order_id="CH-100380", amount=215.0, reason="opóźniona dostawa")).status == "confirmation_required", "EUR 50.00 exactly is within the cap"
    over = await call(ctx, "goodwill_credit", order_id="CH-100380", amount=216.0, reason="opóźniona dostawa")
    assert over.status == "approval_required", "EUR 50.23 is above the autonomous goodwill cap"
    ctx2 = await make_ctx(svc, customer="CU-1012")
    for amount in (200.0, 201.0):  # (a request that differs only in its free-text reason is the SAME action: its fingerprint ignores the reason)
        assert (await call(ctx2, "goodwill_credit", order_id="CH-100380", amount=amount, reason="opóźniona dostawa")).status == "confirmation_required"
        confirm_all(ctx2)
        assert (await call(ctx2, "goodwill_credit", order_id="CH-100380", amount=amount, reason="opóźniona dostawa")).status == "ok"
    third = await call(ctx2, "goodwill_credit", order_id="CH-100380", amount=202.0, reason="opóźniona dostawa")
    assert third.status == "approval_required", "200 + 201 + 202 zł = EUR 140.00 exceeds the 90-day limit of EUR 100"
    credits = await svc.backoffice.credits_for("CU-1012", 0)
    assert len(credits) == 2 and {c["currency"] for c in credits} == {"PLN"}


async def test_idempotent_retries_never_double_refund_or_double_credit_in_pln_even_when_concurrent(svc):
    ctx = await make_ctx(svc, customer="CU-1012")
    args = {"order_id": "CH-100380", "amount": 100.0, "reason": "opóźniona dostawa", "idempotency_key": "pl-retry-1"}
    assert (await call(ctx, "goodwill_credit", **args)).status == "confirmation_required"
    confirm_all(ctx)
    results = await asyncio.gather(*(call(ctx, "goodwill_credit", **args) for _ in range(5)))
    assert sorted(r.status for r in results).count("ok") == 1 and {r.status for r in results} <= {"ok", "replayed"}
    assert len(await svc.backoffice.credits_for("CU-1012", 0)) == 1 and all(r.data["currency"] == "PLN" and r.data["amount"] == 100.0 for r in results)

    rf = await make_ctx(svc)
    await start_refund_return(rf, "CH-100350")
    rargs = {"order_id": "CH-100350", "amount": 1599.0, "reason": "uszkodzenie", "idempotency_key": "pl-refund-1"}
    assert (await call(rf, "issue_refund", **rargs)).status == "confirmation_required"
    confirm_all(rf)
    runs = await asyncio.gather(*(call(rf, "issue_refund", **rargs) for _ in range(4)))
    assert sorted(r.status for r in runs).count("ok") == 1
    assert len(await svc.backoffice.refunds_for("CH-100350")) == 1


async def test_cross_customer_access_to_polish_orders_is_rejected(svc):
    ctx = await make_ctx(svc, customer="CU-1010")  # Tomasz asks about Anna's order
    r = await call(ctx, "lookup_order", order_id="CH-100350")
    ghost = await call(ctx, "lookup_order", order_id="CH-999999")
    assert r.status == "blocked" and r.data == ghost.data


async def test_order_lookup_shows_pln_amounts_under_plain_keys_and_a_currency(svc):
    ctx = await make_ctx(svc)
    data = (await call(ctx, "lookup_order", order_id="CH-100350")).data
    assert data["total"] == 1599.0 and data["currency"] == "PLN" and "total_eur" not in data
    assert data["items"][0]["unit_price"] == 1599.0 and "unit_price_eur" not in data["items"][0] and data["carrier"] == "DPD Polska" and data["delivery_city"] == "Warszawa"


# ------------------------------------------------------------------------------------------------------------------ the golden journey in Polish
async def golden_journey(svc, lang="pl") -> str:
    conv = await svc.orchestrator.start(channel="web_chat", language=lang, recording_consent="granted")
    await say(svc, conv.id, "Dzień dobry, moja kanapa dotarła uszkodzona. Numer zamówienia CH-100350.")
    c = await svc.store.get(conv.id)
    await say(svc, conv.id, f"Kod to {otp_of(c)}")
    await say(svc, conv.id, "Poproszę o zwrot pieniędzy.")
    await say(svc, conv.id, "Tak, proszę.")
    await say(svc, conv.id, "Dziękuję, to wszystko.")
    return conv.id


async def test_anna_kowalska_damaged_sofa_golden_journey_resolves_in_polish_with_a_confirmed_refund_in_pln(svc):
    cid = await golden_journey(svc)
    c = await svc.store.get(cid)
    agent_texts = [m.text for m in c.messages if m.role == "agent_ai"]
    assert c.status == "resolved" and c.handler == "ai" and c.handoff is None and c.language == "pl"
    plan_text = next(t for t in agent_texts if "Czy mam to zrealizować?" in t)
    assert f"1{NBSP}599,00{NBSP}zł" in plan_text and "Mastercard kończącą się na 2245" in plan_text, "the refund is read back (amount, card) before it is executed"
    assert "ze zwrotem środków" in plan_text
    spoken = plain(plan_text)
    assert spoken.startswith("Zlecę zwrot towaru „") and "Zarezerwuję bezpłatny odbiór towaru z adresu dostawy (Warszawa): " in spoken, "one short formal sentence per action"
    assert not re.search(r"\b(Zlecić|Zarezerwować)\b|Oto plan|odbiór lub termin", plan_text), "no infinitive list inside a formal sentence"
    assert spoken.endswith("Czy mam to zrealizować?")
    refunds = await svc.backoffice.refunds_for("CH-100350")
    assert len(refunds) == 1 and refunds[0]["amount"] == 1599.0 and refunds[0]["currency"] == "PLN" and refunds[0]["status"] == "issued"
    done = next(t for t in agent_texts if "Gotowe" in t)
    assert f"1{NBSP}599,00{NBSP}zł" in done and "dni roboczych" in done and "business" not in done
    assert "Zarezerwowano bezpłatny odbiór towaru: " in plain(done) and "odbiór lub termin" not in done, "the booking names what was booked"
    assert not [t for t in agent_texts if re.search(r"\b(the|your|refund|pickup|please)\b", t)], "no English sentence leaks into the Polish conversation"
    assert "disclosure" in c.messages[0].flags
    confirmation_mail = next(o for o in c.outbox if o["kind"] == "confirmation")
    mail = plain(confirmation_mail["body"])
    assert mail.startswith("Dzień dobry,\npotwierdzamy Państwa zgłoszenie w Contoso Home:\n- Zlecono zwrot towaru „") and "Numer referencyjny:" in mail
    assert "\n- Zarezerwowano bezpłatny odbiór towaru z adresu dostawy (Warszawa): " in mail and "\n- Zarejestrowano zwrot środków w wysokości 1 599,00 zł" in mail, "the e-mail lists what was done, not an infinitive to-do list"
    assert not re.search(r"\n- (Zlecić|Zarezerwować|Zlecę|Zarezerwuję|Zarejestruję)", mail) and mail.endswith("Z poważaniem\nZespół obsługi klienta Contoso Home")
    steps = {s["tool"] for s in c.steps if s["status"] == "ok"}
    assert {"verify_otp", "initiate_return", "schedule_pickup", "issue_refund"} <= steps


async def test_wrapup_disposition_crm_note_and_follow_ups_are_polish_for_a_polish_conversation(svc):
    cid = await golden_journey(svc)
    c = await svc.store.get(cid)
    w = c.wrapup or await wrapup.generate_wrapup(svc, c)
    assert w["disposition"] == "RESOLVED_REFUND_ISSUED" and w["lang"] == "pl" and w["disposition_label"] == "Rozwiązano — zwrot środków zrealizowany"
    assert w["summary"].startswith("Kontakt: Anna, kanał: czat internetowy, język: PL, sprawa: uszkodzony towar (zamówienie CH-100350).")
    assert "zł (wypłata w ciągu 5–7 dni roboczych od odbioru towaru)" in plain(w["summary"]) and f"1{NBSP}599,00{NBSP}zł" in w["summary"] and "business days" not in w["summary"]
    assert "Wykonane działania: zlecono zwrot towaru „" in plain(w["summary"]) and "; zarezerwowano bezpłatny odbiór towaru" in w["summary"], "the actions read as a record of what was done"
    assert not re.search(r"Zlecić|Zarezerwować|\.;|\.\.", w["summary"]), "no infinitive plans and no `.;` / `..` joins in the summary"
    assert w["crm_note"].startswith("[Automatyczne podsumowanie Concierge ") and w["crm_note"].endswith("Kod wyniku rozmowy: RESOLVED_REFUND_ISSUED.")
    assert [t["title"] for t in w["follow_up_tasks"]] == ["Potwierdzić odbiór towaru i jego przyjęcie w magazynie", "Sprawdzić, czy zwrot środków został wypłacony po zeskanowaniu towaru przy odbiorze (5–7 dni roboczych)"]
    assert [t["code"] for t in w["follow_up_tasks"]] == ["confirm_pickup", "verify_refund"], "stable codes next to the localized titles"


async def test_wrapup_is_re_rendered_in_the_request_locale_without_touching_the_stored_record(svc):
    cid = await golden_journey(svc)
    c = await svc.store.get(cid)
    w = c.wrapup or await wrapup.generate_wrapup(svc, c)
    en = wrapup.localize_wrapup(w, c, "en")
    assert en["disposition_label"] == "Resolved - refund issued" and en["summary"].startswith("Anna contacted us via web chat (PL) about damaged item (order CH-100350).")
    assert en["follow_up_tasks"][0]["title"] == "Confirm pickup was completed and item scanned at warehouse"
    pl = wrapup.localize_wrapup(en, c, "pl")
    assert pl["summary"].startswith("Kontakt: Anna") and w["lang"] == "pl", "the stored wrap-up keeps the conversation language"
    submitted = wrapup.localize_wrapup({**w, "edited_by": "agent1", "summary": "Własne podsumowanie konsultanta."}, c, "en")
    assert submitted["summary"] == "Własne podsumowanie konsultanta.", "a text a human wrote is never overwritten by a re-rendered one"


async def test_english_wrapup_is_unchanged_and_names_the_first_real_intent_not_the_goodbye(svc):
    conv = await svc.orchestrator.start(language="en", recording_consent="granted")
    await say(svc, conv.id, "Hello, my sofa arrived damaged, order CH-100231.")
    await say(svc, conv.id, f"The code is {otp_of(await svc.store.get(conv.id))}")
    await say(svc, conv.id, "Refund please.")
    await say(svc, conv.id, "Yes, please do.")
    await say(svc, conv.id, "No thanks, that's all.")
    c = await svc.store.get(conv.id)
    w = c.wrapup or await wrapup.generate_wrapup(svc, c)
    assert "about damaged item (order CH-100231)." in w["summary"] and w["disposition_label"] == "Resolved - refund issued"
    assert "Refund of EUR 379.00 issued (5-7 business days after the item is collected)." in w["summary"]


# ------------------------------------------------------------------------------------------------------------------ handoff, escalation, Agent Assist
async def legal_threat_conversation(svc):
    conv = await svc.orchestrator.start(channel="web_chat", language="pl", recording_consent="granted")
    await say(svc, conv.id, "To skandal! Sprawa zamówienia CH-100390 ciągnie się od tygodni. Jeśli sprawa nie zostanie załatwiona, skieruję ją do sądu i zgłoszę do UOKiK.")
    return await svc.store.get(conv.id)


async def test_legal_threat_in_polish_is_a_warm_handoff_to_escalations_with_polish_notice_and_package(svc):
    c = await legal_threat_conversation(svc)
    assert c.status == "waiting_human" and c.queue == "escalations" and c.handoff["trigger"]["code"] == "legal_threat" and c.handoff["package"]["completeness"] >= 80
    notice = next(m.text for m in c.messages if "handoff_notice" in m.flags)
    assert plain(notice).startswith("Łączę z konsultantem, który widzi już naszą rozmowę, więc nie trzeba niczego powtarzać.") and "Szacowany czas oczekiwania" in notice
    pkg = c.handoff["package"]
    assert pkg["text_lang"] == "pl" and pkg["summary_source"] == "extractive"
    assert pkg["summary"].startswith("Kontakt: klient niezweryfikowany, kanał: czat internetowy, język: PL, sprawa: skarga.") and "Tożsamość: niezweryfikowana." in pkg["summary"]
    assert "UOKiK.” Dotyczy zamówienia CH-100390." in pkg["summary"] and ".”." not in pkg["summary"], "a quoted sentence ends with its own punctuation: no `.”.`"
    assert pkg["suggested_resolution"] == i18n.msg("ho.suggested.legal_threat", "pl") and pkg["suggested_resolution"].startswith("Okaż zrozumienie dla frustracji i powagi skargi")
    assert not re.search(r"\b(the|customer|order|please|acknowledge)\b", pkg["summary"] + pkg["suggested_resolution"], re.IGNORECASE), "the package is written in Polish, no English mixed in"
    assert c.handoff["trigger"]["reason"] == i18n.msg("trigger.legal_threat", "en"), "the stored trigger keeps the original text; the API renders it per request locale"


async def test_handoff_api_renders_trigger_queue_and_summary_in_the_request_locale_and_keeps_codes_stable(svc):
    from fastapi.testclient import TestClient

    from concierge.core.config import Settings
    from concierge.main import create_app

    with TestClient(create_app(Settings(mode="offline", rate_limit_ip_per_min=100000, rate_limit_ai_ip_per_min=100000, rate_limit_global_per_min=100000))) as client:
        cust, staff = {"X-Demo-Role": "customer"}, {"X-Demo-Role": "admin"}
        sid = client.post("/api/chat/sessions", json={"language": "pl", "recording_consent": "granted"}, headers=cust).json()["session"]["id"]
        client.post(f"/api/chat/sessions/{sid}/messages", json={"text": "To skandal! Skieruję sprawę do sądu i zgłoszę ją do UOKiK, zamówienie CH-100390."}, headers=cust)
        pl = client.get("/api/handoff/queue", headers={**staff, "X-UI-Lang": "pl"}).json()
        en = client.get("/api/handoff/queue?lang=en", headers={**staff, "X-UI-Lang": "pl"}).json()
        item_pl, item_en = next(i for i in pl if i["conversation_id"] == sid), next(i for i in en if i["conversation_id"] == sid)
        assert item_pl["queue"] == item_en["queue"] == "escalations" and item_pl["trigger"]["code"] == item_en["trigger"]["code"] == "legal_threat"
        assert item_pl["queue_name"] == "Eskalacje i sprawy prawne" and item_en["queue_name"] == "Escalations & legal"
        assert item_pl["trigger"]["reason"] == "Klient wspomniał o krokach prawnych lub organie ochrony konsumentów" and item_en["trigger"]["reason"].startswith("Customer mentioned legal")
        pkg_pl = client.get(f"/api/handoff/{sid}/package", headers={**staff, "X-UI-Lang": "pl"}).json()
        pkg_en = client.get(f"/api/handoff/{sid}/package", headers={**staff, "X-UI-Lang": "en"}).json()
        assert pkg_pl["trigger"]["code"] == pkg_en["trigger"]["code"] and pkg_pl["routing"]["queue"] == pkg_en["routing"]["queue"] == "escalations"
        assert pkg_pl["routing"]["queue_name"] == "Eskalacje i sprawy prawne" and any(r.startswith("R2: ") and "groźba" in r.lower() for r in pkg_pl["routing"]["reasons"])
        assert pkg_pl["suggested_resolution"] != pkg_en["suggested_resolution"] and pkg_en["suggested_resolution"].startswith("Acknowledge the frustration")
        assert pkg_en["text_lang"] == "en" and pkg_pl["text_lang"] == "pl"
        acc = client.post(f"/api/handoff/{sid}/accept", json={"agent_id": "AG-08"}, headers={**staff, "X-UI-Lang": "pl"})
        assert acc.status_code == 200
        conv_notice = client.get(f"/api/chat/sessions/{sid}", headers=cust).json()["session"]["messages"][-1]["text"]
        assert conv_notice.endswith("jest już w rozmowie i widzi wszystko, co zostało ustalone.")
        cb = client.post(f"/api/handoff/{sid}/callback", json={}, headers={**staff, "X-UI-Lang": "pl"}).json()
        assert cb["callback"]["window"] == "next business day 09:00-12:00", "the stored window is what the caller sent (the default is language-neutral data)"
        notice = client.get(f"/api/chat/sessions/{sid}", headers=cust).json()["session"]["messages"][-1]["text"]
        assert notice.startswith("Umówiono oddzwonienie (następny dzień roboczy, 09:00–12:00).")


async def test_agent_assist_speaks_polish_to_a_polish_operator_and_drafts_replies_in_the_conversation_language(svc):
    from fastapi.testclient import TestClient

    from concierge.core.config import Settings
    from concierge.main import create_app

    with TestClient(create_app(Settings(mode="offline", rate_limit_ip_per_min=100000, rate_limit_ai_ip_per_min=100000, rate_limit_global_per_min=100000))) as client:
        cust, staff = {"X-Demo-Role": "customer"}, {"X-Demo-Role": "admin", "X-UI-Lang": "pl"}
        sid = client.post("/api/chat/sessions", json={"language": "pl", "recording_consent": "granted"}, headers=cust).json()["session"]["id"]
        client.post(f"/api/chat/sessions/{sid}/messages", json={"text": "To skandal! Skieruję sprawę do sądu i zgłoszę ją do UOKiK, zamówienie CH-100390."}, headers=cust)
        client.post(f"/api/handoff/{sid}/accept", json={"agent_id": "AG-08"}, headers=staff)
        pl = client.get(f"/api/assist/{sid}", headers=staff).json()
        en = client.get(f"/api/assist/{sid}", headers={**staff, "X-UI-Lang": "en"}).json()
        assert pl["next_best_actions"][0]["title"].startswith("Okaż zrozumienie") and en["next_best_actions"][0]["title"] == "Acknowledge; do not admit liability; summarise the history back"
        assert [r["id"] for r in pl["compliance_reminders"]] == [r["id"] for r in en["compliance_reminders"]], "stable ids"
        assert pl["compliance_reminders"][0]["label"] == "Na początku podano informację o AI i nagrywaniu"
        assert pl["tone"]["tips"][0].startswith("Klient jest sfrustrowany") and en["tone"]["tips"][0].startswith("The customer is frustrated")
        assert pl["form_autofill"]["summary"].startswith("skarga: To skandal!") and en["form_autofill"]["summary"].startswith("complaint: To skandal!")
        assert pl["suggested_replies"][0]["text"].startswith("Bardzo przykro mi z powodu tej sytuacji")
        assert [r["text"] for r in pl["suggested_replies"]] == [r["text"] for r in en["suggested_replies"]], "customer-facing drafts follow the CONVERSATION language, not the operator's UI language"


async def test_polish_assist_next_best_actions_and_reminders_come_from_the_catalog(svc):
    for key in ("assist.rem.recording_consent", "nba.approval.title", "assist.tone.frustrated", "assist.resolution.default"):
        assert i18n.msg(key, "pl") != i18n.msg(key, "en") and i18n.has(key)
    assert i18n.msg("assist.kind.refund", "pl") == "zwrot środków"
