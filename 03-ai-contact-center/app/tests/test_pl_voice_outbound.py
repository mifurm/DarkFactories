"""Polish voice (Realtime configured for Polish, pl-PL TTS / STT, text-in -> Polish audio + transcript) and Polish outbound / proactive messages
(templates, STOP / REZYGNUJĘ opt-out, quiet hours 21:00-08:00 in Europe/Warsaw incl. the DST change)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from concierge.core.ai import azure_cognitive
from concierge.core.config import Settings
from concierge.core.money import speakable_pl
from concierge.engine import outbound as ob
from concierge.engine.guard import AI_DISCLOSURE, GREETING
from concierge.features.voice.session import VoiceSession
from concierge.features.voice.upstream import FakeRealtimeUpstream
from concierge.main import create_app
from test_voice import PCM, FakeRealtimeServer, Sink, open_session  # noqa: F401  (the fake realtime SERVER of the English voice tests)

NBSP = "\u00a0"


# ------------------------------------------------------------------------------------------------------------------ Realtime
async def open_pl_session(svc, fake):
    conv = await svc.orchestrator.start(channel="voice", language="pl", recording_consent="granted")
    sink = Sink()
    from concierge.features.voice.upstream import AzureRealtimeUpstream

    session = VoiceSession(svc, conv.id, sink.json, sink.bytes, upstream_factory=lambda dep: AzureRealtimeUpstream(svc.settings, dep, url=fake.url, token="entra-test-token"))
    await session.start()
    return session, sink, conv.id


async def test_realtime_session_is_configured_for_polish_instructions_transcription_and_greeting(svc):
    async with FakeRealtimeServer().run() as fake:
        session, sink, _ = await open_pl_session(svc, fake)
        try:
            await sink.until(lambda: sink.of("latency"))
            update = next(e for e in fake.received if e["type"] == "session.update")["session"]
            assert update["audio"]["input"]["transcription"] == {"model": "gpt-4o-mini-transcribe", "language": "pl"}, "the input transcription is told the language (better accuracy on short Polish utterances)"
            instructions = update["instructions"]
            assert instructions.startswith("JĘZYK ROZMOWY: polski."), "the language lock comes first (the model otherwise says its pre-tool filler in English)"
            assert "LANGUAGE GUIDE (Polish)" in instructions and "GŁOS (po polsku)" in instructions and "tysiąc pięćset dziewięćdziesiąt dziewięć złotych" in instructions
            assert "1 EUR = 4.30 PLN" in instructions and "rękojmia" in instructions and "[K1]" in instructions
            assert update["audio"]["output"]["voice"] and update["audio"]["input"]["turn_detection"]["interrupt_response"] is True, "barge-in is unchanged"
            greeting = next(e for e in fake.received if e["type"] == "response.create")["response"]["instructions"]
            assert AI_DISCLOSURE["pl"] in greeting and GREETING["pl"] in greeting and "żadnego „cześć”" in greeting, "the disclosure and the formal opening question are spoken verbatim, in Polish, before anything else"
            assert [e["type"] for e in fake.received][:2] == ["session.update", "response.create"]
            assert sink.of("session")[0]["language"] == "pl"
        finally:
            await session.close()


@pytest.mark.parametrize("language", ["pl", "en"])
async def test_a_greeting_without_the_ai_disclosure_is_corrected_once_before_the_caller_can_talk(svc, language):
    skipped = "Cześć, już zaczynam. Pozwól, że przywitam." if language == "pl" else "Let me set up a quick listening frame and then we can dive in."
    corrected = f"{AI_DISCLOSURE[language]} {GREETING[language]}"
    async with FakeRealtimeServer(greetings=[skipped, corrected]).run() as fake:
        session, sink, _ = await (open_pl_session(svc, fake) if language == "pl" else open_session(svc, fake))
        try:
            await sink.until(lambda: len([e for e in sink.of("transcript") if e["role"] == "agent" and e["final"]]) == 2)
            await sink.until(lambda: sink.of("state")[-1]["state"] == "listening")
            creates = [e["response"]["instructions"] for e in fake.received if e["type"] == "response.create"]
            assert len(creates) == 2 and AI_DISCLOSURE[language] in creates[1] and ("słowo w słowo" in creates[1] if language == "pl" else "exactly these words" in creates[1])
            assert session.disclosure_enforced == 1
            states = [e["state"] for e in sink.of("state")]
            assert states.count("listening") == 1, "the caller is invited to speak only after the corrected opening"
            assert any(a["action"] == "voice.disclosure_enforced" for a in await svc.audit.recent(40))
        finally:
            await session.close()


async def test_no_correction_when_the_greeting_already_carries_the_disclosure(svc):
    async with FakeRealtimeServer().run() as fake:
        session, sink, _ = await open_pl_session(svc, fake)
        try:
            await sink.until(lambda: sink.of("latency"))
            await sink.until(lambda: sink.of("state")[-1]["state"] == "listening")
            assert session.disclosure_enforced == 0 and len([e for e in fake.received if e["type"] == "response.create"]) == 1
        finally:
            await session.close()


async def test_english_realtime_session_is_unchanged_no_polish_guide(svc):
    async with FakeRealtimeServer().run() as fake:
        session, sink, _ = await open_session(svc, fake)
        try:
            await sink.until(lambda: sink.of("latency"))
            update = next(e for e in fake.received if e["type"] == "session.update")["session"]
            assert update["audio"]["input"]["transcription"]["language"] == "en" and "LANGUAGE GUIDE" not in update["instructions"] and "GŁOS" not in update["instructions"]
            assert "You are Concierge" in update["instructions"]
        finally:
            await session.close()


async def test_polish_customer_text_reaches_the_realtime_model_unchanged_and_pii_is_masked(svc):
    async with FakeRealtimeServer().run() as fake:
        session, sink, _conv_id = await open_pl_session(svc, fake)
        try:
            await sink.until(lambda: sink.of("latency"))
            fake.stage = "after_tool"
            await session.feed_text("Dzień dobry, moja sofa dotarła uszkodzona, mój PESEL 44051401458, karta 4111 1111 1111 1111.")
            await sink.until(lambda: any(e["type"] == "conversation.item.create" and e["item"].get("role") == "user" for e in fake.received))
            sent = [e for e in fake.received if e["type"] == "conversation.item.create" and e["item"].get("role") == "user"][-1]["item"]["content"][0]["text"]
            assert sent.startswith("Dzień dobry, moja sofa dotarła uszkodzona") and "44051401458" not in sent and "4111" not in sent and "[PESEL]" in sent and "[CARD]" in sent
            assert any(e.get("role") == "customer" and "[PESEL]" in e["text"] for e in sink.of("transcript"))
        finally:
            await session.close()


async def test_text_in_polish_audio_and_transcript_out_through_the_relay(svc):
    c = TestClient(create_app(Settings(mode="offline", rate_limit_ip_per_min=100000, rate_limit_ai_ip_per_min=100000, rate_limit_global_per_min=100000)))
    with c:
        r = c.post("/api/voice/text-turn", json={"text": "Dzień dobry, jaka jest wasza polityka zwrotów?", "language": "pl", "mode": "realtime"}, headers={"X-Demo-Role": "customer", "X-UI-Lang": "pl"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["greeting"] == [f"{AI_DISCLOSURE['pl']} {GREETING['pl']}"], "the Polish disclosure + opening question are the first thing spoken"
        assert body["audio_bytes"] > 0 and body["transcript"], "audio AND a transcript come back"
        reply = " ".join(body["transcript"])
        assert any(ch in reply for ch in "ąćęłńóśźż") or "zwrot" in reply.lower(), reply
        assert not any(w in reply.lower().split() for w in ("the", "return", "policy", "days")), "the answer is Polish, not English"


# ------------------------------------------------------------------------------------------------------------------ fallback pipeline: STT -> LLM -> TTS
async def test_fallback_pipeline_speaks_polish_with_a_pl_pl_voice_and_reads_amounts_as_words(svc):
    conv = await svc.orchestrator.start(channel="voice", language="pl", recording_consent="granted")
    sink = Sink()
    spoken: list[tuple[str, str]] = []
    original = svc.speech.synthesize

    async def spy(text, *, language="en", voice=None):
        spoken.append((language, text))
        return await original(text, language=language, voice=voice)

    svc.speech.synthesize = spy

    def broken(dep: str):
        f = FakeRealtimeUpstream()
        f.fail_connect = True
        return f

    session = VoiceSession(svc, conv.id, sink.json, sink.bytes, upstream_factory=broken)
    await session.start()
    try:
        assert session.mode == "pipeline" and sink.of("fallback")
        assert spoken[0] == ("pl", f"{AI_DISCLOSURE['pl']} {GREETING['pl']}"), "the pipeline speaks the Polish disclosure with the Polish voice"
        await session._pipeline_speak(f"Zwrot 379,00{NBSP}zł jest w drodze, a sofa kosztuje 1 599,00 zł. [K1]")
        assert spoken[-1] == ("pl", "Zwrot trzysta siedemdziesiąt dziewięć złotych jest w drodze, a sofa kosztuje tysiąc pięćset dziewięćdziesiąt dziewięć złotych. ")
        await session.feed_text("Chcę zwrócić krzesła, które zamówiłem.")
        await sink.until(lambda: any(e.get("role") == "agent" and e.get("final") for e in sink.of("transcript")[1:]), timeout=15)
        assert all(lang == "pl" for lang, _ in spoken), "every utterance uses the Polish voice"
    finally:
        await session.close()


async def test_azure_speech_uses_the_pl_pl_neural_voice_and_the_pl_pl_locale_for_stt(monkeypatch):
    assert azure_cognitive.VOICES["pl"] == ("pl-PL", "pl-PL-ZofiaNeural") and azure_cognitive.VOICES["en"][0] == "en-US"

    class Resp:
        content = b"RIFF....WAVE"

        def raise_for_status(self) -> None: ...

        def json(self):
            return {"durationMilliseconds": 1500, "combinedPhrases": [{"text": "dzień dobry"}], "phrases": [{"locale": "pl-PL"}]}

    calls: list[dict] = []

    class Http:
        async def post(self, url, **kw):
            calls.append({"url": url, **kw})
            return Resp()

    async def token(_client_id=None):
        return "entra-token"

    class Meter:
        def check_budget(self) -> None: ...

        def record(self, **kw) -> None: ...

    monkeypatch.setattr(azure_cognitive, "get_token", token)
    speech = azure_cognitive.AzureSpeech(Settings(mode="offline", ai_services_endpoint="https://x.example"), Meter())
    speech._http = Http()
    _audio, mime = await speech.synthesize("Zażółć gęślą jaźń & <test>", language="pl")
    ssml = calls[-1]["content"].decode("utf-8")
    assert mime == "audio/wav" and 'xml:lang="pl-PL"' in ssml and 'name="pl-PL-ZofiaNeural"' in ssml and "Zażółć gęślą jaźń &amp; &lt;test&gt;" in ssml
    result = await speech.transcribe(b"RIFF", language="pl")
    assert calls[-1]["files"]["definition"][1] == '{"locales": ["pl-PL"]}' and result.text == "dzień dobry" and result.language == "pl"
    assert speakable_pl("Razem 12,50 zł.") == "Razem dwanaście złotych pięćdziesiąt groszy."


def test_caller_language_is_derived_from_the_calling_number_in_every_provider_notation():
    from concierge.features.voice.telephony import caller_language

    for polish in ("+48 600 123 456", "+48600123456", "0048 22 555 01 90", "<sip:+48225550190@carrier.example>", "4:+48225550190", "tel:+48-600-123-456", "sip:0048600123456@sbc.example"):
        assert caller_language(polish) == "pl", polish
    for other in ("+4915550001234", "+44 7700 900123", "<sip:+49305550000@carrier.example>", "+148600123456", "600 123 456", "", None, "anonymous"):
        assert caller_language(other) == "en", other


def test_telephony_simulator_answers_a_polish_caller_in_polish():
    with TestClient(create_app(Settings(mode="offline", rate_limit_ip_per_min=100000, rate_limit_ai_ip_per_min=100000, rate_limit_global_per_min=100000))) as c:
        r = c.post("/api/voice/telephony/simulate", json={"scenario": "damaged_sofa", "provider": "sip", "language": "pl"}, headers={"X-Demo-Role": "admin"})
        assert r.status_code == 200, r.text
        body = r.json()
        play = next(a for a in body["final"]["actions"] if a["kind"] == "play")
        assert play["params"]["language"] == "pl" and "nagrywan" in play["params"]["prompt"] and "RODO" in play["params"]["prompt"]
        conv = c.get(f"/api/chat/sessions/{body['final']['conversation_id']}", headers={"X-Demo-Role": "admin"}).json()["session"]
        assert conv["language"] == "pl"
        assert body["exchange"]["agent_lines"][0] == f"{AI_DISCLOSURE['pl']} {GREETING['pl']}" and "numer zamówienia" in body["exchange"]["agent_lines"][1]
        english = c.post("/api/voice/telephony/simulate", json={"scenario": "damaged_sofa", "provider": "sip", "language": "en"}, headers={"X-Demo-Role": "admin"}).json()
        assert english["exchange"]["agent_lines"][0] == "Hello, how can I help you today?"
        assert english["exchange"]["agent_lines"].count("Hello, how can I help you today?") == 1, "the offline demo model is a script: the relay does not 'correct' it (English output unchanged)"


# ------------------------------------------------------------------------------------------------------------------ outbound: templates & opt-out keywords
def test_polish_templates_use_polish_dates_appointment_kinds_and_offer_both_stop_keywords():
    msg = ob.render("shipment_delayed", "pl", first_name="Piotr", order_id="CH-100380", carrier="DHL", eta="2026-11-21")
    assert msg == (
        "Dzień dobry, Państwa zamówienie CH-100380 jest opóźnione u przewoźnika DHL. Nowy przewidywany termin dostawy: 21.11.2026. Aby zmienić termin, zadać pytanie lub poprosić o oddzwonienie, wystarczy odpowiedzieć na tę wiadomość. "
        "To automatyczna wiadomość od Concierge, asystenta AI Contoso Home. Aby zrezygnować z powiadomień, prosimy o odpowiedź: STOP lub REZYGNUJĘ."
    )
    reminder = ob.render("appointment_reminder", "pl", first_name="Anna", order_id="CH-100390", kind="installation", eta="2026-11-24", window="08:00-12:00")
    assert "przypominamy: montaż zamówienia CH-100390 zaplanowano na 24.11.2026 (08:00–12:00)." in reminder and "installation" not in reminder and "Odpowiedz" not in msg + reminder, "formal register throughout: no `Odpowiedz`"
    en = ob.render("shipment_delayed", "en", first_name="Anna", order_id="CH-100232", carrier="NordFreight", eta="2026-11-21")
    assert "Hello Anna, your order CH-100232 is delayed at NordFreight. New estimated delivery: 2026-11-21." in en and en.endswith("Reply STOP to opt out.")


@pytest.mark.parametrize("text", ["STOP", "Stop.", "stop!", "  stop  ", "REZYGNUJĘ", "rezygnuje", "Rezygnuję.", "WYPISZ MNIE", "wypisz", "STOP SMS", "Stop wysyłki", "unsubscribe", "STOPALL", "REZYGNACJA"])
def test_stop_and_rezygnuje_are_opt_out_keywords_with_and_without_diacritics(text):
    assert ob.is_opt_out_keyword(text)


@pytest.mark.parametrize(
    "text",
    ["Proszę nie przestawać wysyłać", "Rezygnuję z zamówienia CH-100350", "Chcę zrezygnować z zamówienia", "stop-klatka", "I will stop by tomorrow", "Cancel", "Dziękuję", "Kiedy będzie dostawa?", "nie chcę wiadomości o promocjach, ale o dostawach tak"],
)
def test_ordinary_replies_are_not_opt_outs(text):
    assert not ob.is_opt_out_keyword(text)


# ------------------------------------------------------------------------------------------------------------------ outbound: API
def client() -> TestClient:
    return TestClient(create_app(Settings(mode="offline", rate_limit_ip_per_min=100000, rate_limit_ai_ip_per_min=100000, rate_limit_global_per_min=100000)))


SUP = {"X-Demo-Role": "supervisor"}


def piotr(decisions: list[dict]) -> dict:
    return next(d for d in decisions if d["customer_id"] == "CU-1012")


def test_polish_customer_gets_the_delay_notice_in_polish_then_rezygnuje_withdraws_all_consent_in_polish_and_english():
    with client() as c:
        day = datetime(2026, 11, 18, 10, 0, tzinfo=UTC).isoformat()  # 11:00 in Warsaw
        run = c.post("/api/outbound/events", json={"trigger": "shipment_delayed", "as_of": day, "use_llm": False}, headers={**SUP, "X-UI-Lang": "pl"}).json()
        d = piotr(run["decisions"])
        assert d["decision"] == "sent" and d["channel"] == "sms" and d["reason"] == "wszystkie kontrole zakończone powodzeniem" and d["reason_code"] == "all_ok"
        assert d["message"].startswith("Dzień dobry, Państwa zamówienie CH-100380 jest opóźnione u przewoźnika DHL. Nowy przewidywany termin dostawy: ") and d["message"].endswith("REZYGNUJĘ.")
        conv_id = d["conversation_id"]
        conv = c.get(f"/api/chat/sessions/{conv_id}", headers={"X-Demo-Role": "admin"}).json()["session"]
        assert conv["language"] == "pl" and conv["messages"][0]["text"] == d["message"]

        not_a_stop = c.post("/api/outbound/replies", json={"conversation_id": conv_id, "text": "Kiedy dokładnie przyjedzie kurier?"}).json()
        assert not_a_stop["opted_out"] is False and not_a_stop["next"] == "conversation"
        stop = c.post("/api/outbound/replies", json={"conversation_id": conv_id, "text": "REZYGNUJĘ"})
        assert stop.status_code == 200 and stop.json()["opted_out"] is True and stop.json()["customer_id"] == "CU-1012"
        assert stop.json()["confirmation"].startswith("Potwierdzamy rezygnację z powiadomień — Contoso Home nie będzie już wysyłać Państwu wiadomości z własnej inicjatywy.")
        prefs = c.get("/api/outbound/preferences/CU-1012", headers=SUP).json()
        assert prefs["opt_out"]["all"] is True and prefs["opt_out"]["channels"] == ["sms", "email", "voice"] and prefs["opt_out"]["source"] == "reply-keyword"
        assert any(a["action"] == "outbound.opt_out" and a["detail"]["source"] == "reply-keyword" for a in c.get("/api/compliance/audit?limit=50", headers={"X-Demo-Role": "admin"}).json())

        again_pl = c.post("/api/outbound/events", json={"trigger": "shipment_delayed", "as_of": day, "use_llm": False}, headers={**SUP, "X-UI-Lang": "pl"}).json()
        again_en = c.post("/api/outbound/events", json={"trigger": "shipment_delayed", "as_of": day, "use_llm": False}, headers={**SUP, "X-UI-Lang": "en"}).json()
        s_pl, s_en = piotr(again_pl["decisions"]), piotr(again_en["decisions"])
        assert s_pl["decision"] == s_en["decision"] == "suppressed" and s_pl["reason_code"] == s_en["reason_code"] == "opt_out_all"
        assert s_pl["reason"] == "klient zrezygnował ze wszystkich kontaktów proaktywnych" and s_en["reason"] == "customer opted out of all outbound contact"
        ov = c.get("/api/outbound/overview", headers={**SUP, "X-UI-Lang": "pl"}).json()
        assert "klient zrezygnował ze wszystkich kontaktów proaktywnych" in ov["reasons"] and ov["campaigns"][0]["name"] in ("Opóźnienie przesyłki — powiadomienie proaktywne", "Przypomnienie o terminie dostawy lub montażu")
        assert {x["id"] for x in ov["campaigns"]} == {"camp-shipment-delay", "camp-appointment-reminder"}, "campaign ids are stable"
        assert c.post("/api/outbound/replies", json={"conversation_id": "cv_nope", "text": "STOP"}).status_code == 404


def test_quiet_hours_21_to_08_apply_in_warsaw_and_the_decision_is_deferred_to_08_local():
    with client() as c:
        night = datetime(2026, 11, 18, 21, 30, tzinfo=UTC)  # 22:30 in Warsaw (CET)
        run = c.post("/api/outbound/events", json={"trigger": "shipment_delayed", "as_of": night.isoformat(), "use_llm": False}, headers={**SUP, "X-UI-Lang": "pl"}).json()
        d = piotr(run["decisions"])
        assert d["decision"] == "deferred" and d["reason_code"] == "quiet_hours" and d["reason"] == "cisza nocna w strefie czasowej odbiorcy (Europe/Warsaw, czas lokalny: 22:30)"
        assert datetime.fromtimestamp(d["scheduled_for"], UTC) == datetime(2026, 11, 19, 7, 0, tzinfo=UTC), "released at 08:00 Warsaw time (07:00 UTC in winter)"
        en = c.post("/api/outbound/events", json={"trigger": "shipment_delayed", "as_of": night.isoformat(), "use_llm": False}, headers={**SUP, "X-UI-Lang": "en"}).json()
        assert piotr(en["decisions"])["reason"] == "quiet hours in the recipient's time zone (Europe/Warsaw, 22:30 local)"


def test_quiet_hours_follow_the_warsaw_dst_change_and_use_the_whole_21_08_window():
    def quiet(ts: datetime) -> bool:
        return ob.in_quiet_hours(ts.timestamp(), "PL")

    assert not quiet(datetime(2026, 3, 28, 19, 30, tzinfo=UTC)), "20:30 CET"
    assert quiet(datetime(2026, 3, 30, 19, 30, tzinfo=UTC)), "21:30 CEST after the clocks went forward on 29 March"
    assert not quiet(datetime(2026, 10, 24, 18, 59, tzinfo=UTC)) and quiet(datetime(2026, 10, 24, 19, 0, tzinfo=UTC)), "21:00 CEST starts the quiet window"
    assert quiet(datetime(2026, 7, 10, 5, 59, tzinfo=UTC)) and not quiet(datetime(2026, 7, 10, 6, 0, tzinfo=UTC)), "08:00 CEST ends it"
    assert quiet(datetime(2026, 12, 1, 6, 59, tzinfo=UTC)) and not quiet(datetime(2026, 12, 1, 7, 0, tzinfo=UTC)), "08:00 CET (UTC+1) ends it in winter"
    assert ob.TZ["PL"] == "Europe/Warsaw"


def test_english_outbound_decisions_keep_their_historic_reason_texts():
    prefs = {"consents": {"sms": {"granted": True, "ts": 1.0, "source": "x", "text_version": "v"}}, "opt_out": {"all": False, "channels": []}}
    camp = {"state": "active", "caps": {"per_customer_7d": 2, "per_day": 150}, "quiet_hours": {"start": 21, "end": 8}}
    now = datetime(2026, 11, 18, 12, 0, tzinfo=UTC).timestamp()
    assert ob.decide(market="DE", prefs=prefs, campaign=camp, kill_switch=True, now_ts=now, contacts_7d=0, sent_today=0).reason == "global outbound kill-switch is on"
    assert ob.decide(market="DE", prefs=prefs, campaign={**camp, "state": "paused"}, kill_switch=False, now_ts=now, contacts_7d=0, sent_today=0).reason == "campaign is paused"
    assert ob.decide(market="DE", prefs=None, campaign=camp, kill_switch=False, now_ts=now, contacts_7d=0, sent_today=0).reason == "no contact preferences on file (no consent)"
    assert ob.decide(market="DE", prefs=prefs, campaign=camp, kill_switch=False, now_ts=now, contacts_7d=2, sent_today=0).reason == "frequency cap reached (2 outbound contacts in 7 days, cap 2)"
    assert ob.decide(market="DE", prefs=prefs, campaign=camp, kill_switch=False, now_ts=now, contacts_7d=0, sent_today=150).reason == "campaign daily cap reached"
    ok = ob.decide(market="DE", prefs=prefs, campaign=camp, kill_switch=False, now_ts=now, contacts_7d=0, sent_today=0)
    assert (ok.decision, ok.reason, ok.code) == ("sent", "all checks passed", "all_ok")
