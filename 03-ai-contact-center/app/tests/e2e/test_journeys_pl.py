"""Polish end-to-end journeys (UI language PL, Polish conversations) in a real browser: the language switch and its plumbing (header switch on every page, persistence,
?lang=, <html lang>, no reload, Accept-Language / X-UI-Lang on every API call, ?lang= on WebSocket URLs, refetch on switch), the golden Polish customer journey
(widget chat -> OTP -> damage policy with citations -> refund in PLN with confirmation), warm handoff, voice page, supervisor, QA workbench, VoC, WFM, evaluation
harness, KB admin, CX metrics / ROI calculator, feature map and a full crawl of every route at 1600x900 and 1280x720.

Every page is checked for: no English leftover, no missing translation (`window.__i18nMissing`), no horizontal overflow / clipped text, a clean console.
Run:   pytest tests/e2e/test_journeys_pl.py -o addopts="" -q
       E2E_BASE_URL=https://<live-app> pytest tests/e2e/test_journeys_pl.py -o addopts="" -q     (the same journeys against a running / deployed app)
Screenshots (1600x900) go to ../deck/assets/screens-pl/NN-<view>.png (E2E_PL_SHOTS_DIR overrides, E2E_NO_PL_SHOTS=1 disables)."""

from __future__ import annotations

import os
import re
import time

import pytest
from e2e_env import LIVE, ai, poll
from i18n_helpers import (
    assert_polish,
    assert_text_polish,
    assert_transcript_polish,
    looks_english,
    missing_keys,
    overflow,
)
from journey_helpers import confirm_cards_until, prepare_demo_refund, refunded, voice_ask, wait_quiet
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

NBSP = "\u00a0"
ZL = rf"[\s{NBSP}]zł"  # "1 599,00 zł" with NBSP / thin spaces
AMOUNT_1599 = re.compile(rf"1[\s{NBSP}.]?599(?:,00)?[\s{NBSP}]?(?:zł|PLN)")  # however the model writes the golden amount
DAYS = re.compile(r"\b(?:14|30|czternastu|trzydziestu|czternaście|trzydzieści)[\s-]*(?:dni|dniow\w+)", re.I)  # "30 dni", "14 dni", "30-dniowy"
NAV_ROUTES = ["/", "/features", "/settings", "/agent", "/supervisor", "/routing", "/customers", "/i18n", "/qa", "/kb", "/compliance", "/identity", "/tools", "/metrics", "/voc", "/wfm", "/outbound", "/observability", "/evals", "/rollout", "/security", "/deployment"]
BARE_ROUTES = ["/widget", "/call"]
CUSTOMER = {"X-Demo-Role": "customer"}


def log(page: Page):
    return page.get_by_role("log", name="Rozmowa")


def say(page: Page, text: str) -> None:
    page.locator("#msg").fill(text)
    page.get_by_role("button", name="Wyślij").click()


def wait_idle(page: Page, timeout: int | None = None) -> None:
    expect(page.get_by_label("Asystent pisze")).to_have_count(0, timeout=timeout or ai(30000))


def settle(page: Page, ms: int = 600) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightTimeoutError:  # a deployed app polls and streams: it may never be network-idle, the page is rendered anyway
        pass
    page.wait_for_timeout(ms)


def go(page: Page, base_url: str, route: str, lang: str = "pl") -> None:
    sep = "&" if "?" in route else "?"
    page.goto(f"{base_url}{route}{sep}lang={lang}")
    settle(page)


def number(text: str) -> float:
    return float(re.sub(r"[\s\u00a0]", "", text).replace(",", "."))


# ================================================================================================ language switch & plumbing
def test_pl_language_switch_is_in_every_header_remembered_and_needs_no_reload(page: Page, base_url: str):
    page.goto(f"{base_url}/")
    settle(page)
    assert page.evaluate("document.documentElement.lang") == "en"
    switch = page.get_by_test_id("ui-lang")
    expect(switch).to_be_visible()
    assert switch.get_attribute("aria-label") == "Interface language"
    page.evaluate("window.__marker = 'same document'")  # survives only while no reload happens
    requests: list[dict] = []
    page.on("request", lambda r: requests.append({"url": r.url, "headers": r.headers}) if "/api/" in r.url else None)
    switch.select_option("pl")
    expect(page.get_by_role("heading", name="Concierge — centrum kontaktu oparte na AI")).to_be_visible()
    settle(page)
    assert page.evaluate("window.__marker") == "same document", "switching the language must not reload the page"
    assert page.evaluate("document.documentElement.lang") == "pl"
    assert page.evaluate("localStorage.getItem('concierge.lang')") == "pl"
    assert page.title() == "Concierge · Centrum kontaktu AI"
    assert page.get_by_test_id("ui-lang").get_attribute("aria-label") == "Język interfejsu"
    # every API call after the switch is made in Polish, and server data was refetched (not just re-labelled)
    assert requests, "the switch refetches the API data"
    assert all(r["headers"].get("x-ui-lang") == "pl" and r["headers"].get("accept-language", "").startswith("pl") for r in requests), requests[:3]
    assert any(r["url"].endswith("/api/meta") for r in requests)
    assert_polish(page, where="/ after the switch")
    # remembered across a reload; ?lang= wins over the saved choice and is remembered itself
    page.reload()
    settle(page)
    assert page.evaluate("document.documentElement.lang") == "pl"
    page.goto(f"{base_url}/?lang=en")
    settle(page)
    assert page.evaluate("document.documentElement.lang") == "en"
    assert page.evaluate("localStorage.getItem('concierge.lang')") == "en"
    expect(page.get_by_role("heading", name="Concierge — the AI-first contact center")).to_be_visible()


