#!/usr/bin/env python
"""Playwright end-to-end journeys for Spotlight (local or deployed) + 1600x900 screenshots for the deck.

    /Users/michalfu/Dev/SwarmAI/.venv/bin/python app/e2e/journeys.py --base-url http://127.0.0.1:8102 [--screens deck/assets/screens]

Journeys: dashboard · brief wizard (clarifying questions + completeness) · brand brain (cited retrieval) · claims / rights ·
creative workspace (storyboard keyframes, audio, rendered video player, formats, localization, provenance tamper test, scorecard) ·
Guardian playground (seeded violations blocked, auto-revise converges) · approvals inbox + audit chain · variants/bandit ·
performance insights · planner · asset library · cost meter · ROI/ACR calculator · team · ops · feature map.

The target must already contain one produced campaign (run scripts/smoke_test.py first, or pass --campaign ID); the script finds it through the API.
Exit code != 0 when any journey fails. Console errors and HTTP 5xx responses fail the run. Every screenshot waits for the page to settle
(no skeleton, spinner, "Loading…" text, undecoded image/video/audio or toast) and fails the journey if it never does; the scratch
"E2E —" campaigns created by the run (and only those) are deleted at the end. Against a deployed instance (a --base-url that is not
localhost) the waits on a model are raised: E2E_AI_TIMEOUT_MS (default 600000) and a 15 s default expectation timeout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

VIEWPORT = {"width": 1600, "height": 900}
PRE_EXISTING: set[str] = set()  # campaign ids that existed before this run: the scratch cleanup only removes what the run itself created
AI_FLOOR_MS = 0  # waits on a model: E2E_AI_TIMEOUT_MS, default 10 min against a deployed (non-localhost) instance


def ai(ms: int) -> int:
    return max(ms, AI_FLOOR_MS)

# A capture must never show a loading state (skeleton, spinner, "Loading…" text, undecoded image/video) or a lingering toast.
SETTLE_JS = """
() => {
  const inView = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth; };
  if (document.querySelector('.skeleton')) return 'skeleton';
  if (document.querySelector('[aria-label="loading"]')) return 'spinner';
  if (/(Loading|Connecting)…/.test(document.body.innerText)) return 'loading text';
  if (document.querySelector('[aria-live="polite"]')?.children.length) return 'toast';
  for (const i of document.images) if (inView(i) && !(i.complete && i.naturalWidth > 0)) return 'image ' + i.src.slice(-48);
  for (const v of document.querySelectorAll('video')) if (inView(v) && v.readyState < 2) return 'video ' + v.src.slice(-48);
  for (const a of document.querySelectorAll('audio')) if (inView(a) && a.preload !== 'none' && a.readyState < 1) return 'audio ' + a.src.slice(-48);
  return '';
}
"""


class Run:
    def __init__(self, base: str, screens: Path | None) -> None:
        self.base, self.screens = base.rstrip("/"), screens
        self.results: list[tuple[str, bool, float, str]] = []
        self.problems: list[str] = []

    def settle(self, page: Page, name: str, timeout_s: float = 30.0) -> None:
        t0 = time.monotonic()
        deadline = t0 + timeout_s
        reason = first = page.evaluate(SETTLE_JS)
        while reason and time.monotonic() < deadline:
            page.wait_for_timeout(250)
            reason = page.evaluate(SETTLE_JS)
        if reason:
            raise AssertionError(f"capture '{name}' would show a loading state ({reason})")
        if first and time.monotonic() - t0 > 3:
            print(f"    capture '{name}' waited {time.monotonic() - t0:.1f}s for: {first}", flush=True)

    def shot(self, page: Page, name: str, full: bool = False) -> None:
        page.mouse.move(1000, 885)  # park the pointer on the footer so no hover tooltip/state is captured
        self.settle(page, name)
        page.wait_for_timeout(700)  # let charts finish their animation
        self.settle(page, name, 5)
        if self.screens:
            self.screens.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(self.screens / f"{name}.png"), full_page=full)

    def journey(self, name: str, fn, page: Page) -> None:
        t0 = time.perf_counter()
        before = len(self.problems)
        try:
            fn(page)
            ok, detail = True, ""
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
        if len(self.problems) > before:
            ok, detail = False, (detail + " | " if detail else "") + "; ".join(self.problems[before:][:2])
        dt = time.perf_counter() - t0
        self.results.append((name, ok, dt, detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<58} {dt:5.1f}s  {detail}", flush=True)

    def go(self, page: Page, path: str) -> None:
        page.goto(self.base + path, wait_until="networkidle")


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310
        return json.loads(r.read())


def delete_scratch_campaigns(base: str) -> int:
    """Remove the 'E2E —' campaigns this script creates (their experiments go with them). Campaigns that existed before the run are never touched."""
    n = 0
    for c in get_json(f"{base}/api/campaigns"):
        if c["name"].startswith("E2E —") and c["id"] not in PRE_EXISTING:
            req = urllib.request.Request(f"{base}/api/campaigns/{c['id']}", method="DELETE", headers={"X-Studio-Role": "admin"})  # noqa: S310
            urllib.request.urlopen(req, timeout=60).read()  # noqa: S310
            n += 1
    return n


def produced_campaign(base: str, wanted: str = "") -> dict:
    if wanted:
        return get_json(f"{base}/api/campaigns/{wanted}")["campaign"]
    best = None
    for c in get_json(f"{base}/api/campaigns"):
        n = len(get_json(f"{base}/api/campaigns/{c['id']}/spot").get("spots", []))
        if n and (best is None or n > best[1]):
            best = (c, n)
    if not best:
        raise SystemExit("no produced campaign found — run scripts/smoke_test.py against this base URL first")
    return best[0]


def main() -> int:
    global AI_FLOOR_MS
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--screens", default=None, help="directory for 1600x900 screenshots (deck/assets/screens)")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--skip-live-ai", action="store_true", help="do not click buttons that call Azure OpenAI (brief analysis)")
    ap.add_argument("--campaign", default="", help="use this produced campaign (default: the one with the most spots)")
    args = ap.parse_args()
    run = Run(args.base_url, Path(args.screens) if args.screens else None)
    remote = (urllib.parse.urlparse(run.base).hostname or "") not in {"localhost", "127.0.0.1", "::1"}
    AI_FLOOR_MS = int(os.environ.get("E2E_AI_TIMEOUT_MS") or (600_000 if remote else 0))
    if remote:
        expect.set_options(timeout=15_000)  # deployed instance: network + Cosmos latency
    PRE_EXISTING.update(c["id"] for c in get_json(f"{run.base}/api/campaigns"))
    camp = produced_campaign(run.base, args.campaign)
    cid = camp["id"]
    print(f"E2E against {run.base} — campaign {cid!r} ({camp['name']})\n", flush=True)

    def dashboard(p: Page) -> None:
        run.go(p, "/")
        expect(p.get_by_role("heading", name="Brief to broadcast")).to_be_visible()
        expect(p.get_by_text("Open workspace →").first).to_be_visible()
        expect(p.get_by_text("Synthetic data / simulated environment")).to_be_visible()
        expect(p.locator("section", has_text="Recent activity").locator("li").first).to_be_visible(timeout=30000)  # the activity feed has no skeleton: wait for its rows
        run.shot(p, "01-dashboard")

    def brief_wizard(p: Page) -> None:
        run.go(p, "/campaigns/new")
        expect(p.get_by_test_id("brief-wizard")).to_be_visible()
        p.get_by_label("Campaign name").fill("E2E — Dawn Roast wizard")
        p.get_by_role("button", name="Continue").click()
        p.get_by_role("button", name="Load sample (Dawn Roast)").click()
        expect(p.get_by_label("Brief text")).not_to_be_empty()
        if args.skip_live_ai:
            run.shot(p, "02-brief-wizard")
            return
        p.get_by_role("button", name="Analyze with the Briefing agent").click()
        expect(p.get_by_test_id("questions")).to_be_visible(timeout=ai(90000))
        n = p.get_by_test_id("questions").locator("input").count()
        assert 1 <= n <= 3, f"expected 1-3 clarifying questions, got {n}"
        run.shot(p, "02-brief-wizard")

    def brand_brain(p: Page) -> None:
        run.go(p, "/brand")
        expect(p.get_by_test_id("brand-kit")).to_be_visible()
        expect(p.get_by_test_id("learnings").locator("li").first).to_be_visible(timeout=30000)
        p.get_by_role("button", name="Retrieve").click()
        expect(p.get_by_test_id("brain-hits").locator("li").first).to_be_visible(timeout=30000)
        assert p.get_by_test_id("brain-hits").locator("li").count() >= 3
        run.shot(p, "03-brand-brain")

    def claims_rights(p: Page) -> None:
        run.go(p, "/claims")
        expect(p.get_by_test_id("claims-table").locator("tbody tr").first).to_be_visible(timeout=30000)  # rows, not the loading skeleton
        p.get_by_role("button", name="Check").click()
        expect(p.get_by_test_id("claim-result")).to_contain_text("block", ignore_case=True)
        run.shot(p, "04-claims-library")
        run.go(p, "/rights")
        expect(p.get_by_test_id("rights-table").locator("tbody tr").first).to_be_visible(timeout=30000)
        p.get_by_role("button", name="Check clearance").click()
        expect(p.get_by_test_id("rights-result")).to_contain_text("NOT cleared")
        run.shot(p, "05-rights-registry")

    def workspace(p: Page) -> None:
        run.go(p, f"/campaigns/{cid}/storyboard")
        expect(p.get_by_test_id("shots").locator("img").first).to_be_visible(timeout=30000)
        assert p.get_by_test_id("shots").locator("img").count() >= 3
        run.shot(p, "06-creative-workspace-storyboard")
        run.go(p, f"/campaigns/{cid}/video")
        video = p.get_by_test_id("video-player").first
        expect(video).to_be_visible(timeout=30000)
        p.wait_for_function("() => { const v = document.querySelector('[data-testid=video-player]'); return v && v.readyState >= 2 && v.duration > 5; }", timeout=30000)
        assert p.evaluate("document.querySelector('[data-testid=video-player]').duration") > 5
        expect(p.get_by_test_id("probe")).to_contain_text("h264")
        p.evaluate("const v = document.querySelector('[data-testid=video-player]'); v.currentTime = 6; v.scrollIntoView({block: 'center'})")
        run.shot(p, "07-creative-workspace-video")
        run.go(p, f"/campaigns/{cid}/audio")
        expect(p.locator("audio").first).to_be_visible(timeout=30000)
        expect(p.get_by_test_id("music").get_by_role("button").first).to_be_visible(timeout=30000)  # the music candidates have no skeleton
        run.shot(p, "08-voice-and-music")
        run.go(p, f"/campaigns/{cid}/formats")
        expect(p.get_by_test_id("version-tree")).to_be_visible(timeout=30000)
        run.shot(p, "09-formats-and-cutdowns")
        run.go(p, f"/campaigns/{cid}/localization")
        expect(p.get_by_test_id("localizations").locator("table").first).to_be_visible(timeout=30000)
        run.shot(p, "10-localization")
        run.go(p, f"/campaigns/{cid}/scorecard")
        expect(p.get_by_test_id("scorecard")).to_be_visible(timeout=30000)
        run.shot(p, "11-preflight-scorecard")

    def provenance(p: Page) -> None:
        run.go(p, f"/campaigns/{cid}/provenance")
        expect(p.get_by_test_id("verification")).to_contain_text("authentic", timeout=30000)
        p.get_by_role("button", name="Run tamper test").click()
        expect(p.get_by_test_id("tamper-result")).to_contain_text("tampering detected", timeout=ai(60000))
        run.shot(p, "12-provenance-tamper-test")

    def guardian(p: Page) -> None:
        run.go(p, "/guardian")
        expect(p.get_by_label("line v1")).to_have_value("Dawn Roast cures morning anxiety.")
        p.get_by_role("button", name="Run Guardian").click()
        expect(p.get_by_test_id("verdict")).to_have_text("block", timeout=ai(60000))
        cov = p.get_by_test_id("seeded-coverage")
        expect(cov).to_be_visible()
        assert cov.get_by_text("failed").count() == 0, "a seeded violation was missed"
        p.evaluate("window.scrollTo(0, 0)")
        run.shot(p, "13-guardian-report-blocked")
        p.get_by_role("button", name="Auto-revise (≤3 iterations)").click()
        expect(p.get_by_test_id("iterations")).to_be_visible(timeout=ai(90000))
        expect(p.get_by_test_id("verdict")).not_to_have_text("block")
        p.evaluate("window.scrollTo(0, 0)")
        run.shot(p, "14-guardian-auto-revise")
        run.go(p, f"/campaigns/{cid}/guardian")
        expect(p.get_by_test_id("guardian-report")).to_be_visible(timeout=30000)

    def approvals(p: Page) -> None:
        run.go(p, "/approvals")
        expect(p.get_by_test_id("approval-inbox").locator("section").first).to_be_visible(timeout=30000)
        run.shot(p, "15-approvals-inbox")
        run.go(p, f"/campaigns/{cid}/approvals")
        expect(p.get_by_text("chain verified")).to_be_visible(timeout=30000)
        expect(p.get_by_test_id("campaign-approvals").locator("section").first).to_be_visible(timeout=30000)
        run.shot(p, "16-approvals-and-audit-chain")

    def variants(p: Page) -> None:
        run.go(p, "/experiments")
        expect(p.get_by_test_id("experiment-card")).to_be_visible(timeout=30000)  # the newest experiment opens automatically
        campaign_select = p.get_by_label("campaign")
        scratch = campaign_select.locator("option", has_text="E2E —")
        if scratch.count():  # the brief-wizard journey left a scratch campaign: exercise create → simulate on it (removed together with that campaign)
            campaign_select.select_option(label=scratch.first.inner_text())
            name = f"E2E bandit {int(time.time())}"
            p.get_by_label("Name", exact=True).fill(name)
            p.get_by_role("button", name="Create 12 variants").click()
            expect(p.get_by_role("heading", name=name)).to_be_visible(timeout=30000)  # the NEW experiment is open (not the previously selected one) …
            expect(p.get_by_test_id("experiment-card")).to_contain_text("draft")
            expect(p.get_by_test_id("variants-table").locator("tbody tr")).to_have_count(12)
            p.get_by_role("button", name="Run simulation").click()
            expect(p.get_by_test_id("experiment-card")).to_contain_text("completed", timeout=60000)  # … and it ran to completion
            expect(p.get_by_test_id("experiment-stats")).to_contain_text("Leader")
            delete_scratch_campaigns(run.base)
            run.go(p, "/experiments")  # fresh page: the capture below must not list the scratch experiment
            expect(p.get_by_test_id("experiment-card")).to_be_visible(timeout=30000)
        # capture the showcase experiment: reset and re-run 24 h (seeded, so the results are identical every time), then wait for ALL result panels
        campaign_select.select_option(value=cid)
        p.get_by_label("Name", exact=True).fill("Dawn Roast variant test")  # no scratch name left in the form of the capture
        showcase = p.get_by_role("button").filter(has_text="Smoke bandit")
        (showcase.first if showcase.count() else p.get_by_role("button").filter(has_text="variants ·").first).click()
        expect(p.get_by_test_id("experiment-card")).to_be_visible(timeout=30000)
        p.get_by_role("button", name="Reset").click()
        expect(p.get_by_test_id("experiment-card")).to_contain_text("draft", timeout=30000)
        p.get_by_role("button", name="Run simulation").click()
        expect(p.get_by_test_id("experiment-card")).to_contain_text("completed", timeout=60000)
        stats = p.get_by_test_id("experiment-stats")
        expect(stats).to_contain_text("Leader", timeout=30000)
        expect(stats).to_contain_text("Auto-paused losers")
        expect(p.get_by_test_id("allocation-chart").locator("svg.recharts-surface").first).to_be_visible()
        expect(p.locator("[data-testid=allocation-chart] .recharts-area-area").first).to_be_visible()  # the stacked areas are drawn
        table = p.get_by_test_id("variants-table")
        expect(table.locator("tbody tr")).to_have_count(12)
        expect(table).to_contain_text("paused")
        expect(table).to_contain_text("control")
        assert table.locator("tbody tr", has_text="yes").count() >= 1, "no variant is significantly different from the control"
        p.evaluate(  # leader tiles + allocation chart + significance table in one frame, just below the sticky top bar
            """() => {
              const el = document.querySelector('[data-testid=experiment-stats]');
              let s = el.parentElement;
              while (s && !(s.scrollHeight > s.clientHeight && /(auto|scroll)/.test(getComputedStyle(s).overflowY))) s = s.parentElement;
              if (s) s.scrollTop += el.getBoundingClientRect().top - s.getBoundingClientRect().top - 14;
            }"""
        )
        run.shot(p, "17-variants-bandit-experiment")

    def performance(p: Page) -> None:
        run.go(p, "/performance")
        expect(p.get_by_test_id("perf-stats")).to_be_visible(timeout=30000)
        p.get_by_role("button", name="Generate insights").click()
        expect(p.get_by_test_id("insights").locator("li").first).to_be_visible(timeout=30000)
        run.shot(p, "18-performance-insights")

    def planner(p: Page) -> None:
        run.go(p, "/planner")
        expect(p.get_by_test_id("plan-stats")).to_be_visible(timeout=30000)
        run.shot(p, "19-media-planner")

    def library(p: Page) -> None:
        run.go(p, "/library")
        expect(p.get_by_test_id("asset-grid").locator("button").first).to_be_visible(timeout=30000)
        p.get_by_label("search").fill("storyboard")
        expect(p.get_by_test_id("asset-grid").locator("button").first).to_be_visible(timeout=30000)
        p.get_by_label("search").fill("")
        run.shot(p, "20-asset-library")
        p.get_by_test_id("asset-grid").locator("button").first.click()
        expect(p.get_by_role("dialog")).to_be_visible()
        p.keyboard.press("Escape")

    def cost(p: Page) -> None:
        run.go(p, "/cost")
        expect(p.get_by_test_id("cost-chart").locator("svg").first).to_be_visible(timeout=30000)
        expect(p.get_by_text("Guard", exact=True)).to_be_visible()
        run.shot(p, "21-cost-meter")

    def roi(p: Page) -> None:
        run.go(p, "/roi")
        kpis = p.get_by_test_id("roi-kpis")
        expect(kpis).to_contain_text("140%", timeout=30000)  # Base reference values: ROI 140 %, NPV $6.98M, payback 15.0 mo, ACR Y1/Y2/Y3 $65k/$305k/$465k
        for text in ("$6.98M", "15.0 mo"):
            expect(kpis).to_contain_text(text)
        expect(p.get_by_test_id("roi-acr-years")).to_have_text("Y1 $65k · Y2 $305k · Y3 $465k")
        expect(p.get_by_test_id("roi-cashflow").locator("svg").first).to_be_visible()
        expect(p.get_by_test_id("roi-tiers")).to_contain_text("Enterprise scale")  # the fifth tier
        expect(p.get_by_test_id("roi-enterprise")).to_contain_text("$2.63M")
        assert p.get_by_test_id("roi-tiers").locator("tbody tr").count() == 5
        before = kpis.inner_text()
        p.get_by_role("tab", name="Conservative", exact=True).click()
        p.wait_for_function("(b) => document.querySelector('[data-testid=roi-kpis]').innerText !== b", arg=before, timeout=15000)
        p.get_by_role("tab", name="Upside", exact=True).click()
        expect(p.get_by_test_id("roi-acr-years")).to_contain_text("Y3 $973k", timeout=15000)
        p.get_by_role("tab", name="Base", exact=True).click()
        expect(p.get_by_test_id("roi-acr-years")).to_have_text("Y1 $65k · Y2 $305k · Y3 $465k", timeout=15000)
        p.get_by_role("tab", name="Expansion on", exact=True).click()  # Base vs Expansion on (expansion_scale 0 -> 1): ACR by lever appears
        expect(p.get_by_test_id("roi-acr-years")).to_contain_text("Y3 $940k", timeout=15000)
        expect(p.get_by_test_id("roi-lever")).to_contain_text("E3", timeout=15000)
        run.shot(p, "22b-roi-expansion-on")
        p.get_by_role("tab", name="Expansion off", exact=True).click()
        expect(p.get_by_test_id("roi-acr-years")).to_have_text("Y1 $65k · Y2 $305k · Y3 $465k", timeout=15000)
        p.evaluate("window.scrollTo(0, 0)")
        run.shot(p, "22-roi-acr-calculator")

    def team(p: Page) -> None:
        run.go(p, "/team")
        expect(p.get_by_test_id("permission-matrix").locator("tbody tr").first).to_be_visible(timeout=30000)
        expect(p.get_by_text("Recent deliveries")).to_be_visible()
        run.shot(p, "23-team-and-integrations")

    def ops(p: Page) -> None:
        run.go(p, "/ops")
        expect(p.get_by_text("Dependencies (/readyz)")).to_be_visible()
        expect(p.get_by_text("Real calls to Cosmos DB")).to_be_visible()
        run.shot(p, "24-ops-observability")

    def feature_map(p: Page) -> None:
        run.go(p, "/features")
        expect(p.get_by_role("heading", name="Feature map")).to_be_visible()
        assert p.locator("text=CS-25").count() >= 1 and p.locator("text=implemented").count() >= 25
        run.shot(p, "25-feature-map")

    def api_docs(p: Page) -> None:
        run.go(p, "/docs")
        expect(p.locator(".swagger-ui").first).to_be_visible(timeout=30000)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        ctx = browser.new_context(viewport=VIEWPORT, locale="en-US")
        page = ctx.new_page()
        page.on("console", lambda m: run.problems.append(f"console error: {m.text[:120]}") if m.type == "error" and "favicon" not in m.text else None)
        page.on("pageerror", lambda e: run.problems.append(f"page error: {str(e)[:120]}"))
        page.on("response", lambda r: run.problems.append(f"HTTP {r.status} {r.url[-80:]}") if r.status >= 500 else None)
        for name, fn in [
            ("dashboard", dashboard), ("brief wizard (clarifying questions, completeness)", brief_wizard), ("brand brain (cited retrieval)", brand_brain),
            ("claims + rights registries", claims_rights), ("creative workspace (storyboard, video player, audio, formats, localization, scorecard)", workspace),
            ("provenance verification + tamper test", provenance), ("guardian playground (blocked report, auto-revise)", guardian),
            ("approvals inbox + audit chain", approvals), ("variants / bandit experiment", variants), ("performance insights", performance),
            ("media planner", planner), ("asset library", library), ("cost meter", cost), ("ROI / ACR calculator", roi),
            ("team & integrations", team), ("ops & observability", ops), ("feature map", feature_map), ("API docs (swagger)", api_docs),
        ]:
            run.journey(name, fn, page)
        browser.close()
    removed = delete_scratch_campaigns(run.base)
    if removed:
        print(f"\nremoved {removed} scratch 'E2E —' campaign(s) created by this run")
    failed = [r for r in run.results if not r[1]]
    print(f"\n{len(run.results) - len(failed)}/{len(run.results)} journeys passed" + (f"; FAILED: {[r[0] for r in failed]}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
