"""Frontend <-> backend localization CONTRACT (spec §11): locale resolution order, `Content-Language`, SSE / WebSocket `?lang=`, error bodies with stable
codes + localized message / hint, additive-only API (the English output of every localized endpoint is unchanged), message-catalog parity, read-time
localization of persisted records (supervisor, routing, VoC, WFM), idempotent seeds (also on an already-seeded repository) and the proof that the English
seed data is byte-identical to the original generator."""

from __future__ import annotations

import hashlib
import json
import re

from fastapi import Request, WebSocket
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from concierge.core import catalog_en, catalog_pl, i18n
from concierge.core.config import Settings
from concierge.engine import history_seed, synth
from concierge.engine.routing import QUEUES, ROUTING_RULES
from concierge.engine.wrapup import DISPOSITIONS
from concierge.main import create_app
from concierge.services import build_services

ADMIN = {"X-Demo-Role": "admin"}
CUST = {"X-Demo-Role": "customer"}
BIG = {"rate_limit_ip_per_min": 100000, "rate_limit_ai_ip_per_min": 100000, "rate_limit_global_per_min": 100000}


def client(**kw) -> TestClient:
    return TestClient(create_app(Settings(mode="offline", **{**BIG, **kw})))


# ------------------------------------------------------------------------------------------------------------------ locale resolution
def test_locale_is_resolved_query_then_header_then_accept_language_then_english():
    with client() as c:
        def lang(headers=None, query=""):
            r = c.get(f"/api/meta{query}", headers=headers or {})
            assert r.status_code == 200
            return r.json()["language"], r.headers["content-language"]

        assert lang() == ("en", "en")
        assert lang({"Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8"}) == ("pl", "pl")
        assert lang({"Accept-Language": "en-GB,en;q=0.9,pl;q=0.8"}) == ("en", "en")
        assert lang({"Accept-Language": "en", "X-UI-Lang": "pl"}) == ("pl", "pl"), "X-UI-Lang beats Accept-Language"
        assert lang({"Accept-Language": "pl", "X-UI-Lang": "en"}, "?lang=pl") == ("pl", "pl"), "?lang= beats the headers"
        assert lang({"X-UI-Lang": "pl"}, "?lang=en") == ("en", "en")
        assert lang({"X-UI-Lang": "de"}) == ("en", "en"), "an unsupported language falls back to English"
        assert lang({"X-UI-Lang": "PL_pl"}) == ("pl", "pl")


def test_meta_announces_the_languages_additively_and_keeps_every_historic_field():
    with client() as c:
        m = c.get("/api/meta").json()
    assert m["languages"] == ["en", "pl"] and m["default_language"] == "en" and m["language_names"] == {"en": "English", "pl": "Polski"}
    for key in ("name", "product", "version", "build_id", "mode", "region", "deployments", "repository", "llm", "uptime_s", "features", "seed", "daily_budget_usd", "synthetic_data", "simulated"):
        assert key in m, key


def test_features_registry_stays_english_whatever_the_locale():
    with client() as c:
        en = c.get("/api/features").json()
        pl = c.get("/api/features", headers={"X-UI-Lang": "pl"}).json()
    assert en == pl and len(en) == 24 and en[0]["id"] and any(f["name"] == "Real-time voice agent" for f in en), "the registry is the contract with docs and smoke: English"


def test_the_locale_reaches_sse_and_websocket_handlers_through_the_query_string():
    app = create_app(Settings(mode="offline", **BIG))

    @app.get("/api/_locale/stream")
    async def stream(request: Request) -> StreamingResponse:
        async def gen():
            yield f"data: {i18n.current_locale()}\n\n".encode()
            yield f"data: {i18n.msg('err.not_found')}\n\n".encode()

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.websocket("/ws/_locale")
    async def ws(socket: WebSocket) -> None:
        await socket.accept()
        await socket.send_text(json.dumps({"locale": i18n.current_locale(), "message": i18n.msg("err.not_found")}))
        await socket.close()

    with TestClient(app) as c:
        sse = c.get("/api/_locale/stream?lang=pl", headers={"X-UI-Lang": "en"})
        assert sse.text == "data: pl\n\ndata: Nie znaleziono żądanego zasobu.\n\n" and sse.headers["content-language"] == "pl"
        assert c.get("/api/_locale/stream").text.startswith("data: en")
        with c.websocket_connect("/ws/_locale?lang=pl") as socket:
            assert socket.receive_json() == {"locale": "pl", "message": "Nie znaleziono żądanego zasobu."}
        with c.websocket_connect("/ws/_locale", headers={"Accept-Language": "pl"}) as socket:
            assert socket.receive_json()["locale"] == "pl"
        with c.websocket_connect("/ws/_locale") as socket:
            assert socket.receive_json() == {"locale": "en", "message": "The requested resource was not found."}