def test_pl_browser_language_is_the_default_when_nothing_is_saved(pl_page: Page, base_url: str):
    pl_page.goto(f"{base_url}/")  # context locale pl-PL, no ?lang=, empty localStorage
    settle(pl_page)
    assert pl_page.evaluate("document.documentElement.lang") == "pl"
    expect(pl_page.get_by_role("heading", name="Concierge — centrum kontaktu oparte na AI")).to_be_visible()


@pytest.mark.parametrize("route", NAV_ROUTES)
def test_pl_every_console_page_has_the_language_switch_in_its_header(pl_page: Page, base_url: str, route: str):
    go(pl_page, base_url, route)
    expect(pl_page.get_by_test_id("ui-lang").first).to_be_visible()
    assert pl_page.get_by_test_id("ui-lang").first.input_value() == "pl"
    assert pl_page.evaluate("document.documentElement.lang") == "pl"


def test_pl_customer_pages_carry_their_own_language_selector(pl_page: Page, base_url: str):
    go(pl_page, base_url, "/widget")
    expect(pl_page.get_by_test_id("widget-lang")).to_have_value("pl")
    go(pl_page, base_url, "/call")
    expect(pl_page.get_by_label("Język").first).to_be_visible()


def test_pl_websockets_and_downloads_carry_the_language(pl_page: Page, base_url: str):
    go(pl_page, base_url, "/widget")
    with pl_page.expect_event("websocket", lambda ws: "/ws/chat/" in ws.url, timeout=20000) as ws_info:  # the socket opens right after the greeting renders: wait for it
        pl_page.get_by_role("button", name="Akceptuję i zaczynam").click()
    expect(log(pl_page)).to_contain_text("asystent AI", timeout=15000)
    assert "lang=pl" in ws_info.value.url, ws_info.value.url
    link = pl_page.get_by_role("link", name="Transkrypcja")
    assert "lang=pl" in (link.get_attribute("href") or "")


def test_pl_widget_language_selector_sets_both_the_labels_and_the_conversation_language(page: Page, base_url: str, api):
    page.goto(f"{base_url}/widget?lang=en")
    settle(page)
    expect(page.get_by_role("heading", name="Before we start")).to_be_visible()
    page.get_by_test_id("widget-lang").select_option("pl")
    expect(page.get_by_role("heading", name="Zanim zaczniemy")).to_be_visible()
    assert page.evaluate("document.documentElement.lang") == "pl", "Polish is a UI language: the whole app follows the widget selector"
    page.get_by_role("button", name="Akceptuję i zaczynam").click()
    expect(log(page)).to_contain_text("asystent AI", timeout=15000)
    sid = re.search(r"c=(cv_[0-9a-f]+)", page.get_by_role("link", name="Zadzwoń do nas").get_attribute("href") or "").group(1)
    assert api.get(f"/api/chat/sessions/{sid}", headers=CUSTOMER).json()["session"]["language"] == "pl"
    # a language that is not a UI language only changes the conversation (and the widget's built-in labels)
    page.goto(f"{base_url}/widget?lang=en")
    settle(page)
    page.get_by_test_id("widget-lang").select_option("de")
    expect(page.get_by_role("heading", name="Bevor wir starten")).to_be_visible()
    assert page.evaluate("document.documentElement.lang") == "en"
    page.get_by_role("button", name="Akzeptieren & starten").click()
    expect(page.get_by_role("log", name="Conversation")).to_contain_text("KI-Assistenten", timeout=15000)  # German keeps the English accessible names


