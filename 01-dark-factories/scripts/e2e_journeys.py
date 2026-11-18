#!/usr/bin/env python3
"""Playwright end-to-end journeys for Nightshift (key user journeys + deck screenshots).

Needs Playwright (the portfolio's shared venv has it):
    /Users/michalfu/Dev/SwarmAI/.venv/bin/python scripts/e2e_journeys.py --base-url http://127.0.0.1:8101 [--screens deck/assets/screens]

The run first re-seeds the demo state (admin role) so it is repeatable, then walks through: control tower + fault injection + agent reaction,
approval inbox (RBAC + approve), decision ledger, what-if, copilot, A/B value realization, ROI/ACR calculator, readiness, fleet,
kill switch and the feature map. 1600x900 screenshots are written when --screens is given.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

ADMIN = {"X-Demo-Role": "admin", "Content-Type": "application/json"}
PM = {"X-Demo-Role": "plant_manager", "Content-Type": "application/json"}


def api(base: str, method: str, path: str, body=None, headers=PM, timeout=60):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def h1(page: Page, text: str):
    return page.locator('h1').filter(has_text=text)


class Runner:
    def __init__(self, page: Page, base: str, screens: Path | None, only: str = "") -> None:
        self.page, self.base, self.screens, self.only = page, base, screens, only.lower()
        self.results: list[tuple[str, bool, str]] = []

    def shot(self, name: str, focus: str | None = None) -> None:
        """1600x900 viewport screenshot; `focus` scrolls the first element containing that text to the top of the page first."""
        if self.screens:
            if focus:
                self.page.get_by_text(focus).first.evaluate("e => e.closest('section, div')?.scrollIntoView({block: 'start'})")
            else:
                self.page.evaluate("document.querySelector('main')?.scrollTo(0, 0)")
            self.page.wait_for_timeout(600)
            self.page.screenshot(path=str(self.screens / f"{name}.png"))

    def journey(self, name: str, fn) -> None:
        if self.only and self.only not in name.lower():
            return
        t0 = time.time()
        try:
            fn()
            self.results.append((name, True, f"{time.time() - t0:.1f}s"))
        except Exception as e:  # noqa: BLE001
            self.page.screenshot(path=str((self.screens or Path(".")) / f"_failed-{re.sub(r'[^a-z0-9]+', '-', name.lower())}.png"))
            self.results.append((name, False, f"{type(e).__name__}: {((str(e).splitlines() or [''])[0])[:200]}"))

    def goto(self, path: str) -> None:
        self.page.goto(self.base + path, wait_until="domcontentloaded")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8101")
    ap.add_argument("--screens", default="")
    ap.add_argument("--speed", type=float, default=30.0, help="simulated minutes per real second during the run")
    ap.add_argument("--only", default="", help="run only journeys whose name contains this text (e.g. 'value')")
    a = ap.parse_args()
    base = a.base_url.rstrip("/")
    screens = Path(a.screens) if a.screens else None
    if screens:
        screens.mkdir(parents=True, exist_ok=True)

    speed0 = api(base, "GET", "/api/sim/state")["speed"]
    api(base, "POST", "/api/admin/reseed?plant=KAT-1", {}, ADMIN)  # deterministic starting point; the ledger chain continues
    api(base, "POST", "/api/sim/control", {"command": "speed", "value": a.speed})
    api(base, "POST", "/api/sim/control", {"command": "resume"})

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1600, "height": 900})
        page = ctx.new_page()
        page.set_default_timeout(25000)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console: {m.text[:160]}") if m.type == "error" and "Failed to load resource" not in m.text else None)
        r = Runner(page, base, screens, a.only)

        # ------------------------------------------------------------------ 1. control tower, fault injection, agents react
        def control_tower() -> None:
            r.goto("/")
            expect(h1(page, "Control Tower")).to_be_visible()
            expect(page.get_by_text("● live")).to_be_visible(timeout=15000)
            expect(page.get_by_text("Plant floor")).to_be_visible()
            expect(page.locator("svg[aria-label^='Plant map']")).to_be_visible()
            assert page.locator("svg[aria-label^='Plant map'] g[role='button']").count() >= 20

        def fault_and_react() -> None:
            page.get_by_label("Fault kind").select_option(label="Bearing wear")
            page.get_by_label("Fault target").select_option("CNC-04")
            page.get_by_role("button", name=re.compile("Inject fault")).click()
            expect(page.get_by_text("Injected Bearing wear on CNC-04")).to_be_visible()
            feed = page.get_by_label("Agent activity")
            expect(feed.get_by_text("maintenance", exact=True).first).to_be_visible(timeout=60000)
            try:  # let the story develop: the planned repair puts the asset into MAINT
                page.wait_for_selector("svg[aria-label^='Plant map'] text:text-matches('MAINT|DOWN|SETUP')", timeout=40000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(3000)
            r.shot("01-control-tower")

        def tower_asset_drilldown() -> None:
            page.locator("svg[aria-label^='Plant map'] g[role='button']").filter(has_text="CNC-04").first.click()
            expect(page.get_by_text("CNC-04 · ")).to_be_visible()
            expect(page.get_by_role("button", name="Schedule maintenance")).to_be_visible()

        r.journey("control tower: live plant map, KPIs, SSE", control_tower)
        r.journey("fault injection -> maintenance agent reacts in the live feed", fault_and_react)
        r.journey("click an asset tile -> asset panel", tower_asset_drilldown)

        # ------------------------------------------------------------------ 2. ledger
        def ledger() -> None:
            r.goto("/ledger")
            expect(h1(page, "Decision ledger")).to_be_visible()
            expect(page.get_by_text("VALID", exact=True)).to_be_visible(timeout=15000)
            page.get_by_label("Kind").select_option("decision")
            expect(page.locator("tbody tr").first).to_be_visible()
            page.locator("tbody tr").first.click()
            expect(page.get_by_text("Previous hash")).to_be_visible()
            page.get_by_label("Kind").select_option("")
            r.shot("02-agent-activity-ledger")

        r.journey("ledger: hash chain VALID, filter, entry detail", ledger)

        # ------------------------------------------------------------------ 3. approvals inbox + RBAC
        def approvals() -> None:
            r.goto("/policy")
            expect(h1(page, "Autonomy dial")).to_be_visible()
            page.get_by_role("button", name="maintenance.schedule L2").click()
            page.get_by_role("button", name="Apply dial changes").click()
            page.wait_for_timeout(800)
            r.shot("11-autonomy-dial-policy")
        r.journey("policy: set maintenance.schedule to L2 (approve-all)", approvals)

        def inbox_flow() -> None:
            api(base, "POST", "/api/sim/faults", {"kind": "bearing_wear", "asset": "CNC-02", "params": {"ttf_h": 8}})
            r.goto("/inbox")
            card = page.get_by_test_id("approval-card").first
            expect(card).to_be_visible(timeout=90000)
            r.shot("03-approvals-inbox")
            # an operator may not approve (HTTP 403 surfaces in the UI)
            page.select_option("#role-sel", "operator")
            card.get_by_role("button", name="Approve").click()
            expect(page.get_by_role("alert").filter(has_text=re.compile("403|lacks permission"))).to_be_visible()
            page.select_option("#role-sel", "plant_manager")
            card.get_by_role("button", name="Approve").click()
            page.get_by_role("tab", name="Resolved").click()
            expect(page.get_by_text("approved").first).to_be_visible()

        r.journey("approvals inbox: operator denied (403), plant manager approves", inbox_flow)
        api(base, "PUT", "/api/policy/dial", {"levels": {"maintenance.schedule": 4}})

        # ------------------------------------------------------------------ 4. what-if
        def whatif() -> None:
            r.goto("/twin")
            expect(h1(page, "Digital twin")).to_be_visible()
            page.get_by_role("button", name="Run what-if").click()
            expect(page.get_by_text("What-if result")).to_be_visible(timeout=30000)
            expect(page.get_by_text("Net value (EUR)")).to_be_visible()
            r.shot("04-what-if")

        r.journey("digital twin: what-if on a fork with KPI deltas", whatif)

        # ------------------------------------------------------------------ 5. copilot
        def copilot() -> None:
            r.goto("/copilot")
            page.get_by_role("button", name=re.compile("Which assets look unhealthy")).click()
            bubble = page.locator("div.max-w-\\[92\\%\\]").last
            expect(bubble).to_contain_text(re.compile(r"\S{20,}"), timeout=90000)
            expect(page.get_by_role("button", name="Ask", exact=True)).to_be_visible(timeout=90000)  # streaming finished
            expect(page.get_by_text(re.compile(r"asset:|ledger:|plan:|order:")).first).to_be_visible(timeout=30000)
            r.shot("05-copilot")

        r.journey("copilot: grounded answer with tool calls and citations", copilot)

        # ------------------------------------------------------------------ 6. value realization
        def value_ab() -> None:
            r.goto("/value")
            expect(h1(page, "Value realization")).to_be_visible()
            row = page.get_by_test_id("ab-downtime_h")
            expect(row).to_be_visible(timeout=60000)
            expect(row.get_by_text("significant", exact=True)).to_be_visible()
            expect(page.get_by_test_id("ab-late_orders").get_by_text("significant", exact=True)).to_be_visible()
            r.shot("06-ab-value-realization")

        def value_roi() -> None:
            page.get_by_role("tab", name="ROI / ACR calculator").click()
            head = page.get_by_test_id("calc-headline")
            expect(head).to_be_visible(timeout=30000)
            for text in ("$8.26M", "104 %", "22.2 mo", "$677k", "$910k", "$114k"):  # Base reference values of business-case model v1.1.0
                expect(head).to_contain_text(text, timeout=30000)
            expect(page.get_by_test_id("calc-parity")).to_contain_text("matches outputs.json")
            before = head.text_content()  # not inner_text(): the tiles use CSS uppercase, to_have_text compares textContent
            filt = page.get_by_label("Filter assumptions")
            filt.fill("unplanned downtime")
            page.get_by_label("Reduction of unplanned downtime hours", exact=True).fill("0.6")
            expect(head).not_to_have_text(before, timeout=30000)  # the server recomputes the model (debounced), so wait for it
            page.get_by_label("Reset Reduction of unplanned downtime hours").click()
            expect(head).to_have_text(before, timeout=30000)
            ramp = "Benefit realisation by year since go-live (year 1, 2, 3+)"
            filt.fill("realisation by year since go-live")
            page.get_by_label(f"{ramp} year 1", exact=True).fill("0.6")
            expect(head).not_to_have_text(before, timeout=30000)
            page.get_by_label(f"Reset {ramp}").click()
            expect(head).to_have_text(before, timeout=30000)
            filt.fill("")
            expect(page.get_by_text("ACR by service family").first).to_be_visible()
            expect(page.get_by_text("ACR by lever").first).to_be_visible()
            expect(page.get_by_role("cell", name=re.compile("100-plant")).first).to_be_visible()
            expect(page.get_by_text("illustrative").first).to_be_visible()
            expect(page.get_by_role("img", name="Sensitivity tornado of NPV")).to_be_visible(timeout=40000)  # slow path: idle-debounced, cached on the server
            r.shot("07-roi-acr-calculator")

            page.get_by_role("button", name="Expansion levers on").click()  # master toggle: the five switches go to their Upside adoption
            for text in ("$4.26M", "$1.28M", "$1.87M", "$233k"):
                expect(head).to_contain_text(text, timeout=30000)
            expect(page.get_by_test_id("calc-parity")).to_contain_text("matches outputs.json", timeout=30000)
            expect(page.get_by_role("cell", name=re.compile("E4 Enterprise data-platform")).first).to_be_visible()
            for lever in ("E1", "E2", "E3", "E4", "E5"):
                expect(page.get_by_label(f"{lever} adoption %")).not_to_have_value("0")
            r.shot("07b-roi-acr-levers-on")
            r.shot("07c-roi-acr-by-family-and-lever", focus="ACR by service family")
            r.shot("07d-roi-acr-tiers-and-levers", focus="ACR tiers")
            page.get_by_label("E4 adoption %").fill("0")  # a custom mix is reported, not silently coerced
            expect(page.get_by_text("Custom lever mix").first).to_be_visible(timeout=30000)
            page.get_by_role("button", name="Base · levers off").click()
            expect(head).to_contain_text("$8.26M", timeout=30000)

        r.journey("value: A/B replay with significant downtime + late-order improvement", value_ab)
        r.journey("value: ROI/ACR calculator reacts to overrides", value_roi)

        # ------------------------------------------------------------------ 7. readiness, fleet, kill switch, feature map
        def readiness() -> None:
            r.goto("/readiness")
            page.get_by_role("button", name="Assess readiness").click()
            expect(page.get_by_text("Prioritised roadmap").first).to_be_visible()
            expect(page.get_by_text(re.compile(r"/ 100 · target")).first).to_be_visible()
            r.shot("08-readiness-assessment")

        def fleet() -> None:
            r.goto("/fleet")
            expect(h1(page, "Fleet")).to_be_visible()
            for pid in ("KAT-1", "GDN-2", "MTY-3"):
                expect(page.get_by_role("cell", name=re.compile(pid)).first).to_be_visible(timeout=15000)
            r.shot("09-fleet")

        def kill_switch() -> None:
            r.goto("/")
            expect(page.get_by_text("● live")).to_be_visible(timeout=15000)
            page.get_by_role("button", name=re.compile("KILL SWITCH")).click()
            expect(page.get_by_role("alert").filter(has_text="Kill switch is ON")).to_be_visible(timeout=10000)
            r.shot("12-kill-switch")
            page.get_by_role("button", name="Release kill switch").click()
            expect(page.get_by_role("alert").filter(has_text="Kill switch is ON")).to_have_count(0, timeout=10000)

        def feature_map() -> None:
            r.goto("/features")
            expect(h1(page, "Feature Map")).to_be_visible()
            expect(page.get_by_text("25", exact=True).first).to_be_visible()
            expect(page.get_by_text("implemented", exact=True)).to_have_count(25, timeout=20000)
            r.shot("10-feature-map")

        r.journey("readiness: assessment, radar, roadmap", readiness)
        r.journey("fleet: three plants compared", fleet)
        r.journey("kill switch: banner shown, then released", kill_switch)
        r.journey("feature map: 25/25 implemented", feature_map)

        # ------------------------------------------------------------------ extra screens for the deck
        def extra_screens() -> None:
            for route, name, ready in (
                ("/maintenance", "13-predictive-maintenance", "Asset health"),
                ("/planner", "14-planner-gantt", "Gantt"),
                ("/quality", "15-quality-spc", "Process capability"),
                ("/deployment", "16-deployment", "Infrastructure as code"),
                ("/observability", "17-observability-finops", "FinOps"),
            ):
                r.goto(route)
                expect(page.get_by_text(re.compile(ready)).first).to_be_visible(timeout=20000)
                r.shot(name)

        r.journey("extra screens (maintenance, planner, quality, deployment, observability)", extra_screens)
        browser.close()

    api(base, "POST", "/api/sim/control", {"command": "speed", "value": speed0})
    print("\nPlaywright end-to-end journeys against", base)
    for name, ok, detail in r.results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<72} {detail}")
    if errors:
        print("\nbrowser errors:", *sorted(set(errors))[:8], sep="\n  ")
    failed = [n for n, ok, _ in r.results if not ok]
    print(f"\n{len(r.results) - len(failed)}/{len(r.results)} journeys passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
