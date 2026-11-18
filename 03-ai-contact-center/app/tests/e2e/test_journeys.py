"""End-to-end journeys in a real browser (golden journeys GJ-1..GJ-8 of FEATURES.md): customer chat and voice UI, agent console with handoff and Agent Assist,
supervisor, QA, VoC, WFM, evaluation harness, KB admin, CX/ROI, feature map; keyboard-only operation and an axe-core accessibility scan.
Run:  pytest tests/e2e -o addopts="" -q     (screenshots: E2E_SHOTS_DIR=../deck/assets/screens)"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from e2e_env import LIVE, ai, poll
from journey_helpers import confirm_cards_until, prepare_demo_refund, refunded, voice_ask, wait_quiet
from playwright.sync_api import Page, expect

AXE = Path(__file__).resolve().parents[2] / "web" / "node_modules" / "axe-core" / "axe.min.js"
AMOUNT_379 = re.compile(r"\b379(?:[.,]00)?\b")  # however the model writes the golden amount
DAYS = re.compile(r"\b(?:14|30|fourteen|thirty)[\s-]*days?\b", re.I)  # "30 days", "14 days", "30-day"


def log(page: Page):
    return page.get_by_role("log", name="Conversation")


def say(page: Page, text: str) -> None:
    page.locator("#msg").fill(text)
    page.get_by_role("button", name="Send").click()


def wait_idle(page: Page, timeout: int | None = None) -> None:
    expect(page.get_by_label("Assistant is typing")).to_have_count(0, timeout=timeout or ai(30000))


def start_chat(page: Page, base_url: str, lang: str = "en") -> None:
    page.goto(f"{base_url}/widget?lang={lang}")
    page.get_by_role("button", name=re.compile("Accept & start|Akzeptieren|Accepter|Aceptar|Accetta|Accepteren|Akceptuj|Aceitar")).first.click()
    expect(log(page)).to_contain_text("AI assistant", timeout=ai(15000))


def test_gj1_customer_chat_resolves_a_damaged_sofa_in_german(page: Page, base_url: str, api, shot):
    prepare_demo_refund(api, base_url, "CU-1001", reset_when_local=False)  # the demo order can be refunded once; a deployed app is never reset by the suite
    start_chat(page, base_url)
    sid = re.search(r"c=(cv_[0-9a-f]+)", page.locator("a[href*='/call?c=cv_']").first.get_attribute("href") or "").group(1)
    say(page, "Hallo, mein Sofa ist beschädigt angekommen. Bestellnummer CH-100231.")
    code_btn = page.get_by_label("Simulated phone").get_by_role("button", name=re.compile(r"^\d{6}$"))
    expect(code_btn).to_be_visible(timeout=ai(20000))
    code_btn.click()
    page.get_by_role("button", name="Send").click()
    expect(log(page)).to_contain_text(AMOUNT_379, timeout=ai(30000))  # the real model needs ~1 min for the verification, lookup and policy turns
    expect(page.get_by_text("Verified L1")).to_be_visible(timeout=ai(15000))
    kb_chip = log(page).locator("span[title]").filter(has_text=re.compile(r"^K\d+\s+\S"))
    expect(kb_chip.first).to_be_visible(timeout=ai(15000))
    say(page, "Ich möchte eine Erstattung bitte, der erste Termin passt.")
    shot_taken: list[bool] = []

    def on_card(text: str) -> None:
        if "379.00" in text and not shot_taken:
            shot_taken.append(True)
            shot("01-customer-widget-chat-confirmation")

    # the stub proposes return, pickup and refund in one card, a real model one card at a time: confirm until the refund tool has run
    cards = confirm_cards_until(
        page,
        card_name="Please confirm this action",
        confirm_name="Confirm",
        typing_label="Assistant is typing",
        done=lambda: refunded(api, "CU-1001"),
        nudge=lambda: say(page, "Yes, please go ahead with the refund."),
        on_card=on_card,
    )
    assert "379.00" in "\n".join(cards), cards
    expect(page.get_by_role("group", name="Please confirm this action")).to_have_count(0, timeout=ai(30000))
    wait_idle(page)
    page.wait_for_timeout(500)
    say(page, "Nein danke, das war's.")
    expect(page.locator("#msg")).to_be_disabled(timeout=ai(30000))
    shot("01-customer-widget-resolved")
    deadline = time.time() + ai(40000) / 1000
    refunds: list[dict] = []
    while time.time() < deadline and not refunds:  # wrap-up and QA run in the background after the customer says goodbye
        timeline = api.get("/api/crm/customers/CU-1001/360").json()["timeline"]
        refunds = [e for e in timeline if e["type"] == "refund"]
        time.sleep(poll(0.5))
    assert len(refunds) == 1 and "379" in refunds[0]["title"] + refunds[0].get("detail", ""), refunds
    review: dict = {}
    deadline = time.time() + ai(60000) / 1000
    while time.time() < deadline and not review:  # the QA review of THIS conversation appears after the (model-assisted) scoring
        reviews = api.get("/api/qa/reviews", headers={"X-Demo-Role": "qa"}).json()
        review = next((r for r in (reviews["reviews"] if isinstance(reviews, dict) else reviews) if r.get("conversation_id") == sid), {})
        time.sleep(poll(1))
    assert review.get("disposition") == "RESOLVED_REFUND_ISSUED", review


def test_voice_call_ui_text_path_shows_live_transcripts_and_latency(page: Page, base_url: str, shot):
    page.goto(f"{base_url}/call")
    expect(page.get_by_role("tab", name="Voice call")).to_be_visible()
    page.get_by_role("button", name=re.compile("Start call|Call", re.I)).first.click()
    expect(page.get_by_text(re.compile("Concierge", re.I)).first).to_be_visible(timeout=ai(20000))
    # the real Realtime model speaks the disclosure first and streams its answer for up to ~90 s; the caption is phrased by the model: any of the policy periods
    voice_ask(page, "What is your return policy?", DAYS, placeholder=re.compile("type", re.I), greeting=re.compile("record|help you", re.I), listening="listening")  # live: the disclosure ("may be recorded"); offline fake realtime: "how can I help you today?"
    shot("02-customer-voice-call")
    page.get_by_role("tab", name=re.compile("Telephony adapters")).click()
    expect(page.get_by_text("SIP trunk -> Azure OpenAI Realtime SIP").first).to_be_visible()
    expect(page.get_by_text(re.compile("Supported until 30 Sep 2028")).first).to_be_visible()
    page.get_by_role("button", name="Damaged-sofa call").click()
    expect(page.get_by_text("realtime.call.incoming")).to_be_visible(timeout=ai(30000))
    expect(page.get_by_text("disconnected").first).to_be_visible()
    shot("02-telephony-adapters-simulator")


def test_agent_console_warm_handoff_with_context_package_and_agent_assist(page: Page, base_url: str, api, shot):
    customer = {"X-Demo-Role": "customer"}
    created = api.post("/api/chat/sessions", json={"language": "en", "recording_consent": "granted"}, headers=customer)
    assert created.status_code == 200, created.text
    sid = created.json()["session"]["id"]
    sent = api.post(f"/api/chat/sessions/{sid}/messages", json={"text": "This is unacceptable! If my washing machine CH-100250 isn't installed I will contact my lawyer."}, headers=customer)
    assert sent.status_code == 200, sent.text
    deadline = time.time() + ai(30000) / 1000
    while time.time() < deadline and not (api.get(f"/api/chat/sessions/{sid}", headers=customer).json()["session"].get("handoff") or {}).get("queue"):
        time.sleep(poll(0.5))  # the hand-off (and its context package) exists before the console opens the conversation
    page.goto(f"{base_url}/agent?conversation={sid}")
    expect(page.get_by_role("heading", name="Human-agent console")).to_be_visible()
    expect(page.get_by_text("legal_threat").first).to_be_visible(timeout=ai(15000))
    expect(page.get_by_text(re.compile("context package|Context package", re.I)).first).to_be_visible(timeout=ai(15000))
    page.get_by_role("button", name="Accept", exact=True).click(timeout=ai(15000))
    expect(page.locator("#reply")).to_be_enabled(timeout=ai(15000))
    expect(page.get_by_text(re.compile("Agent Assist|Next best", re.I)).first).to_be_visible(timeout=ai(15000))
    wait_quiet(page, ai(30000))  # the suggestions are written by the model: capture the console once they are there
    shot("02-agent-console-handoff")
    box = page.locator("#reply")
    box.fill("Hello, this is Hannah. I am sorry about the trouble and I am looking at your order now.")
    send = page.get_by_role("button", name="Send", exact=True)
    expect(send).to_be_enabled(timeout=ai(15000))
    send.click()
    deadline = time.time() + ai(15000) / 1000
    while time.time() < deadline:
        session = api.get(f"/api/chat/sessions/{sid}", headers=customer).json()["session"]
        if any(m["role"] == "agent_human" for m in session["messages"]):
            break
        time.sleep(poll(0.3))
    assert any(m["role"] == "agent_human" for m in session["messages"])


def test_supervisor_console_shows_queues_alerts_and_live_conversations(page: Page, base_url: str, api, shot):
    api.post("/api/supervisor/demo-traffic", json={"count": 2 if LIVE else 6})  # on a deployed app every demo conversation is a real model run
    page.goto(f"{base_url}/supervisor")
    expect(page.get_by_role("heading", name="Supervisor console")).to_be_visible()
    expect(page.get_by_text(re.compile("queue", re.I)).first).to_be_visible(timeout=15000)
    page.wait_for_timeout(800)
    shot("03-supervisor-console")


def test_qa_workbench_lists_scored_conversations_with_evidence(page: Page, base_url: str, api, shot):
    page.goto(f"{base_url}/qa")
    expect(page.get_by_role("heading", name="QA workbench")).to_be_visible()
    expect(page.get_by_text(re.compile("agreement|kappa|calibrat", re.I)).first).to_be_visible(timeout=15000)
    page.wait_for_timeout(600)
    shot("04-qa-workbench")


def test_voc_insights_flags_the_nordfreight_damage_spike(page: Page, base_url: str, shot):
    page.goto(f"{base_url}/voc")
    expect(page.get_by_role("heading", name="Voice-of-customer insights")).to_be_visible()
    expect(page.get_by_text("NordFreight").first).to_be_visible(timeout=30000)
    expect(page.get_by_text(re.compile("Emerging issue", re.I)).first).to_be_visible()
    page.wait_for_timeout(600)
    shot("05-voc-insights")


def test_wfm_forecast_staffing_and_containment_what_if(page: Page, base_url: str, shot):
    page.goto(f"{base_url}/wfm")
    expect(page.get_by_role("heading", name=re.compile("Workforce forecast"))).to_be_visible()
    expect(page.get_by_text(re.compile("Simulated service level", re.I))).to_be_visible(timeout=30000)
    def fte() -> float:
        m = re.search(r"Human FTE \(week\)\s*([\d.]+)", page.locator("main").inner_text())
        assert m, "the staffing KPI is on the page"
        return float(m.group(1))

    before = fte()
    slider = page.get_by_role("slider").first
    slider.focus()
    for _ in range(25):
        slider.press("ArrowRight")
    page.wait_for_timeout(1500)
    assert fte() < before, "more AI containment reduces the human staffing requirement"
    shot("06-wfm-forecast-staffing")


def test_eval_harness_runs_a_suite_and_the_gate_blocks_a_broken_prompt(page: Page, base_url: str, api, shot):
    page.goto(f"{base_url}/evals")
    expect(page.get_by_role("heading", name=re.compile("Evaluation"))).to_be_visible()
    # a real model needs minutes (and ~US$1.4) for the 42 core scenarios: a deployed app runs the 8-scenario smoke suite for the run and for the gate
    # (the run stores the baseline the gate compares with); the offline stub runs the default suites
    if LIVE:
        page.get_by_label("Suite", exact=True).select_option("smoke")
    known = {r["id"] for r in api.get("/api/evals/runs?limit=50").json()}
    page.get_by_role("button", name="Run suite").click()
    deadline = time.time() + ai(120000) / 1000
    new: list[str] = []
    while time.time() < deadline and not new:  # finished runs are listed; the page may still show an older report, so wait for this run's
        new = [r["id"] for r in api.get("/api/evals/runs?limit=50").json() if r["id"] not in known]
        time.sleep(poll(1))
    assert new, "the suite run did not finish"
    expect(page.get_by_text(f"Report · {new[0]}").first).to_be_visible(timeout=ai(30000))
    expect(page.get_by_text(re.compile(r"\d+/\d+ scenarios")).first).to_be_visible()
    shot("07-eval-harness-report")
    page.get_by_role("tab", name=re.compile("CI gate")).click()
    if LIVE:
        page.get_by_label("Gate suite").select_option("smoke")
    page.get_by_role("button", name="Inject broken prompt & gate").click()
    expect(page.get_by_text(re.compile("FAILED — promotion blocked")).first).to_be_visible(timeout=ai(120000))
    shot("07-eval-harness-gate")


def test_kb_admin_shows_documents_versions_and_answers_with_citations(page: Page, base_url: str, shot):
    page.goto(f"{base_url}/kb")
    expect(page.get_by_role("heading", name="Knowledge base admin")).to_be_visible()
    expect(page.get_by_text("Returns policy (30 days)").first).to_be_visible(timeout=15000)
    shot("09-agent-studio-kb-admin")


def test_cx_metrics_and_the_roi_acr_calculator_recompute(page: Page, base_url: str, shot):
    page.goto(f"{base_url}/metrics")
    expect(page.get_by_role("heading", name="CX metrics & ROI")).to_be_visible()
    expect(page.get_by_text("AI containment").first).to_be_visible(timeout=20000)
    shot("08-cx-metrics")
    page.get_by_role("tab", name=re.compile("ROI")).click()
    expect(page.get_by_text(re.compile(r"NPV", re.I)).first).to_be_visible(timeout=20000)
    base_text = page.locator("main").inner_text()
    seats = page.get_by_label(re.compile("seats|agents", re.I)).first
    seats.fill("3000")
    seats.press("Enter")
    page.wait_for_timeout(1500)
    assert page.locator("main").inner_text() != base_text, "changing an assumption recomputes the model"
    shot("08-cx-roi-calculator")


def test_feature_map_lists_all_24_features_as_implemented(page: Page, base_url: str, shot):
    page.goto(f"{base_url}/features")
    expect(page.get_by_role("heading", name="Feature map")).to_be_visible()
    for i in (1, 2, 12, 16, 24):
        expect(page.get_by_text(f"CC-{i:02d}").first).to_be_visible(timeout=15000)
    assert len(page.get_by_text(re.compile(r"^CC-\d\d$")).all()) >= 24
    shot("10-feature-map")


def test_keyboard_only_chat_and_visible_focus(page: Page, base_url: str):
    page.goto(f"{base_url}/widget")
    expect(page.get_by_role("heading", name="Before we start")).to_be_visible()
    page.keyboard.press("Tab")
    focused = page.evaluate("document.activeElement && document.activeElement.tagName")
    assert focused in ("SELECT", "A", "BUTTON"), focused
    for _ in range(6):
        if page.evaluate("document.activeElement.textContent || ''").strip().startswith("Accept"):
            break
        page.keyboard.press("Tab")
    page.keyboard.press("Enter")
    expect(log(page)).to_contain_text("AI assistant", timeout=ai(15000))
    page.locator("#msg").focus()
    page.keyboard.type("What is your return policy?")
    page.keyboard.press("Enter")
    expect(log(page)).to_contain_text(DAYS, timeout=ai(30000))
    outline = page.evaluate("getComputedStyle(document.querySelector('#msg')).outlineStyle + getComputedStyle(document.querySelector('#msg')).boxShadow")
    assert outline and outline != "none", "the focused input has a visible focus indicator"
    assert page.get_by_role("log", name="Conversation").get_attribute("aria-live") == "polite"


@pytest.mark.parametrize("route", ["/widget", "/call", "/", "/agent", "/supervisor", "/qa", "/metrics", "/wfm", "/voc", "/evals", "/kb", "/features", "/outbound", "/security"])
def test_axe_core_finds_no_serious_or_critical_accessibility_violations(axe_page: Page, base_url: str, route: str):
    page = axe_page
    if not AXE.exists():
        pytest.skip("axe-core is not installed (npm install)")
    page.goto(f"{base_url}{route}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    page.add_script_tag(path=str(AXE))
    result = page.evaluate("axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})")
    bad = [(v["id"], v["impact"], len(v["nodes"]), v["nodes"][0]["html"][:120]) for v in result["violations"] if v["impact"] in ("serious", "critical")]
    assert not bad, bad


def test_spa_routes_survive_a_hard_reload_and_unknown_routes_show_the_shell(page: Page, base_url: str):
    page.goto(f"{base_url}/qa")
    page.reload()
    expect(page.get_by_role("heading", name="QA workbench")).to_be_visible()
    t0 = time.time()
    page.goto(f"{base_url}/does-not-exist")
    assert time.time() - t0 < 10