# ================================================================================================ golden Polish customer journey
def test_pl_gj1_widget_chat_resolves_a_damaged_sofa_with_a_refund_in_pln(pl_page: Page, base_url: str, api, pl_shot):
    page = pl_page
    prepare_demo_refund(api, base_url, "CU-1009", reset_when_local=True)  # a golden journey refunds the demo order once; a deployed app is never reset by the suite
    go(page, base_url, "/widget")
    expect(page.get_by_role("heading", name="Zanim zaczniemy")).to_be_visible()
    assert_polish(page, where="/widget consent")
    page.get_by_role("button", name="Akceptuję i zaczynam").click()
    # AI disclosure + recording notice in Polish (formal register), simulated phone and suggestions in Polish
    expect(log(page)).to_contain_text("asystent AI", timeout=15000)
    expect(log(page)).to_contain_text("nagrywana")
    sid = re.search(r"c=(cv_[0-9a-f]+)", page.get_by_role("link", name="Zadzwoń do nas").get_attribute("href") or "").group(1)
    say(page, "Dzień dobry, moja sofa dotarła uszkodzona. Numer zamówienia CH-100350.")
    code_btn = page.get_by_label("Symulowany telefon").get_by_role("button", name=re.compile(r"^\d{6}$"))
    expect(code_btn).to_be_visible(timeout=ai(20000))
    expect(page.get_by_label("Symulowany telefon")).to_contain_text("kod weryfikacyjny")
    code_btn.click()
    page.get_by_role("button", name="Wyślij").click()
    expect(log(page)).to_contain_text(AMOUNT_1599, timeout=ai(30000))  # the model quotes the order in PLN
    expect(page.get_by_text("Zweryfikowano L1")).to_be_visible(timeout=ai(15000))
    kb_chip = log(page).locator("span[title]").filter(has_text=re.compile(r"^K\d+\s+\S"))
    expect(kb_chip.first).to_be_visible(timeout=ai(15000))  # a Polish KB article is cited
    say(page, "Poproszę o zwrot środków, pierwszy termin odbioru mi odpowiada.")
    shot_taken: list[bool] = []

    def on_card(text: str) -> None:
        page.wait_for_timeout(400)
        assert_polish(page, where="/widget confirmation", allow_english=("Mastercard",))
        if "Mastercard" in text and not shot_taken:  # the refund plan names the card
            shot_taken.append(True)
            pl_shot("01-customer-widget-chat")

    # the stub proposes return, pickup and refund in one card, a real model one card at a time: confirm until the refund tool has run
    cards = confirm_cards_until(
        page,
        card_name="Prosimy o potwierdzenie tej czynności",
        confirm_name="Potwierdź",
        typing_label="Asystent pisze",
        done=lambda: refunded(api, "CU-1009"),
        nudge=lambda: say(page, "Tak, proszę o realizację zwrotu środków."),
        on_card=on_card,
    )
    plan = "\n".join(cards)
    assert AMOUNT_1599.search(plan), f"the plan quotes the refund in PLN: {cards}"
    assert "Mastercard" in plan and "2245" in plan, f"the refund plan names the card ending 2245: {cards}"
    expect(page.get_by_role("group", name="Prosimy o potwierdzenie tej czynności")).to_have_count(0, timeout=ai(30000))
    wait_idle(page)
    page.wait_for_timeout(500)
    say(page, "Nie, dziękuję, to wszystko.")
    expect(page.locator("#msg")).to_be_disabled(timeout=ai(30000))
    assert_transcript_polish(page, where="/widget transcript", allow_english=("Mastercard",))
    pl_shot("01-customer-widget-resolved")
    deadline = time.time() + ai(40000) / 1000
    refunds: list[dict] = []
    while time.time() < deadline and not refunds:  # wrap-up and QA run in the background after the customer says goodbye
        timeline = api.get("/api/crm/customers/CU-1009/360", headers={"X-UI-Lang": "pl"}).json()["timeline"]
        refunds = [e for e in timeline if e["type"] == "refund"]
        time.sleep(poll(0.5))
    assert len(refunds) == 1 and AMOUNT_1599.search(refunds[0]["title"] + refunds[0].get("detail", "")), refunds
    review: dict = {}
    deadline = time.time() + ai(60000) / 1000
    while time.time() < deadline and not review:  # the QA review of THIS conversation appears after the (model-assisted) scoring
        reviews = api.get("/api/qa/reviews", headers={"X-Demo-Role": "qa"}).json()
        review = next((r for r in (reviews["reviews"] if isinstance(reviews, dict) else reviews) if r.get("conversation_id") == sid), {})
        time.sleep(poll(1))
    assert review.get("disposition") == "RESOLVED_REFUND_ISSUED" and review.get("language") == "pl", f"the Polish conversation is auto-scored: {review}"


def test_pl_widget_does_not_guess_and_hands_over_to_a_colleague(pl_page: Page, base_url: str, pl_shot):
    page = pl_page
    go(page, base_url, "/widget")
    page.get_by_role("button", name="Akceptuję i zaczynam").click()
    expect(log(page)).to_contain_text("asystent AI", timeout=ai(15000))
    say(page, "Chcę porozmawiać z konsultantem.")
    expect(page.get_by_text(re.compile("Konsultant dołączy za chwilę"))).to_be_visible(timeout=ai(30000))
    expect(log(page)).to_contain_text(re.compile("konsultant", re.I))
    assert_polish(page, where="/widget handoff")
    assert_transcript_polish(page, where="/widget handoff transcript")


