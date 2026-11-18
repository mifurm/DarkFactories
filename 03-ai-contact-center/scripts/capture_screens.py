#!/usr/bin/env python3
"""Captures the product-tour screenshots (1600x900, light theme, synthetic data) of a running instance into deck/assets/screens/.

    python scripts/capture_screens.py --base-url https://<app>.azurecontainerapps.io [--out deck/assets/screens] [--only 01,03]

It prepares demo data through the public API / UI first (a damaged-sofa journey in German, an escalated legal threat, supervisor traffic),
so every console shows real content. Needs: pip install playwright httpx && playwright install chromium"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import Page, TimeoutError as PwTimeout, expect, sync_playwright

ADMIN = {"X-Demo-Role": "admin"}
CUSTOMER = {"X-Demo-Role": "customer"}
SILENT_MIC = """navigator.mediaDevices.getUserMedia = async () => {
  const ctx = new AudioContext(); const dest = ctx.createMediaStreamDestination();
  const gain = ctx.createGain(); gain.gain.value = 0; const osc = ctx.createOscillator();
  osc.connect(gain); gain.connect(dest); osc.start(); return dest.stream;
};"""
OUT = Path(__file__).resolve().parent.parent / "deck" / "assets" / "screens"
DONE: list[str] = []
FAILED: list[str] = []


def snap(page: Page, name: str, *, full: bool = False) -> None:
    page.wait_for_timeout(700)
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=full)
    DONE.append(path.name)
    print(f"  saved {path.name}")


def step(name: str, only: set[str] | None, fn) -> None:
    if only and not any(name.startswith(o) for o in only):
        return
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - one failed screenshot must not stop the others
        FAILED.append(name)
        print(f"  FAILED {name}: {type(exc).__name__}: {str(exc)[:200]}")


def say(page: Page, text: str) -> None:
    page.locator("#msg").fill(text)
    page.get_by_role("button", name="Send").click()


def refund_executed(base: str, sid: str) -> bool:
    data = httpx.get(f"{base}/api/chat/sessions/{sid}", headers=CUSTOMER, timeout=30).json()
    data = data.get("session", data)
    return any(t.get("name") == "issue_refund" and t.get("status") in ("ok", "replayed") for m in data.get("messages", []) for t in (m.get("tools") or []))


def widget_journey(page: Page, base: str) -> None:
    """GJ-1 in the browser: German damaged sofa -> OTP from the simulated phone -> KB citation -> confirmed plan -> refund executed -> resolved."""
    log = page.get_by_role("log", name="Conversation")
    page.goto(f"{base}/widget")
    page.get_by_role("button", name="Accept & start").click()
    expect(log).to_contain_text("AI assistant", timeout=20000)
    sid = re.search(r"/transcript/([^?]+)", page.locator("a[href*='/api/i18n/transcript/']").get_attribute("href") or "").group(1)
    say(page, "Hallo, mein Sofa ist beschädigt angekommen. Bestellnummer CH-100231.")
    code = page.get_by_label("Simulated phone").get_by_role("button", name=re.compile(r"^\d{6}$"))
    expect(code).to_be_visible(timeout=60000)
    code.click()
    page.get_by_role("button", name="Send").click()
    expect(page.get_by_text("Verified L1")).to_be_visible(timeout=90000)
    deadline = time.time() + 300
    asked = False
    while time.time() < deadline and not refund_executed(base, sid):
        page.wait_for_timeout(1500)
        if page.get_by_label("Assistant is typing").count():
            continue
        card = page.get_by_role("group", name="Please confirm this action")
        text = log.inner_text()
        if card.count():
            card.get_by_role("button", name="Confirm").click()
            page.wait_for_timeout(5000)
        elif not asked:
            asked = True
            say(page, "Ich möchte eine Erstattung bitte, der erste Termin passt.")
        elif re.search(r"Ersatz.{0,80}(Erstattung|Rückerstattung)|(Erstattung|Rückerstattung).{0,80}Ersatz", text[-700:], re.S):
            say(page, "Ich möchte die Erstattung, bitte.")
        elif re.search(r"\d{1,2}:\d{2}", text[-600:]):
            say(page, "Der erste Termin passt mir.")
        else:
            say(page, "Ja, bitte so machen.")
    if not refund_executed(base, sid):
        raise RuntimeError("the refund was not executed within the time limit")
    page.wait_for_timeout(6000)
    say(page, "Nein danke, das war's.")
    expect(page.locator("#msg")).to_be_disabled(timeout=60000)


def main() -> int:
    global OUT
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--only", help="comma separated screenshot number prefixes, e.g. 01,03")
    ap.add_argument("--skip-prepare", action="store_true")
    a = ap.parse_args()
    base = a.base_url.rstrip("/")
    OUT = Path(a.out)
    OUT.mkdir(parents=True, exist_ok=True)
    only = {s.strip() for s in a.only.split(",")} if a.only else None
    api = httpx.Client(base_url=base, timeout=120, headers=ADMIN)
    print(f"Capturing screenshots of {base} into {OUT}")

    if not a.skip_prepare:
        api.post("/api/admin/reset-backoffice")
        api.post("/api/supervisor/demo-traffic/clear")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport={"width": 1600, "height": 900}, locale="en-GB").new_page()
        page.set_default_timeout(60000)

        def s01() -> None:
            widget_journey(page, base)
            snap(page, "01-customer-widget-chat")

        step("01", only, s01)

        def legal() -> str:
            sid = api.post("/api/chat/sessions", json={"language": "en", "recording_consent": "granted"}, headers=CUSTOMER).json()["session"]["id"]
            api.post(f"/api/chat/sessions/{sid}/messages", json={"text": "This is unacceptable! My washing machine CH-100250 was never installed and I have called three times. If this is not fixed I will contact my lawyer."}, headers=CUSTOMER)
            return sid

        def s02() -> None:
            sid = legal()
            page.goto(f"{base}/agent?conversation={sid}")
            expect(page.get_by_text("legal_threat").first).to_be_visible(timeout=60000)
            page.get_by_role("button", name="Accept", exact=True).click()
            expect(page.locator("#reply")).to_be_enabled(timeout=30000)
            page.wait_for_timeout(2500)
            snap(page, "02-agent-console-handoff")

        step("02", only, s02)

        def s03() -> None:
            api.post("/api/supervisor/demo-traffic", json={"count": 8})
            page.goto(f"{base}/supervisor")
            expect(page.get_by_role("heading", name="Supervisor console")).to_be_visible()
            page.wait_for_timeout(20000)
            snap(page, "03-supervisor-console")

        step("03", only, s03)

        def route(name: str, path: str, heading: str, wait_text: str | None = None, delay: int = 1500) -> None:
            page.goto(f"{base}{path}")
            expect(page.get_by_role("heading", name=re.compile(heading)).first).to_be_visible(timeout=60000)
            if wait_text:
                expect(page.get_by_text(re.compile(wait_text)).first).to_be_visible(timeout=60000)
            page.wait_for_timeout(delay)
            snap(page, name)

        step("04", only, lambda: route("04-qa-workbench", "/qa", "QA workbench", "agreement|calibrat|kappa", 2500))
        step("05", only, lambda: route("05-voc-insights", "/voc", "Voice-of-customer", "NordFreight", 2500))
        step("06", only, lambda: route("06-wfm-forecast-staffing", "/wfm", "Workforce forecast", "Simulated service level", 2500))

        def s07() -> None:
            page.goto(f"{base}/evals")
            expect(page.get_by_role("heading", name=re.compile("Evaluation"))).to_be_visible()
            full_runs = page.get_by_role("button").filter(has_text="42/42")
            expect(full_runs.first).to_be_visible(timeout=30000)
            full_runs.first.click()
            expect(page.get_by_text("42/42 scenarios")).to_be_visible(timeout=30000)
            page.wait_for_timeout(2500)
            snap(page, "07-eval-harness-report")
            page.get_by_role("tab", name=re.compile("CI gate")).click()
            page.get_by_role("button", name="Inject broken prompt & gate").click()
            expect(page.get_by_text(re.compile("promotion blocked"))).to_be_visible(timeout=300000)
            page.wait_for_timeout(2000)
            snap(page, "07b-eval-harness-ci-gate")

        step("07", only, s07)

        def s08() -> None:
            page.goto(f"{base}/metrics")
            expect(page.get_by_role("heading", name="CX metrics & ROI")).to_be_visible()
            expect(page.get_by_text("AI containment").first).to_be_visible(timeout=60000)
            page.wait_for_timeout(2000)
            snap(page, "08-cx-roi-dashboard")
            page.get_by_role("tab", name=re.compile("ROI")).click()
            expect(page.get_by_text(re.compile("NPV")).first).to_be_visible(timeout=60000)
            page.wait_for_timeout(2500)
            snap(page, "08b-roi-acr-calculator")

        step("08", only, s08)
        step("09", only, lambda: route("09-agent-studio-kb-admin", "/kb", "Knowledge base admin", "Returns policy", 2000))

        def s10() -> None:
            # headless Chromium has no microphone: a silent virtual one keeps the call UI in its normal "listening" state (the typed turn is the test path)
            page.add_init_script(SILENT_MIC)
            page.goto(f"{base}/call")
            page.get_by_role("button", name="Start call").click()
            expect(page.get_by_text(re.compile("Concierge", re.I)).first).to_be_visible(timeout=60000)
            page.wait_for_timeout(14000)  # let the opening disclosure + greeting finish, as a caller would
            page.get_by_placeholder(re.compile("type", re.I)).fill("Hello, my sofa arrived damaged. What are my options?")
            page.keyboard.press("Enter")
            page.wait_for_timeout(30000)
            snap(page, "10-customer-voice-call")
            page.get_by_role("tab", name=re.compile("Telephony adapters")).click()
            page.get_by_role("button", name="Damaged-sofa call").click()
            expect(page.get_by_text("realtime.call.incoming")).to_be_visible(timeout=90000)
            page.wait_for_timeout(1500)
            snap(page, "10b-telephony-adapters-simulator")

        step("10", only, s10)
        step("11", only, lambda: route("11-feature-map", "/features", "Feature map", "CC-24", 1500))
        step("12", only, lambda: route("12-outbound-proactive", "/outbound", "Proactive", None, 1500))
        step("13", only, lambda: route("13-security-rbac", "/security", "Security", None, 2000))
        step("14", only, lambda: route("14-observability-finops", "/observability", "Observability", None, 2500))
        step("15", only, lambda: route("15-routing-escalation", "/routing", "Routing", None, 2500))
        step("16", only, lambda: route("16-customer-360-crm", "/customers", "Customer 360", None, 2500))
        step("17", only, lambda: route("17-rollout-llmops", "/rollout", "Prompt, policy", None, 2500))
        step("18", only, lambda: route("18-compliance-guard", "/compliance", "Compliance", None, 2500))
        browser.close()

    print(f"\n{len(DONE)} screenshots saved; {len(FAILED)} failed {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