def test_the_chat_stream_endpoint_accepts_the_language_and_keeps_the_conversation_language_for_replies():
    with client() as c:
        sid = c.post("/api/chat/sessions", json={"language": "pl", "recording_consent": "granted"}, headers={**CUST, "X-UI-Lang": "pl"}).json()["session"]["id"]
        r = c.post(f"/api/chat/sessions/{sid}/stream?lang=pl", json={"text": "Dzień dobry, jaka jest wasza polityka zwrotów?"}, headers=CUST)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:")]
        final = next(e for e in events if e.get("type") == "message" and e["message"]["role"] == "agent_ai")
        assert "[K1]" in final["message"]["text"] and "dni" in final["message"]["text"], "a Polish conversation is answered in Polish from the Polish article"


def test_an_omitted_conversation_language_follows_the_request_locale_and_an_explicit_one_wins():
    with client() as c:
        pl = {"X-UI-Lang": "pl"}
        assert c.post("/api/chat/sessions", json={}, headers={**CUST, **pl}).json()["session"]["language"] == "pl"
        assert c.post("/api/chat/sessions", json={}, headers=CUST).json()["session"]["language"] == "en", "English stays the default"
        assert c.post("/api/chat/sessions", json={"language": "en"}, headers={**CUST, **pl}).json()["session"]["language"] == "en", "an explicit language beats the locale"
        assert c.post("/api/voice/sessions", json={}, headers=pl).json()["language"] == "pl"
        assert c.post("/api/kb/ask", json={"question": "Jaka będzie jutro pogoda w Warszawie?"}, headers=pl).json()["answer"].startswith("Nie mam na ten temat wiarygodnych informacji")
        assert c.post("/api/kb/ask", json={"question": "What is the weather in Berlin tomorrow?"}).json()["answer"].startswith("I don't have reliable information")
        assert c.post("/api/kb/ask", json={"question": "Jaka będzie jutro pogoda w Warszawie?", "language": "en"}, headers=pl).json()["answer"].startswith("I don't have reliable information")


# ------------------------------------------------------------------------------------------------------------------ errors
def test_error_bodies_keep_their_stable_codes_and_localize_message_and_hint():
    with client() as c:
        for path, role, code, en_msg, pl_msg in [
            ("/api/chat/sessions/nope", None, "session_not_found", "Unknown or expired session.", "Nieznana lub wygasła sesja."),
            ("/api/security/matrix", "customer", "forbidden", "Your role is not allowed to do this.", "Ta rola nie ma uprawnień do tej operacji."),
            ("/api/wrapup/cv_nope", "admin", "conversation_not_found", "conversation not found", "Nie znaleziono rozmowy."),
            ("/api/handoff/cv_nope/package", "admin", "no_handoff", "no handoff for this conversation", "Dla tej rozmowy nie ma przekazania do konsultanta."),
            ("/api/nope", None, "not_found", "Not Found", "Nie znaleziono żądanego zasobu."),
            ("/api/wfm/history?queue=nope", "admin", "unknown_queue", "unknown queue 'nope'", "Nieznana kolejka."),
        ]:
            roleh = {"X-Demo-Role": role} if role else {}
            en = c.get(path, headers={**roleh, "X-UI-Lang": "en"})
            pl = c.get(path, headers={**roleh, "X-UI-Lang": "pl"})
            assert en.status_code == pl.status_code, path
            ben, bpl = en.json(), pl.json()
            assert ben["error"] == bpl["error"] == ben["code"] == bpl["code"] == code, path
            assert ben["message"].startswith(en_msg), "English keeps the historic message text"
            assert bpl["message"] == pl_msg, path
            assert ben["request_id"] and bpl["request_id"]
            assert ("hint" in ben) == ("hint" in bpl), "a hint exists in both languages or in neither"
            assert ben["detail"] == (ben["message"] if isinstance(ben["detail"], str) else ben["detail"]), "the historic `detail` of the English body is untouched"
            assert bpl["detail"] == pl_msg or (isinstance(bpl["detail"], dict) and bpl["detail"]["message"] == pl_msg), "and the Polish detail agrees with the message"


def test_validation_errors_keep_fastapi_detail_and_add_code_message_and_field_list():
    with client() as c:
        en = c.post("/api/chat/sessions/x/messages", json={}, headers={**CUST, "X-UI-Lang": "en"}).json()
        pl = c.post("/api/chat/sessions/x/messages", json={}, headers={**CUST, "X-UI-Lang": "pl"}).json()
    assert en["detail"] == pl["detail"] == [{"loc": ["body", "text"], "msg": "Field required", "type": "missing"}], "the historic FastAPI `detail` list is untouched"
    assert en["error"] == pl["error"] == "validation_error" and en["message"] == "The request contains invalid data." and pl["message"] == "Żądanie zawiera nieprawidłowe dane."
    assert pl["hint"] == "Proszę sprawdzić zaznaczone pola i spróbować ponownie." and pl["errors"] == [{"field": "text", "message": "Field required", "type": "missing"}]