def test_pl_agent_console_warm_handoff_with_context_package_and_agent_assist(pl_page: Page, base_url: str, api, pl_shot):
    page = pl_page
    created = api.post("/api/chat/sessions", json={"language": "pl", "recording_consent": "granted"}, headers={**CUSTOMER, "X-UI-Lang": "pl"})
    assert created.status_code == 200, created.text
    sid = created.json()["session"]["id"]
    sent = api.post(f"/api/chat/sessions/{sid}/messages", json={"text": "To skandal! Jeśli pralka CH-100250 nie zostanie zamontowana, zwrócę się do prawnika.", "language": "pl"}, headers=CUSTOMER)
    assert sent.status_code == 200, sent.text
    deadline = time.time() + ai(30000) / 1000
    while time.time() < deadline and not (api.get(f"/api/chat/sessions/{sid}", headers=CUSTOMER).json()["session"].get("handoff") or {}).get("queue"):
        time.sleep(poll(0.5))  # the hand-off (and its context package) exists before the console opens the conversation
    go(page, base_url, f"/agent?conversation={sid}")
    expect(page.get_by_role("heading", name="Konsola konsultanta")).to_be_visible()
    expect(page.get_by_text("groźba prawna").first).to_be_visible(timeout=ai(15000))
    expect(page.get_by_text("Pakiet kontekstu").first).to_be_visible(timeout=ai(15000))
    page.get_by_role("button", name="Przyjmij", exact=True).click(timeout=ai(15000))
    expect(page.locator("#reply")).to_be_enabled(timeout=ai(15000))
    expect(page.get_by_text("Agent Assist").first).to_be_visible(timeout=ai(15000))
    wait_quiet(page, ai(30000))  # the suggestions are written by the model: scan the page once they are there
    assert_polish(page, where="/agent", allow_english=("Agent Assist",))
    assert_transcript_polish(page, where="/agent transcript")
    handoff_card = page.locator("section").filter(has=page.get_by_role("heading", name="Powód przekazania"))
    assert_text_polish(handoff_card.locator("p").first.inner_text(), where="/agent hand-off summary")  # the model-written summary
    pl_shot("02-agent-console-handoff")
    page.locator("#reply").fill("Dzień dobry, mówi Hanna. Przepraszam za kłopot, właśnie sprawdzam Pani zamówienie.")
    send = page.get_by_role("button", name="Wyślij", exact=True)
    expect(send).to_be_enabled(timeout=ai(15000))
    send.click()
    deadline = time.time() + ai(15000) / 1000
    session = {}
    while time.time() < deadline:
        session = api.get(f"/api/chat/sessions/{sid}", headers=CUSTOMER).json()["session"]
        if any(m["role"] == "agent_human" for m in session["messages"]):
            break
        time.sleep(poll(0.3))
    assert any(m["role"] == "agent_human" for m in session["messages"])
    assert session["language"] == "pl" and (session["handoff"] or {}).get("queue") == "escalations"


def test_pl_voice_page_text_path_shows_polish_captions_and_latency(pl_page: Page, base_url: str, pl_shot):
    page = pl_page
    go(page, base_url, "/call")
    expect(page.get_by_role("tab", name="Rozmowa głosowa")).to_be_visible()
    assert_polish(page, where="/call idle", check_overflow=False)
    page.get_by_role("button", name="Rozpocznij rozmowę").first.click()
    expect(page.get_by_text(re.compile("Concierge")).first).to_be_visible(timeout=ai(20000))
    # the call opens with the AI disclosure and the recording consent, spoken in the caller's language (not a canned English line);
    # the real Realtime model speaks it for ~20 s before the caption arrives
    greeting = re.compile(r"Dzień dobry.*(?:asystent|AI).*nagryw", re.S | re.I)
    expect(page.get_by_text(greeting).first).to_be_visible(timeout=ai(20000))
    assert "How can I help" not in page.locator("body").inner_text()
    # the answer's caption is phrased and paced by the model (up to ~90 s live): any of the policy periods, in Polish
    voice_ask(page, "Jakie są zasady zwrotów?", DAYS, placeholder=re.compile("Wpisz tekst", re.I), greeting=greeting, listening="słucha")
    page.wait_for_timeout(500)
    assert_transcript_polish(page, where="/call captions")
    pl_shot("10-customer-voice-call")
    page.get_by_role("tab", name=re.compile("Adaptery telefonii")).click()
    expect(page.get_by_text(re.compile("SIP")).first).to_be_visible()
    page.get_by_role("button", name="Rozmowa o uszkodzonej sofie").click()
    expect(page.get_by_text("realtime.call.incoming")).to_be_visible(timeout=ai(30000))
    pl_shot("10b-telephony-adapters-simulator")
    assert not missing_keys(page), missing_keys(page)


# ================================================================================================ operator consoles in Polish
def test_pl_supervisor_console_shows_queues_alerts_and_live_conversations(pl_page: Page, base_url: str, api, pl_shot):
    page = pl_page
    created = api.post("/api/supervisor/demo-traffic", json={"count": 2 if LIVE else 6}, headers={"X-UI-Lang": "pl"})  # on a deployed app every demo conversation is a real model run
    assert created.status_code == 200, created.text
    go(page, base_url, "/supervisor")
    expect(page.get_by_role("heading", name="Konsola supervisora")).to_be_visible()
    expect(page.get_by_text(re.compile("Kolejki i zegary SLA"))).to_be_visible(timeout=15000)
    expect(page.get_by_text("Ogólna obsługa klienta").first).to_be_visible()
    page.wait_for_timeout(800)
    assert_polish(page, where="/supervisor")
    pl_shot("03-supervisor-console")


def test_pl_qa_workbench_lists_scored_conversations_with_polish_evidence(pl_page: Page, base_url: str, pl_shot):
    page = pl_page
    go(page, base_url, "/qa")
    expect(page.get_by_role("heading", name="Stanowisko QA")).to_be_visible()
    expect(page.get_by_text(re.compile("zgodność|kappa|kalibr", re.I)).first).to_be_visible(timeout=15000)
    page.wait_for_timeout(600)
    assert_polish(page, where="/qa dashboard")
    pl_shot("04-qa-workbench")
    page.get_by_role("tab", name=re.compile("Oceny")).click()
    page.wait_for_timeout(600)
    rows = page.locator("table tbody tr")
    assert rows.count() > 0
    rows.first.click()
    page.wait_for_timeout(800)
    assert_polish(page, where="/qa review")


def test_pl_voc_insights_flags_the_nordfreight_damage_spike(pl_page: Page, base_url: str, pl_shot):
    page = pl_page
    go(page, base_url, "/voc")
    expect(page.get_by_role("heading", name="Analityka głosu klienta (VoC)")).to_be_visible()
    expect(page.get_by_text("NordFreight").first).to_be_visible(timeout=30000)
    expect(page.get_by_text(re.compile("Nowy problem", re.I)).first).to_be_visible()
    expect(page.get_by_text(re.compile("Uszkodzenie przy dostawie")).first).to_be_visible()  # driver label localised by the server
    assert re.search(r"pierwsze wystąpienie: \d{2}\.\d{2}\.\d{4}", page.locator("main").inner_text()), "dates are dd.mm.yyyy"
    assert re.search(r"\d,\d+/dzień", page.locator("main").inner_text()), "decimal comma in rates"
    page.wait_for_timeout(600)
    assert_polish(page, where="/voc", allow_english=("H-0",))
    pl_shot("05-voc-insights")
    page.get_by_role("button", name="Rozmowy źródłowe").first.click()
    page.wait_for_timeout(700)
    assert_polish(page, where="/voc evidence")


def pl_plural(n: int, one: str, few: str, many: str) -> str:
    """CLDR plural rule of Polish for integers (the browser's Intl.PluralRules must agree)."""
    if n == 1:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def test_pl_plural_forms_follow_the_cldr_rules_for_polish(pl_page: Page, base_url: str, api):
    page = pl_page
    if not LIVE:  # offline the feed starts empty; on a deployed app it already carries events and every demo conversation would be a real model run
        api.post("/api/supervisor/demo-traffic", json={"count": 2})
    go(page, base_url, "/supervisor")
    badge = page.get_by_text(re.compile(r"kanał na żywo · \d+")).first
    expect(badge).to_be_visible(timeout=ai(15000))
    m = re.search(r"kanał na żywo · (\d+) (\w+)", badge.inner_text())
    assert m, badge.inner_text()
    n, noun = int(m.group(1)), m.group(2)
    assert noun == pl_plural(n, "zdarzenie", "zdarzenia", "zdarzeń"), f"{n} {noun}"
    # the same rule for every count the browser can produce: 1 / 2-4 / 5-21 / 22-24 / 25 / 112
    forms = page.evaluate(
        """() => { const r = new Intl.PluralRules('pl'); return [0, 1, 2, 4, 5, 12, 21, 22, 25, 112, 1.5].map((n) => r.select(n)); }"""
    )
    assert forms == ["many", "one", "few", "few", "many", "many", "many", "few", "many", "many", "other"]


def test_pl_customer_360_search_ignores_diacritics_and_shows_prices_in_zloty(pl_page: Page, base_url: str, pl_shot):
    page = pl_page
    go(page, base_url, "/customers")
    box = page.get_by_placeholder("imię i nazwisko, e-mail, ID, rynek…")
    box.fill("wisniewski")  # no diacritics typed on a phone: finds "Wiśniewski"
    expect(page.get_by_role("button", name=re.compile("Tomasz Wiśniewski"))).to_be_visible(timeout=15000)
    expect(page.get_by_role("button", name=re.compile("Kowalsk"))).to_have_count(0, timeout=15000)  # the list is filtered, not just scrolled
    page.get_by_role("button", name=re.compile("Tomasz Wiśniewski")).click()
    expect(page.get_by_text("CU-1010 · PL · polski")).to_be_visible(timeout=15000)
    # a Polish customer's order is a PLN amount, never shown with the euro sign (3 849,00 zł, NBSP grouping)
    expect(page.get_by_role("cell", name=re.compile(r"^3\s849,00\szł$"))).to_be_visible()
    assert page.get_by_role("cell", name=re.compile("€")).count() == 0
    assert_polish(page, where="/customers PL customer")


def test_pl_wfm_forecast_staffing_and_containment_what_if(pl_page: Page, base_url: str, pl_shot):
    page = pl_page
    go(page, base_url, "/wfm")
    expect(page.get_by_role("heading", name=re.compile("Prognoza i obsada"))).to_be_visible()
    expect(page.get_by_text(re.compile("Symulowany poziom obsługi", re.I))).to_be_visible(timeout=30000)

    def fte() -> float:
        m = re.search(r"Etaty konsultantów \(tydzień\)\s*(\d[\d\u00a0 ]*(?:,\d+)?)", page.locator("main").inner_text())
        assert m, "the staffing KPI is on the page"
        return number(m.group(1))

    before = fte()
    slider = page.get_by_role("slider").first
    slider.focus()
    for _ in range(25):
        slider.press("ArrowRight")
    page.wait_for_timeout(1500)
    assert fte() < before, "more AI containment reduces the human staffing requirement"
    assert_polish(page, where="/wfm")
    pl_shot("06-wfm-forecast-staffing")