def test_rate_limit_and_budget_errors_are_localized_with_stable_codes():
    with TestClient(create_app(Settings(mode="offline", rate_limit_ip_per_min=3, rate_limit_ai_ip_per_min=100000, rate_limit_global_per_min=100000))) as c:
        last = None
        for _ in range(12):
            last = c.post("/api/chat/sessions", json={"language": "pl"}, headers={"X-UI-Lang": "pl"})  # the limiter counts mutating calls per IP
            if last.status_code == 429:
                break
        assert last is not None and last.status_code == 429 and last.headers["retry-after"]
        body = last.json()
        assert body["error"] == "rate_limited" and body["code"] == "rate_limited" and body["scope"] == "ip-mutating" and body["message"] == "Zbyt wiele żądań." and body["hint"].startswith("Proszę odczekać")
        english = c.post("/api/chat/sessions", json={"language": "en"}, headers={"X-UI-Lang": "en"}).json()
        assert english["error"] == "rate_limited" and english["message"] == "Too many requests." and english["hint"] == "Wait a few seconds and try again."
    assert i18n.msg("err.daily_ai_budget_exceeded", "pl").startswith("Dzienny budżet AI")


# ------------------------------------------------------------------------------------------------------------------ catalogs
def test_message_catalogs_have_identical_keys_and_placeholders_and_no_empty_text():
    en, pl = catalog_en.MESSAGES, catalog_pl.MESSAGES
    assert set(en) == set(pl), sorted(set(en) ^ set(pl))[:10]
    for key in en:
        assert en[key].strip() and pl[key].strip(), key
        assert set(re.findall(r"\{(\w+)\}", en[key])) == set(re.findall(r"\{(\w+)\}", pl[key])), f"placeholders differ in {key}"
    assert len(en) >= 360 and i18n.catalog_codes("en") == i18n.catalog_codes("pl")


def test_polish_catalog_is_polish_not_english_with_known_exceptions():
    english_words = re.compile(r"\b(the|and|with|your|was|were|has|have|not|please|customer|request|conversation|order|refund)\b", re.IGNORECASE)
    offenders = [(key, text[:80]) for key, text in catalog_pl.MESSAGES.items() if english_words.search(re.sub(r"\{\w+\}", "", text))]
    assert offenders == [], offenders
    identical = [k for k, v in catalog_pl.MESSAGES.items() if v == catalog_en.MESSAGES[k] and len(re.sub(r"\{\w+\}", "", v).split()) > 1]  # "status: {status}" is the same word in both
    assert identical == [], f"untranslated: {identical[:10]}"


def test_catalog_helpers_fall_back_to_english_then_to_the_code_and_interpolate_safely():
    assert i18n.msg("err.not_found", "pl") == "Nie znaleziono żądanego zasobu." and i18n.msg("err.not_found", "en") == "The requested resource was not found."
    assert i18n.msg("no.such.code", "pl") == "no.such.code"
    assert i18n.msg("trigger.takeover", "pl", by="AG-08") == "Rozmowę prowadzoną przez AI przejęto ręcznie (rola: AG-08)"
    assert i18n.msg("trigger.takeover", "pl") == i18n.CATALOGS["pl"]["trigger.takeover"], "a missing parameter never raises"
    assert i18n.label("queue", "escalations", "pl") == "Eskalacje i sprawy prawne" and i18n.label("queue", "nope", "pl", "Nope") == "Nope"
    with i18n.use_locale("pl"):
        assert i18n.current_locale() == "pl" and i18n.msg("queue.care") == "Opieka nad klientem (szczególna troska)"
    assert i18n.current_locale() == "en"


def test_every_stable_code_of_the_polish_ui_has_a_polish_label():
    for q in QUEUES:
        assert i18n.has(f"queue.{q}") and i18n.msg(f"queue.{q}", "pl") != QUEUES[q]["name"], q
    for code in DISPOSITIONS:
        assert i18n.has(f"disposition.{code}") and i18n.msg(f"disposition.{code}", "en") == DISPOSITIONS[code], code
    for rule in ROUTING_RULES:
        assert i18n.msg(f"route.rule.{rule['id']}", "en") == rule["when"], rule["id"]


# ------------------------------------------------------------------------------------------------------------------ additive: English output unchanged
def test_english_output_of_every_localized_endpoint_is_unchanged():
    with client() as c:
        wrap = c.get("/api/wrapup/dispositions", headers=ADMIN).json()
        assert wrap == DISPOSITIONS
        q = c.get("/api/routing/queues", headers=ADMIN).json()
        assert [x["name"] for x in q["queues"]] == [v["name"] for v in QUEUES.values()] and q["rules"] == ROUTING_RULES
        assert q["semantics"].startswith("Provider-neutral, in-process router with Job-Router-style semantics")
        sup = c.get("/api/supervisor/overview", headers=ADMIN).json()
        assert [x["name"] for x in sup["queues"]] == [v["name"] for v in QUEUES.values()] and all("label" not in h for h in sup["heat_map"])
        alerts = c.get("/api/supervisor/alerts", headers=ADMIN).json()
        assert alerts["rule"] == "alert when the oldest waiter used >= 80 % of the queue SLA or the projected wait exceeds the SLA; clears when the queue is healthy"
        voc = c.get("/api/voc/summary", headers=ADMIN).json()
        assert all("label_en" not in cl for cl in voc["clusters"]) and voc["alerts"] and re.match(r"^'.+'( \(\+\d+ related topic clusters\))? is running at [\d.]+/day vs [\d.]+/day baseline \([\d.]+x\)", voc["alerts"][0]["message"])
        wq = c.get("/api/wfm/queues", headers=ADMIN).json()
        assert [x["name"] for x in wq[:5]] == ["General support", "Delivery & installation", "Returns & refunds", "Warranty & repairs", "Billing & payments"]
        assert all("timezone" not in x for x in wq[:5]), "the five global queues carry no time zone, as before"
        bt = c.get("/api/wfm/backtest", headers=ADMIN).json()
        assert set(bt["queues"]) == set(synth.WFM_QUEUES) and bt["method"].startswith("rolling origin, 4 folds x 7 days")