def test_pl_eval_harness_runs_the_polish_pack_and_the_gate_blocks_a_broken_prompt(pl_page: Page, base_url: str, pl_shot):
    page = pl_page
    # a real model needs minutes (and ~US$1) for the 31 Polish scenarios, and twice that for a gate: a deployed app runs the 8-scenario Polish smoke suite for both - the
    # run stores the baseline the gate compares with. The harness, its Polish report and the blocking gate are the same; the offline stub runs the whole Polish pack.
    run_suite, gate_suite = ("pl-smoke", "pl-smoke") if LIVE else ("pl", "pl")
    go(page, base_url, "/evals")
    expect(page.get_by_role("heading", name=re.compile("Środowisko oceny"))).to_be_visible()
    page.get_by_label("Zestaw", exact=True).select_option(run_suite)
    page.get_by_role("button", name="Uruchom zestaw").click()
    expect(page.get_by_text(re.compile(r"Raport · run_")).first).to_be_visible(timeout=ai(120000))  # the finished report (not the progress card)
    expect(page.get_by_text(re.compile(r"\d+/\d+ scenariusz", re.I)).first).to_be_visible()
    page.wait_for_timeout(600)
    assert_polish(page, where="/evals report", allow_english=("PL-",))
    pl_shot("07-eval-harness-report")
    page.get_by_role("tab", name=re.compile("Bramka CI")).click()
    page.get_by_label("Zestaw dla bramki").select_option(gate_suite)
    page.get_by_role("button", name="Wstrzyknij zepsuty prompt i uruchom bramkę").click()
    expect(page.get_by_text(re.compile("NIEZALICZONA — wdrożenie zablokowane")).first).to_be_visible(timeout=ai(120000))
    page.wait_for_timeout(600)
    assert_polish(page, where="/evals gate", allow_english=("PL-",))
    pl_shot("07b-eval-harness-ci-gate")
    assert not missing_keys(page), missing_keys(page)


def test_pl_kb_admin_lists_polish_articles_and_answers_with_citations(pl_page: Page, base_url: str, pl_shot):
    page = pl_page
    go(page, base_url, "/kb")
    expect(page.get_by_role("heading", name="Administracja bazą wiedzy")).to_be_visible()
    expect(page.get_by_text("Zasady zwrotów (30 dni)").first).to_be_visible(timeout=ai(15000))
    expect(page.get_by_test_id("kb-doc-lang")).to_have_value("pl")
    assert_polish(page, where="/kb documents")
    pl_shot("09-agent-studio-kb-admin")
    page.get_by_test_id("kb-doc-lang").select_option("en")
    expect(page.get_by_text("Returns policy (30 days)").first).to_be_visible()  # English articles stay available (content, tagged EN)
    page.get_by_role("tab", name=re.compile("Test")).click()
    page.get_by_role("textbox").first.fill("Ile dni mam na zwrot towaru?")
    page.get_by_role("button", name="Zapytaj").first.click()
    expect(page.get_by_text(DAYS).first).to_be_visible(timeout=ai(30000))  # the answer is written by the model from the Polish article: any of its periods
    assert not missing_keys(page), missing_keys(page)


def test_pl_cx_metrics_and_the_roi_acr_calculator_recompute_with_polish_labels(pl_page: Page, base_url: str, pl_shot):
    page = pl_page
    go(page, base_url, "/metrics")
    expect(page.get_by_role("heading", name="Metryki CX i ROI")).to_be_visible()
    expect(page.get_by_text("Obsługa w całości przez AI").first).to_be_visible(timeout=20000)
    assert_polish(page, where="/metrics operations")
    pl_shot("08-cx-roi-dashboard")
    page.get_by_role("tab", name=re.compile("ROI")).click()
    expect(page.get_by_text(re.compile(r"NPV", re.I)).first).to_be_visible(timeout=20000)
    expect(page.get_by_text(re.compile("mln USD")).first).to_be_visible()  # Polish number / currency formatting of the model output
    base_text = page.locator("main").inner_text()
    seats = page.get_by_label(re.compile("stanowisk", re.I)).first
    seats.fill("3000")
    seats.press("Enter")
    page.wait_for_timeout(1500)
    assert page.locator("main").inner_text() != base_text, "changing an assumption recomputes the model"
    assert_polish(page, where="/metrics ROI")
    pl_shot("08b-roi-acr-calculator")


def hover_tooltips(page: Page, charts: int = 3) -> list[str]:
    """Hover the middle of the first charts of the page and return the text of every tooltip that showed up."""
    texts: list[str] = []
    wrappers = page.locator(".recharts-wrapper")
    for i in range(min(wrappers.count(), charts)):
        chart = wrappers.nth(i)
        chart.scroll_into_view_if_needed()
        box = chart.bounding_box()
        if not box:
            continue
        for fx in (0.35, 0.5, 0.65, 0.8):
            page.mouse.move(box["x"] + box["width"] * fx, box["y"] + box["height"] * 0.5)
            page.wait_for_timeout(250)
            tip = chart.locator(".recharts-tooltip-wrapper")
            if tip.count() and tip.first.is_visible() and tip.first.inner_text().strip():
                texts.append(tip.first.inner_text().strip())
                break
    return texts


@pytest.mark.parametrize("route", ["/metrics", "/wfm"])
def test_pl_chart_tooltips_follow_the_polish_text_and_number_formats(pl_page: Page, base_url: str, route: str):
    page = pl_page
    go(page, base_url, route)
    if route == "/metrics":
        page.get_by_role("tab", name=re.compile("ROI")).click()
        expect(page.get_by_text(re.compile("mln USD")).first).to_be_visible(timeout=20000)
    else:
        expect(page.get_by_text(re.compile("Symulowany poziom obsługi", re.I))).to_be_visible(timeout=30000)
    page.wait_for_timeout(800)
    tips = hover_tooltips(page)
    assert tips, f"a tooltip shows on hover of a chart of {route}"
    for tip in tips:
        assert not looks_english(tip), f"English in a chart tooltip: {tip!r}"
        assert not re.search(r"\$\s?\d|\d,\d{3}\.\d", tip), f"US number format in a chart tooltip: {tip!r}"
    assert not missing_keys(page), missing_keys(page)


def test_pl_feature_map_lists_all_24_features_with_polish_names(pl_page: Page, base_url: str, pl_shot):
    page = pl_page
    go(page, base_url, "/features")
    expect(page.get_by_role("heading", name="Mapa funkcji")).to_be_visible()
    for i in (1, 2, 12, 16, 24):
        expect(page.get_by_text(f"CC-{i:02d}").first).to_be_visible(timeout=15000)
    assert len(page.get_by_text(re.compile(r"^CC-\d\d$")).all()) >= 24
    assert_polish(page, where="/features")
    pl_shot("11-feature-map")


@pytest.mark.parametrize(
    ("route", "name", "title"),
    [
        ("/outbound", "12-outbound-proactive", "Kontakt proaktywny"),
        ("/security", "13-security-rbac", "Bezpieczeństwo"),
        ("/observability", "14-observability-finops", "Obserwowalność"),
        ("/routing", "15-routing-escalation", "Routing"),
        ("/customers", "16-customer-360-crm", "Klient 360"),
        ("/rollout", "17-rollout-llmops", "Zarządzanie promptami"),
        ("/compliance", "18-compliance-guard", "Zgodność i ochrona przed ryzykiem"),
    ],
)
def test_pl_remaining_screens_are_polish_and_captured(pl_page: Page, base_url: str, pl_shot, route: str, name: str, title: str):
    page = pl_page
    go(page, base_url, route)
    expect(page.get_by_role("heading", name=re.compile(title)).first).to_be_visible(timeout=20000)
    page.wait_for_timeout(500)
    assert_polish(page, where=route)
    pl_shot(name)


# ================================================================================================ full crawl: every route, every tab
def _tabs(page: Page) -> list[str]:
    return [t.inner_text() for t in page.get_by_role("tab").all()]


@pytest.mark.parametrize("viewport", [(1600, 900), (1280, 720)])
def test_pl_crawl_every_route_and_every_tab_has_no_english_no_missing_keys_no_overflow(browser, base_url: str, viewport):
    ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, locale="pl-PL", timezone_id="Europe/Warsaw")
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console.error: {m.text}") if m.type == "error" and "favicon" not in m.text else None)
    failures: list[str] = []

    def check(where: str) -> None:
        try:
            assert_polish(page, where=where, allow_english=("PL-", "H-0", "Mastercard", "Visa", "InPost", "DPD"))
        except AssertionError as e:
            failures.append(str(e)[:500])

    try:
        for route in NAV_ROUTES + BARE_ROUTES:
            go(page, base_url, route)
            check(f"{route} @{viewport[0]}")
            for i, label in enumerate(_tabs(page)):
                page.get_by_role("tab").nth(i).click()
                settle(page, 500)
                check(f"{route} tab «{label}» @{viewport[0]}")
    finally:
        ctx.close()
    assert not errors, errors[:5]
    assert not failures, "\n".join(failures[:10])