# ------------------------------------------------------------------------------------------------------------------ supervisor / routing / wrap-up in the request locale
def test_supervisor_routing_and_dispositions_render_in_polish_with_stable_codes():
    with client() as c:
        pl = {**ADMIN, "X-UI-Lang": "pl"}
        assert c.get("/api/wrapup/dispositions", headers=pl).json()["RESOLVED_REFUND_ISSUED"] == "Rozwiązano — zwrot środków zrealizowany"
        assert set(c.get("/api/wrapup/dispositions", headers=pl).json()) == set(DISPOSITIONS), "the codes are the keys"
        rq = c.get("/api/routing/queues", headers=pl).json()
        assert {x["id"] for x in rq["queues"]} == set(QUEUES) and rq["queues"][0]["name"] == "Obsługa ogólna" and rq["rules"][1]["id"] == "R2" and rq["rules"][1]["when"].startswith("flaga ryzyka: groźba prawna")
        assert rq["semantics"].startswith("Router niezależny od dostawcy")
        route = c.post("/api/routing/route", json={"intent": "complaint", "risk_flags": ["legal_threat"], "sentiment": -0.8, "urgency": "high", "language": "pl"}, headers=pl).json()
        assert route["queue"] == "escalations" and route["rule"] == "R2" and route["queue_name"] == "Eskalacje i sprawy prawne" and route["reasons"][0].startswith("R2: flaga ryzyka")
        sim = c.post("/api/routing/triggers/simulate", json={"language": "pl", "turns": ["Z piekarnika czuć zapach gazu!"]}, headers=pl).json()
        fired = sim["timeline"][0]["fired"][0]
        assert fired["code"] == "safety_issue" and fired["reason"] == "Zgłoszono problem z bezpieczeństwem produktu"


def test_sla_alerts_and_queue_names_in_the_supervisor_view_follow_the_locale_while_stored_alerts_stay_english():
    with client() as c:
        sid = c.post("/api/chat/sessions", json={"language": "pl", "recording_consent": "granted"}, headers=CUST).json()["session"]["id"]
        c.post(f"/api/chat/sessions/{sid}/messages", json={"text": "To skandal! Skieruję sprawę do sądu i zgłoszę ją do UOKiK, zamówienie CH-100390."}, headers=CUST)
        pl = c.get("/api/supervisor/overview", headers={**ADMIN, "X-UI-Lang": "pl"}).json()
        en = c.get("/api/supervisor/overview", headers={**ADMIN, "X-UI-Lang": "en"}).json()
        esc_pl = next(q for q in pl["queues"] if q["queue"] == "escalations")
        esc_en = next(q for q in en["queues"] if q["queue"] == "escalations")
        assert esc_pl["name"] == "Eskalacje i sprawy prawne" and esc_en["name"] == "Escalations & legal" and esc_pl["waiting"] == esc_en["waiting"] == 1 and esc_pl["state"] == esc_en["state"]
        assert pl["alerts"] and en["alerts"] and pl["alerts"][0]["id"] == en["alerts"][0]["id"] and pl["alerts"][0]["queue"] == "escalations"
        assert re.fullmatch(r"najdłuższe oczekiwanie: \d+ s przy SLA 60 s; prognozowane oczekiwanie: \d+ s; dostępnych konsultantów: \d+", pl["alerts"][0]["reason"]), pl["alerts"][0]["reason"]
        assert re.fullmatch(r"oldest wait \d+s of 60s SLA; projected wait \d+s; \d+ agent\(s\) available", en["alerts"][0]["reason"])
        assert pl["alerts"][0]["name"] == "Eskalacje i sprawy prawne" and pl["alerts"][0]["params"]["sla"] == 60
        heat = {h["key"]: h for h in pl["heat_map"]}
        assert heat["Escalations & legal"]["label"] == "Eskalacje i sprawy prawne", "the stable key stays, the label is localized"
        assert c.get("/api/supervisor/alerts", headers={**ADMIN, "X-UI-Lang": "pl"}).json()["rule"].startswith("alert, gdy najdłużej oczekujący wykorzystał co najmniej 80% SLA kolejki")
        mon = c.post(f"/api/supervisor/{sid}/monitor", json={"mode": "listen"}, headers={**ADMIN, "X-UI-Lang": "pl"}).json()
        assert mon["note"] == "podgląd rozmowy na żywo"