def test_pl_page_actions_and_their_results_are_polish_too(pl_page: Page, base_url: str):
    """Result panels only exist after an action: run the safe actions of every page that has one and scan the page again."""
    page = pl_page
    allow = ("PL-", "H-0", "Mastercard", "Visa", "InPost", "DPD", "NordFreight")
    # a deployed app is billed per model run: the two actions that only start background evaluations / conversations (their toast is the same code as offline) run there
    # with E2E_FULL_ACTIONS=1 only
    full = not LIVE or os.environ.get("E2E_FULL_ACTIONS") == "1"
    failures: list[str] = []

    def step(where: str, action, quiet_ms: int | None = None) -> None:
        try:
            action()
            page.wait_for_timeout(300)
            wait_quiet(page, quiet_ms or ai(30000), settle_ms=900)  # a model may be behind the action: scan the page once its result is there
            assert_polish(page, where=where, allow_english=allow)
        except Exception as e:  # one report with every page that failed
            failures.append(f"{where}: {str(e)[:400]}")

    def click(name: str, exact: bool = True) -> None:
        page.get_by_role("button", name=name, exact=exact).first.click()

    def tab(name: str) -> None:
        page.get_by_role("tab", name=re.compile(name)).click()

    go(page, base_url, "/compliance")
    step("/compliance redaction", lambda: click("Zamaskuj"))
    tab("Ochrona wejścia")
    for b in ("Sprawdź", "Sprawdź odpowiedź", "Skanuj"):
        step(f"/compliance {b}", lambda b=b: click(b))
    tab("Zestaw red team")
    step("/compliance red team", lambda: click("Uruchom zestaw"))
    tab("Retencja i audyt")
    for b in ("Próbne czyszczenie", "Zweryfikuj łańcuch", "Test manipulacji"):
        step(f"/compliance {b}", lambda b=b: click(b))

    go(page, base_url, "/routing")
    step("/routing analyse", lambda: click("Analizuj"))
    step("/routing route", lambda: click("Skieruj"))
    tab("Wyzwalacze eskalacji")
    step("/routing triggers", lambda: click("Symuluj"))

    go(page, base_url, "/customers")
    tab("Konektory")
    step("/customers contract tests", lambda: click("Uruchom testy kontraktowe"))
    step("/customers outage", lambda: click("Zasymuluj awarię CRM"))
    step("/customers restore", lambda: click("Przywróć"))

    go(page, base_url, "/i18n")
    step("/i18n detect & translate", lambda: click("Wykryj język i przetłumacz"))
    tab("Ocena")
    step("/i18n evaluation", lambda: click("Uruchom ocenę"))
    step("/i18n round trip", lambda: click("Uruchom test w obie strony"))

    go(page, base_url, "/outbound")
    step("/outbound shipment delayed", lambda: click("Opóźniona przesyłka — teraz"))
    step("/outbound quiet hours", lambda: click("… o 22:30 UTC (cisza nocna)"))
    step("/outbound decision", lambda: page.locator("table tbody tr").first.click())
    step("/outbound release", lambda: click("Zwolnij zaległe odroczenia"))

    go(page, base_url, "/rollout")
    step("/rollout select", lambda: page.locator("table tbody tr").first.click())
    if full:
        step("/rollout gate", lambda: click("1 · Uruchom bramkę oceny"), quiet_ms=ai(120000))  # starts a 23-scenario evaluation: ~US$0.8 with a real model
    tab("Różnice")
    step("/rollout diff", lambda: (page.get_by_label("Z wersji").select_option(index=1), page.get_by_label("Do wersji").select_option(index=1), click("Różnice")))

    go(page, base_url, "/tools")
    tab("Zatwierdzenia")
    step("/tools approvals", lambda: None)
    tab("Ślad audytu")
    step("/tools audit", lambda: None)

    go(page, base_url, "/observability")
    tab("Ślady")
    step("/observability chat traces", lambda: click("czat"))
    tab("Stan systemu")
    step("/observability health", lambda: None)

    go(page, base_url, "/supervisor")
    if full:
        step("/supervisor demo traffic", lambda: click("Ruch demo"))  # starts real conversations on a deployed app

    go(page, base_url, "/qa")
    tab("Oceny")

    def open_first_review() -> None:
        # reviews are produced by the conversations of the journeys above (the QA journey asserts that they exist)
        row = page.locator("table tbody tr").first
        try:
            row.wait_for(timeout=8000)
        except PlaywrightTimeoutError:
            return
        row.click()

    step("/qa review", open_first_review)
    tab("Kalibracja")
    step("/qa calibration", lambda: None)

    go(page, base_url, "/settings")
    step("/settings", lambda: None)

    assert not failures, "\n".join(failures)


def test_pl_polish_glyphs_render_with_a_real_font(pl_page: Page, base_url: str):
    page = pl_page
    go(page, base_url, "/")
    page.evaluate(
        "() => { const d = document.createElement('div'); d.id = 'glyphs'; d.textContent = 'ąćęłńóśźżĄĆĘŁŃÓŚŹŻ'; d.style.cssText = 'position:fixed;left:0;top:0;font-size:24px;z-index:99'; document.body.appendChild(d); }"
    )
    cdp = page.context.new_cdp_session(page)
    cdp.send("DOM.enable")
    cdp.send("CSS.enable")
    root = cdp.send("DOM.getDocument", {"depth": 1})["root"]["nodeId"]
    node = cdp.send("DOM.querySelector", {"nodeId": root, "selector": "#glyphs"})["nodeId"]
    fonts = cdp.send("CSS.getPlatformFontsForNode", {"nodeId": node})["fonts"]
    assert sum(f["glyphCount"] for f in fonts) == 18, fonts  # every one of the 18 Polish letters was drawn by an installed font (no tofu)
    assert not any("LastResort" in f["familyName"] for f in fonts), fonts
    assert overflow(page)["docOverflowX"] <= 1