# ------------------------------------------------------------------------------------------------------------------ seeds
ANCHOR = 1_794_960_000.0
ORIGINAL_HISTORY_DIGEST = "be5e6aa970367b4442845d314a5f634a012c99cf49a30a7b1bd054f60baaa8ca"  # sha256 of the records of the ORIGINAL generator (commit 947d29d)
ORIGINAL_WFM_DIGEST = "32761649dead47b445ea1c5e59ea53f9cc87a440fdc6a41889238e576d03d6c8"


def digest(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def test_the_english_history_and_wfm_seed_data_is_byte_identical_to_the_original_generator():
    rows = synth.generate_history(ANCHOR)
    assert len(rows) == 1934 and sum(1 for r in rows if r["market"] == "PL") == 140
    base = []
    for r in rows:
        r = {k: v for k, v in r.items() if k != "summary_pl"}
        if r["market"] == "PL":
            r["text"] = r["summary"]  # the original generator used the English summary as the opening text of every market
        base.append(r)
    assert digest(base) == ORIGINAL_HISTORY_DIGEST, "ids, timestamps, scores, sentiment, topics and the English summaries did not move"
    assert digest(synth.generate_wfm_history(ANCHOR)) == ORIGINAL_WFM_DIGEST, "the five global queues (and so every Erlang / forecast number) are unchanged"


def test_polish_slice_content_every_record_has_a_polish_summary_and_pl_records_a_polish_opening_message():
    rows = synth.generate_history(ANCHOR)
    assert all(r["summary_pl"] and r["summary_pl"].startswith("Powód: ") for r in rows)
    pl_rows = [r for r in rows if r["market"] == "PL"]
    assert all(r["language"] == "pl" and r["text"] != r["summary"] and any(ch.isalpha() for ch in r["text"]) for r in pl_rows)
    assert all(r["text"] == r["summary"] for r in rows if r["market"] != "PL"), "other markets keep their historic text"
    topics = {r["topic"] for r in pl_rows}
    assert len(topics) == 13, "every contact driver is represented in the Polish market"
    assert not re.search(r"\b(the|customer|asks|wants)\b", " ".join(r["summary_pl"] for r in rows)), "no English in the Polish summaries"
    assert not re.search(r"\{|\}", " ".join(r["summary_pl"] for r in rows)), "no unfilled template slot"
    assert len({r["id"] for r in rows}) == len(rows)


def test_polish_wfm_queues_are_in_warsaw_time_with_polish_holidays_and_their_own_random_stream():
    docs = synth.generate_wfm_history_pl(ANCHOR)
    assert {d["queue"] for d in docs} == {"general-pl", "delivery-pl"} and len(docs) == 180 and all(d["timezone"] == "Europe/Warsaw" and d["market"] == "PL" and len(d["intervals"]) == 48 for d in docs)
    holidays = [d for d in docs if d["event"] == "holiday"]
    assert holidays and all(d["date"] in synth.pl_holidays(int(d["date"][:4])) for d in holidays)
    assert docs == synth.generate_wfm_history_pl(ANCHOR), "deterministic"
    assert {"2026-11-11", "2026-11-01", "2026-12-25", "2026-04-06", "2026-06-04"} <= synth.pl_holidays(2026), "Niepodległości, Wszystkich Świętych, Boże Narodzenie, Poniedziałek Wielkanocny, Boże Ciało"
    busy = [sum(d["intervals"][i] for d in docs if d["queue"] == "general-pl" and d["dow"] < 5 and not d["event"]) for i in range(48)]
    assert max(range(48), key=busy.__getitem__) in range(18, 30), "the busiest half hour lies between 09:00 and 15:00 Warsaw time (broad 10:00-14:00 plateau)"
    assert sum(busy[:10]) < 0.06 * sum(busy), "almost nothing between 00:00 and 05:00 local time"


async def test_history_seed_is_idempotent_and_upgrades_an_already_seeded_repository_without_wiping_it():
    svc = build_services(Settings(mode="offline"))
    await svc.start()
    try:
        first = await history_seed.seed_history(svc)
        assert first["skipped"] is False and first["records"] == 1934 and first["wfm_docs"] == 450
        meta = await svc.repo.get("seed_meta", "history")
        assert meta["version"] == "h4" and meta["pl_slice"] == "pl2" and meta["wfm_docs_pl"] == 180
        second = await history_seed.seed_history(svc)
        assert second["skipped"] is True and "pl_slice" not in second, "a second run changes nothing"

        # simulate the DEPLOYED Cosmos data: seeded by the previous version (no Polish fields, no Polish queues, no slice marker)
        rows = await svc.repo.query("history", limit=6000)
        for r in rows:
            r = {k: v for k, v in r.items() if k not in ("summary_pl", "pk", "_ts")}
            if r["market"] == "PL":
                r["text"] = r["summary"]
            await svc.repo.put("history", r)
        for d in await svc.repo.query("wfm_history", {"queue": {"$in": ["general-pl", "delivery-pl"]}}):
            await svc.repo.delete("wfm_history", d["id"])
        await svc.repo.put("seed_meta", {k: v for k, v in meta.items() if k not in ("pl_slice", "wfm_docs_pl", "pk", "_ts")})
        before_ids = {r["id"] for r in await svc.repo.query("history", limit=6000)}
        base_digest = digest(sorted(({k: v for k, v in r.items() if k not in ("pk", "_ts")} for r in await svc.repo.query("wfm_history", limit=6000)), key=lambda d: d["id"]))

        upgraded = await history_seed.seed_history(svc)
        assert upgraded["skipped"] is True and upgraded["pl_slice"] == {"patched_records": len(before_ids), "wfm_docs_pl": 180}
        after = await svc.repo.query("history", limit=6000)
        assert {r["id"] for r in after} == before_ids, "no record was added, removed or renamed"
        assert all(r.get("summary_pl") for r in after) and all(r["text"] != r["summary"] for r in after if r["market"] == "PL")
        assert digest(sorted(({k: v for k, v in r.items() if k not in ("pk", "_ts")} for r in await svc.repo.query("wfm_history", {"queue": {"$in": list(synth.WFM_QUEUES)}}, limit=6000)), key=lambda d: d["id"])) == base_digest, "the five global queues were not touched"
        assert len(await svc.repo.query("wfm_history", {"queue": "general-pl"})) == 90
        assert (await svc.repo.get("seed_meta", "history"))["version"] == "h4"
        assert "pl_slice" not in await history_seed.seed_history(svc), "and the upgrade runs once"
    finally:
        await svc.stop()


# ------------------------------------------------------------------------------------------------------------------ VoC and WFM in Polish
def test_voc_labels_alerts_and_examples_are_polish_for_a_polish_operator_and_unchanged_in_english():
    with client() as c:
        en = c.get("/api/voc/summary", headers=ADMIN).json()
        pl = c.get("/api/voc/summary", headers={**ADMIN, "X-UI-Lang": "pl"}).json()
        assert [x["id"] for x in pl["clusters"]] == [x["id"] for x in en["clusters"]] and [x["volume"] for x in pl["clusters"]] == [x["volume"] for x in en["clusters"]], "numbers and ids are stable"
        labels = [x["label"] for x in pl["clusters"]]
        assert len(set(labels)) == len(labels), "every topic keeps a distinct label"
        assert all(x["label_en"] == e["label"] for x, e in zip(pl["clusters"], en["clusters"], strict=True))
        assert any(label.startswith("Uszkodzenie przy dostawie") for label in labels)
        alert_pl, alert_en = pl["alerts"][0], en["alerts"][0]
        assert alert_pl["id"] == alert_en["id"] and alert_pl["carrier"] == alert_en["carrier"] and alert_pl["z"] == alert_en["z"]
        assert re.fullmatch(r"„.+” \(powiązane klastry tematyczne: \+\d+\) występuje w tempie \d+,\d/dzień wobec \d+,\d/dzień w okresie bazowym \(\d+,\d×\) — przewoźnik NordFreight odpowiada za \d+% ostatnich kontaktów \(w okresie bazowym \d+%\)\.", alert_pl["message"]), alert_pl["message"]
        assert alert_pl["evidence_summaries"] != alert_en["evidence_summaries"] and alert_pl["evidence_summaries"][0].startswith("Powód: ")
        example = pl["clusters"][0]["examples"][0]
        assert example["summary"].startswith("Powód: ") and example["summary_pl"] == example["summary"]
        topic = c.get(f"/api/voc/topics/{pl['clusters'][0]['id']}", headers={**ADMIN, "X-UI-Lang": "pl"}).json()
        assert topic["conversations"][0]["summary"].startswith("Powód: ")
        rc = c.get("/api/voc/repeat-churn", headers={**ADMIN, "X-UI-Lang": "pl"}).json()
        assert rc["definition"]["repeat"] == "ten sam klient i ta sama sprawa w ciągu 7 dni"
        pl_market = [r for r in c.get(f"/api/voc/evidence?ids={','.join(a for a in alert_pl['evidence'])}", headers={**ADMIN, "X-UI-Lang": "pl"}).json() if r["market"] == "PL"]
        assert all(r["text"] != r["summary"] and r["language"] == "pl" for r in pl_market)


def test_wfm_polish_queues_are_listed_planned_and_forecast_in_warsaw_time():
    with client() as c:
        qs = c.get("/api/wfm/queues", headers={**ADMIN, "X-UI-Lang": "pl"}).json()
        pl_q = [q for q in qs if q.get("timezone")]
        assert [q["queue"] for q in pl_q] == ["general-pl", "delivery-pl"] and all(q["timezone"] == "Europe/Warsaw" and q["market"] == "PL" and q["history_days"] == 90 for q in pl_q)
        assert pl_q[0]["name"] == "Obsługa ogólna (Polska, czas warszawski)" and qs[0]["name"] == "Obsługa ogólna"
        hist = c.get("/api/wfm/history?queue=general-pl", headers={**ADMIN, "X-UI-Lang": "pl"}).json()
        assert hist["timezone"] == "Europe/Warsaw" and hist["intervals"][0] == "00:00" and hist["intervals"][47] == "23:30" and {d["dow"] for d in hist["daily"]} == {"pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz."}
        assert any(d["event"] == "holiday" for d in hist["daily"])
        plan = c.post("/api/wfm/plan", json={"queue": "delivery-pl", "containment": 0.3, "day_offset": 2}, headers={**ADMIN, "X-UI-Lang": "pl"}).json()
        assert plan["timezone"] == "Europe/Warsaw" and plan["days"][0]["plan"]["totals"]["peak_agents"] >= 1 and plan["fte_week"] > 0
        fc = c.get("/api/wfm/forecast?queue=general-pl", headers={**ADMIN, "X-UI-Lang": "pl"}).json()
        assert fc["days"][0]["dow_label"] in {"pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz."} and fc["backtest"]["hw"]["mape_daily"] < 0.25
        assert fc["backtest"]["hw"]["mape_interval"] is None, "no half hour of a 42-contacts/day queue reaches the 10-contact floor: null, never NaN"
        assert c.get("/api/wfm/erlang?calls=100&aht=180&t=20&sl=0.8", headers=ADMIN).status_code == 200
        summary = c.get("/api/wfm/summary", headers=ADMIN).json()
        assert summary["fte_with_ai"] > 0, "the tenant totals still cover only the five global queues"


def test_reseed_endpoint_is_idempotent_with_polish_content():
    with client() as c:
        first = c.get("/api/kb/stats", headers=ADMIN).json()
        again = c.post("/api/admin/reseed", headers=ADMIN)
        assert again.status_code == 200
        second = c.get("/api/kb/stats", headers=ADMIN).json()
        assert first["documents"] == second["documents"] == 101 and first["chunks"] == second["chunks"]
        cust = c.get("/api/crm/customers", headers=ADMIN).json()
        assert {x["id"] for x in cust} >= {"CU-1009", "CU-1010", "CU-1011", "CU-1012", "CU-1013"} and sum(1 for x in cust if x["id"] == "CU-1009") == 1


def test_eval_scenarios_and_kb_documents_carry_their_content_language():
    with client() as c:
        sc = c.get("/api/evals/scenarios?suite=pl", headers=ADMIN).json()
        assert len(sc) == 31 and {s["language"] for s in sc} == {"pl"} and sc[0]["id"] == "PL-01"
        docs = c.get("/api/kb/docs", headers=ADMIN).json()
        assert {d["lang"] for d in docs} == {"en", "de", "pl"} and sum(1 for d in docs if d["lang"] == "pl") == 50


# ------------------------------------------------------------------------------------------------------------------ operator views in the request locale
def test_crm_orders_carry_their_currency_and_demo_notes_follow_the_locale():
    with client() as c:
        for lang, expected in (("pl", "PLN"), ("en", "PLN")):
            orders = c.get("/api/crm/customers/CU-1010/360", headers={**ADMIN, "X-UI-Lang": lang}).json()["orders"]
            assert {o["id"]: o["currency"] for o in orders}["CH-100360"] == expected and orders[0]["total"] is not None, "the amount and its currency travel together"
        english = c.get("/api/crm/customers/CU-1001/360", headers=ADMIN).json()["orders"]
        assert english and {o["currency"] for o in english} == {"EUR"}
        pl = {x["id"]: x["note"] for x in c.get("/api/crm/customers", headers={**ADMIN, "X-UI-Lang": "pl"}).json()}
        en = {x["id"]: x["note"] for x in c.get("/api/crm/customers", headers=ADMIN).json()}
        assert pl["CU-1009"] == "Persona demo: uszkodzona sofa (po polsku)" and pl["CU-1006"].startswith("Szczególna troska")
        assert en["CU-1009"] == "Demo persona: damaged sofa (Polish)" and en["CU-1001"] == "Demo persona: damaged sofa (German)", "English notes are the seeded texts"
        demo = [f"CU-{i}" for i in range(1001, 1014)]
        assert set(pl) == set(en) and all(pl[k] for k in demo) and sum(1 for k in demo if pl[k] == en[k]) == 1, "every demo persona has a Polish note; only 'VIP' reads the same in both languages"


async def test_crm_timeline_titles_for_notes_and_tasks_are_rendered_in_the_request_locale():
    svc = build_services(Settings(mode="offline"))
    await svc.start()
    await svc.backoffice.seed()
    try:
        crm = svc.ext["crm"]
        await crm.write_note("CU-1009", "Klientka zgłosiła uszkodzenie sofy.", "cv_x")
        await crm.write_task("CU-1009", "Oddzwonić do klientki w sprawie odbioru", "AG-03", 1, "cv_x")
        with i18n.use_locale("pl"):
            titles = {e["type"]: e["title"] for e in await crm.timeline("CU-1009") if e["type"] in ("note", "task")}
        assert titles == {"note": "Notatka CRM", "task": "Zadanie: Oddzwonić do klientki w sprawie odbioru"}
        titles = {e["type"]: e["title"] for e in await crm.timeline("CU-1009") if e["type"] in ("note", "task")}
        assert titles == {"note": "CRM note", "task": "Task: Oddzwonić do klientki w sprawie odbioru"}, "English keeps the historic titles"
    finally:
        await svc.stop()


def test_output_check_returns_the_safe_replacement_in_the_request_or_body_language():
    from concierge.engine.guard import SAFE_REPLACEMENT

    risky = "Gwarantujemy zwrot 100 % pieniędzy w ciągu 24 godzin."
    with client() as c:
        pl = c.post("/api/compliance/output-check", json={"text": risky}, headers={**ADMIN, "X-UI-Lang": "pl"}).json()
        assert pl["text"] == SAFE_REPLACEMENT["pl"] and pl["risky_promises"], pl
        assert c.post("/api/compliance/output-check", json={"text": risky, "language": "en"}, headers={**ADMIN, "X-UI-Lang": "pl"}).json()["text"] == SAFE_REPLACEMENT["en"], "an explicit language wins"
        en = c.post("/api/compliance/output-check", json={"text": "We guarantee a 100% refund within 24 hours."}, headers=ADMIN).json()
        assert en["text"] == SAFE_REPLACEMENT["en"] and en["risky_promises"]


def test_demo_traffic_fills_a_polish_console_with_polish_customers_and_leaves_the_english_pool_alone():
    from concierge.features.supervisor import DEMO_SCRIPTS, DEMO_SCRIPTS_PL

    assert len(DEMO_SCRIPTS) == 8 and sum(1 for s in DEMO_SCRIPTS if s[0] == "pl") == 1, "the English demo pool is the historic one"
    assert {s[0] for s in DEMO_SCRIPTS_PL} == {"pl"} and any("UOKiK" in s[2] for s in DEMO_SCRIPTS_PL)
    sup = {"X-Demo-Role": "supervisor"}
    with client() as c:
        pl = c.post("/api/supervisor/demo-traffic", json={"count": 4}, headers={**sup, "X-UI-Lang": "pl"}).json()["started"]
        assert len(pl) == 4 and {s["language"] for s in pl} == {"pl"}
        en = c.post("/api/supervisor/demo-traffic", json={"count": 8}, headers=sup).json()["started"]
        assert {s["language"] for s in en} <= {s[0] for s in DEMO_SCRIPTS} and len({s["language"] for s in en}) >= 5


# ------------------------------------------------------------------------------------------------------------------ Polish typography and slice upgrades
def test_polish_typography_helper_joins_one_letter_words_numbers_and_currencies_idempotently():
    out = i18n.nbsp_pl("Zwrot w ciągu 5–7 dni i o 2 150 zł (ok. 500 EUR) a także z 30% rabatem.\nKeywords (en): a w 5 dni.")
    first, second = out.split("\n")
    assert first == "Zwrot w\u00a0ciągu 5–7 dni i\u00a0o\u00a02\u00a0150\u00a0zł (ok.\u00a0500\u00a0EUR) a\u00a0także z\u00a030% rabatem."
    assert second == "Keywords (en): a w 5 dni.", "the English keyword line of an article is left alone"
    assert i18n.nbsp_pl(out) == out and "30\u00a0dni" not in i18n.nbsp_pl("w ciągu 30 dni"), "idempotent; `30 dni` keeps its ordinary space"


async def test_bumping_the_polish_slice_version_refreshes_the_stored_polish_fields_and_nothing_else():
    """The deployed data was patched by an earlier slice version (older wording): a version bump alone must upgrade it, once."""
    svc = build_services(Settings(mode="offline"))
    await svc.start()
    try:
        await history_seed.seed_history(svc)
        meta = await svc.repo.get("seed_meta", "history")
        rows = {r["id"]: r for r in await svc.repo.query("history", limit=6000)}
        for r in rows.values():
            await svc.repo.put("history", {**{k: v for k, v in r.items() if k not in ("pk", "_ts")}, "summary_pl": "stare sformułowanie"})
        await svc.repo.put("seed_meta", {**{k: v for k, v in meta.items() if k not in ("pk", "_ts")}, "pl_slice": "pl1"})
        upgraded = await history_seed.seed_history(svc)
        assert upgraded["pl_slice"]["patched_records"] == len(rows)
        after = await svc.repo.query("history", limit=6000)
        assert all(r["summary_pl"] == rows[r["id"]]["summary_pl"] and r["summary"] == rows[r["id"]]["summary"] for r in after), "Polish fields are back at the current wording; English fields untouched"
        assert (await svc.repo.get("seed_meta", "history"))["pl_slice"] == "pl2"
        assert "pl_slice" not in await history_seed.seed_history(svc), "and it runs once"
    finally:
        await svc.stop()
