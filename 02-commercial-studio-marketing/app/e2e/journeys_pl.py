#!/usr/bin/env python
"""Playwright end-to-end journeys for Spotlight IN POLISH (local or deployed) + 1600x900 screenshots for the Polish deck.

    /Users/michalfu/Dev/SwarmAI/.venv/bin/python app/e2e/journeys_pl.py --base-url http://127.0.0.1:8102
    BASE_URL=https://<app>.azurecontainerapps.io  .../python app/e2e/journeys_pl.py          # against a deployed instance

Screenshots go to deck/assets/screens-pl/ (NEVER to deck/assets/screens/, which feeds the English decks) — pass --screens DIR to change it, --no-screens to skip.

What it proves (each journey is a PASS/FAIL line; exit code != 0 when any fails):
  language behaviour   header switch on every route, ?lang=pl, remembered in localStorage, <html lang>, no page reload, Accept-Language + X-UI-Lang on every API call,
                       ?lang= on the SSE stream, data refetched on a switch, "Język kampanii" select follows the UI language until chosen
  Polish pipeline      Polish brief → clarifying questions → strategy → script → Guardian BLOCK on a Polish prohibited claim → auto-revise → storyboard → voice-over →
                       render → formats → localization PL → EN → scorecard → provenance + tamper test → approvals + audit chain → variants → performance → planner → ROI
  per-page quality     on every page: window.__i18nMissing empty, no English leftovers, no raw enum values, pl-PL number/date formats, no overflow / clipped text / cut-off
                       <select> values, console clean, Polish letters drawn by the bundled Inter / Fraunces (latin-ext)

The scratch campaign ("E2E — Dawn Roast premiera PL") created by the run is deleted at the end — ONLY the campaigns this run created (never other "E2E —" campaigns, so the suite is safe on a shared
deployment). Use --skip-live-ai to reuse a produced scratch campaign (kept by an earlier --keep-scratch run, or --campaign ID) instead of calling the AI pipeline (brief analysis, strategy,
script, keyframes, voice-over, render, localization); journeys that need such a campaign are reported as SKIPPED when there is none.

Against a deployed instance (any --base-url that is not localhost) the waits for AI work are raised automatically: E2E_AI_TIMEOUT_MS (default 600000) caps every wait on a model / job, and
Playwright's default expectation timeout becomes 15 s. Assertions on model-generated text are pattern-based (Polish stems / letters), never exact sentences.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import contextmanager, suppress
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pl_checks import glyph_check, scan_page

VIEWPORT = {"width": 1600, "height": 900}
HERE = Path(__file__).resolve().parent
DEFAULT_SCREENS = HERE.parent.parent / "deck" / "assets" / "screens-pl"
ENGLISH_SCREENS = HERE.parent.parent / "deck" / "assets" / "screens"
SCRATCH = "E2E —"
SCRATCH_NAME = f"{SCRATCH} Dawn Roast premiera PL"


class Skip(Exception):
    """A journey that cannot run in this configuration (reported as SKIPPED, not as a failure)."""


def is_local(url: str) -> bool:
    return (urllib.parse.urlparse(url).hostname or "") in {"localhost", "127.0.0.1", "::1"}

# A capture must never show a loading state (skeleton, spinner, "Wczytywanie…" text, undecoded image/video) or a lingering toast.
SETTLE_JS = """
() => {
  const inView = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth; };
  if (document.querySelector('.skeleton')) return 'skeleton';
  if (document.querySelector('[data-spinner]')) return 'spinner';
  if (/(Loading|Connecting|Wczytywanie|Łączenie)[^\\n]{0,24}…/.test(document.body.innerText)) return 'loading text';
  if (document.querySelector('[aria-live="polite"]')?.children.length) return 'toast';
  for (const i of document.images) if (inView(i) && !(i.complete && i.naturalWidth > 0)) return 'image ' + i.src.slice(-48);
  for (const v of document.querySelectorAll('video')) if (inView(v) && v.readyState < 2) return 'video ' + v.src.slice(-48);
  for (const a of document.querySelectorAll('audio')) if (inView(a) && a.preload !== 'none' && a.readyState < 1) return 'audio ' + a.src.slice(-48);
  return '';
}
"""

ROUTES = ["/", "/brand", "/claims", "/rights", "/campaigns/new", "/guardian", "/approvals", "/experiments", "/performance", "/planner", "/library", "/cost", "/team", "/roi", "/ops", "/features"]


def get_json(url: str, lang: str = "pl", role: str = "admin"):
    req = urllib.request.Request(url, headers={"X-UI-Lang": lang, "Accept-Language": lang, "X-Studio-Role": role})  # noqa: S310
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        return json.loads(r.read())


def post_json(url: str, body: dict, lang: str = "pl", role: str = "creative_director"):
    req = urllib.request.Request(  # noqa: S310
        url, data=json.dumps(body).encode(), method="POST",
        headers={"X-UI-Lang": lang, "Accept-Language": lang, "X-Studio-Role": role, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310
        return json.loads(r.read())


class Run:
    def __init__(self, base: str, screens: Path | None) -> None:
        self.base, self.screens = base.rstrip("/"), screens
        self.results: list[tuple[str, bool, float, str]] = []
        self.skipped: list[str] = []
        self.problems: list[str] = []
        self.shots: list[str] = []
        self.content: set[str] = set()
        self.cid: str | None = None
        self.scratch_ids: list[str] = []
        self.pages_checked = 0
        self.allowed_console: list[str] = []  # regexes of console errors a journey provokes ON PURPOSE (the browser logs every 4xx response)
        self.preexisting: set[str] = set()  # campaign ids that existed before this run: the cleanup never touches them

    # ------------------------------------------------------------------------------------------------ helpers
    def T(self, page: Page, key: str, **vars_: object) -> str:
        """The label in the CURRENT UI language, straight from the app's dictionary (window.__i18n)."""
        return page.evaluate("([k, v]) => window.__i18n.t(k, v)", [key, vars_])

    def TN(self, page: Page, n: float, one: str, other: str, **vars_: object) -> str:
        return page.evaluate("([n, f, v]) => window.__i18n.tn(n, f, v)", [n, {"one": one, "other": other}, vars_])

    def E(self, page: Page, group: str, ident: str) -> str:
        return page.evaluate("([g, i]) => window.__i18n.tEnum(g, i)", [group, ident])

    def go(self, page: Page, path: str, spa: bool = True) -> None:
        page.goto(self.base + path, wait_until="networkidle")
        if spa:
            page.wait_for_function("() => !!window.__i18n")

    def settle(self, page: Page, name: str, timeout_s: float = 30.0) -> None:
        t0 = time.monotonic()
        reason = first = page.evaluate(SETTLE_JS)
        while reason and time.monotonic() - t0 < timeout_s:
            page.wait_for_timeout(250)
            reason = page.evaluate(SETTLE_JS)
        if reason:
            raise AssertionError(f"capture '{name}' would show a loading state ({reason})")
        if first and time.monotonic() - t0 > 3:
            print(f"    capture '{name}' waited {time.monotonic() - t0:.1f}s for: {first}", flush=True)

    def shot(self, page: Page, name: str, full: bool = False) -> None:
        page.mouse.move(1000, 885)  # park the pointer on the footer so no hover tooltip is captured
        self.settle(page, name)
        page.wait_for_timeout(700)  # let charts finish their animation
        self.settle(page, name, 5)
        if self.screens:
            self.screens.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(self.screens / f"{name}.png"), full_page=full)
            self.shots.append(name)

    def check(self, page: Page, route: str, allow: list[str] | None = None) -> None:
        """Quality gate for the page in its current state (called after the page settled)."""
        self.settle(page, f"check {route}", 20)
        found = scan_page(page, route, self.content, "pl", allow)
        self.pages_checked += 1
        for p in found.problems()[:12]:
            self.problems.append(f"{route}: {p}")

    def refresh_content(self) -> None:
        """Strings that are customer / generated CONTENT and may stay as they are (campaign names, artifact titles, asset and document names …)."""
        c: set[str] = set()
        try:
            for camp in get_json(f"{self.base}/api/campaigns"):
                c.add(camp["name"])
            for a in get_json(f"{self.base}/api/library/assets").get("assets", [])[:200]:
                c.update(x for x in (a.get("name"), a.get("title")) if x)
            for d in get_json(f"{self.base}/api/brand").get("documents", []):
                c.add(d["name"])
            for r in get_json(f"{self.base}/api/rights").get("entries", []):
                c.update(x for x in (r.get("title"), r.get("notes"), r.get("source")) if x)
            for e in get_json(f"{self.base}/api/experiments"):
                c.add(e["name"])
            if self.cid:
                for art in get_json(f"{self.base}/api/campaigns/{self.cid}").get("artifacts", []):
                    if art.get("title"):
                        c.add(art["title"])
        except Exception as exc:
            print(f"    (content refresh: {exc})", flush=True)
        self.content = {x for x in c if x and len(x) > 3}

    @contextmanager
    def api_calls(self, page: Page):
        log: list = []

        def on_request(r) -> None:
            if "/api/" in r.url and r.resource_type in {"fetch", "xhr", "eventsource", "other"}:
                log.append(r)

        page.on("request", on_request)
        try:
            yield log
        finally:
            page.remove_listener("request", on_request)

    def assert_headers(self, log: list, lang: str, what: str) -> None:
        assert log, f"{what}: no API request was made"
        bad = []
        for r in log:
            h = {k.lower(): v for k, v in r.headers.items()}
            if r.resource_type == "eventsource" or "/api/stream/" in r.url:
                if f"lang={lang}" not in r.url:
                    bad.append(f"SSE without ?lang={lang}: {r.url[-60:]}")
                continue
            if h.get("x-ui-lang") != lang or not h.get("accept-language", "").lower().startswith(lang):
                bad.append(f"{r.method} {r.url[-60:]}: X-UI-Lang={h.get('x-ui-lang')!r} Accept-Language={h.get('accept-language')!r}")
        assert not bad, f"{what}: {len(bad)} API call(s) without the {lang!r} headers, e.g. {bad[:2]}"

    def journey(self, name: str, fn: Callable[[], None], page: Page | None = None) -> None:
        t0 = time.perf_counter()
        before = len(self.problems)
        exc_lines: list[str] = []
        try:
            fn()
            ok, detail = True, ""
        except Skip as why:
            self.skipped.append(name)
            self.problems[before:] = []
            self.results.append((name, True, time.perf_counter() - t0, f"SKIPPED: {why}"))
            print(f"  SKIP  {name:<62} {time.perf_counter() - t0:5.1f}s  {why}", flush=True)
            return
        except Exception as exc:
            exc_lines = (str(exc).splitlines() or [""])
            first = exc_lines[0][:230]
            ok, detail = False, f"{type(exc).__name__}: {first}"
            if page is not None:
                try:
                    if self.screens:
                        (self.screens.parent / "_failures").mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(self.screens.parent / "_failures" / f"{re.sub(r'[^a-z0-9]+', '-', name.lower())[:50]}.png"))
                except Exception:
                    pass
        new = self.problems[before:]
        if new:
            ok = False
            detail = (detail + " | " if detail else "") + "; ".join(new[:3]) + (f" (+{len(new) - 3} more)" if len(new) > 3 else "")
        dt = time.perf_counter() - t0
        self.results.append((name, ok, dt, detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<62} {dt:5.1f}s  {detail}", flush=True)
        if not ok and new:
            for p in new[3:12]:
                print(f"        · {p}", flush=True)
        if not ok and exc_lines:
            for ln in exc_lines[1:4]:
                print(f"        > {ln.strip()[:200]}", flush=True)


def delete_scratch(base: str, ids: list[str], preexisting: set[str], sweep_stale: bool = False) -> int:
    """Deletes the campaigns THIS run created: the tracked ids, plus any campaign named exactly like the scratch campaign that appeared after the run started
    (a wizard journey that failed half-way). Other people's "E2E —" campaigns are never touched, unless sweep_stale is asked for explicitly (--cleanup-stale)."""
    n = 0
    seen = set(ids)
    for c in get_json(f"{base}/api/campaigns"):
        if c["id"] in preexisting:
            if sweep_stale and c["name"].startswith(SCRATCH):
                seen.add(c["id"])
        elif c["name"] == SCRATCH_NAME:
            seen.add(c["id"])
    for cid in seen:
        try:
            req = urllib.request.Request(f"{base}/api/campaigns/{cid}", method="DELETE", headers={"X-Studio-Role": "admin"})  # noqa: S310
            urllib.request.urlopen(req, timeout=60).read()  # noqa: S310
            n += 1
        except Exception:
            pass
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("BASE_URL"), help="app URL (default: $BASE_URL)")
    ap.add_argument("--screens", default=str(DEFAULT_SCREENS), help="directory for the 1600x900 screenshots (default deck/assets/screens-pl)")
    ap.add_argument("--no-screens", action="store_true")
    ap.add_argument("--viewport", default="1600x900", help="WxH of the browser window (use 1280x720 for the small-screen overflow pass)")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--skip-live-ai", action="store_true", help="reuse a produced scratch campaign instead of running the AI pipeline (journeys that need one are SKIPPED when there is none)")
    ap.add_argument("--keep-scratch", action="store_true", help="do not delete the scratch campaign at the end (lets a later --skip-live-ai run reuse the produced campaign)")
    ap.add_argument("--campaign", default="", help="campaign id to reuse with --skip-live-ai (default: the newest produced scratch campaign)")
    ap.add_argument("--cleanup-stale", action="store_true", help="ALSO delete every older campaign whose name starts with 'E2E —' at the end (never the default on a shared deployment)")
    ap.add_argument("--only", default="", help="comma separated journey name fragments to run")
    args = ap.parse_args()
    if not args.base_url:
        ap.error("--base-url (or $BASE_URL) is required")
    screens = None if args.no_screens else Path(args.screens)
    if screens and screens.resolve() == ENGLISH_SCREENS.resolve():
        ap.error("refusing to write Polish screenshots into deck/assets/screens (the English deck's folder)")
    vw, vh = (int(x) for x in args.viewport.split("x"))
    viewport = {"width": vw, "height": vh}
    if screens and (vw, vh) != (1600, 900):
        screens = screens.parent / f"{screens.name}-{vw}x{vh}"  # other sizes never overwrite the deck screenshots
    run = Run(args.base_url, screens)
    only = [x.strip().lower() for x in args.only.split(",") if x.strip()]
    remote = not is_local(run.base)
    # ONE knob for everything that waits on a model / job: E2E_AI_TIMEOUT_MS (default: 10 min on a deployed instance, the per-call defaults below locally)
    ai_floor = int(os.environ.get("E2E_AI_TIMEOUT_MS") or (600_000 if remote else 0))

    def ai(ms: int) -> int:
        return max(ms, ai_floor)

    expect.set_options(timeout=15_000 if remote else 5_000)
    print(f"Polish E2E against {run.base} — viewport {vw}x{vh}" + (f" — screenshots → {screens}" if screens else "") + (f" — remote: AI waits ≥ {ai_floor // 1000} s" if ai_floor else "") + "\n", flush=True)

    try:
        run.preexisting = {c["id"] for c in get_json(f"{run.base}/api/campaigns")}
    except Exception as exc:
        print(f"    (could not list campaigns: {exc})", flush=True)

    cleaned = {"done": False}

    def cleanup() -> int:
        """Removes the campaigns this run created (also on an unexpected crash: registered with atexit)."""
        if cleaned["done"] or args.keep_scratch:
            return 0
        cleaned["done"] = True
        try:
            return delete_scratch(run.base, run.scratch_ids, run.preexisting, args.cleanup_stale)
        except Exception as exc:
            print(f"    (scratch cleanup failed: {exc})", flush=True)
            return 0

    atexit.register(cleanup)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)

        def new_context(locale: str = "pl-PL") -> BrowserContext:
            c = browser.new_context(viewport=viewport, locale=locale, timezone_id="Europe/Warsaw")
            if remote:
                c.set_default_navigation_timeout(60_000)
            return c

        def instrument(p: Page) -> None:
            def on_console(m) -> None:
                if m.type == "error" and "favicon" not in m.text:
                    url = (m.location or {}).get("url", "")
                    if any(re.search(a, f"{m.text} {url}") for a in run.allowed_console):
                        return
                    where = f" ({url[-70:]})" if url else ""
                    run.problems.append(f"console error: {m.text[:110]}{where}")

            p.on("console", on_console)
            p.on("pageerror", lambda e: run.problems.append(f"page error: {str(e)[:140]}"))
            p.on("response", lambda r: run.problems.append(f"HTTP {r.status} {r.url[-80:]}") if r.status >= 500 else None)

        ctx = new_context()
        page = ctx.new_page()
        instrument(page)
        run.refresh_content()

        def selected(name_fragment: str) -> bool:
            return not only or any(o in name_fragment.lower() for o in only)

        def J(name: str, fn: Callable[[], None], p: Page | None = None) -> None:
            if selected(name):
                run.journey(name, fn, p or page)

        # ============================================================================================ language behaviour
        def lang_state(p: Page) -> dict:
            return p.evaluate("() => ({ html: document.documentElement.lang, saved: localStorage.getItem('studio.lang'), h1: document.querySelector('h1')?.innerText ?? '' })")

        def behaviour_url_and_storage() -> None:
            c = browser.new_context(viewport=viewport, locale="en-US", timezone_id="Europe/Warsaw")
            p = c.new_page()
            instrument(p)
            run.go(p, "/")
            s = lang_state(p)
            assert s["html"] == "en" and s["h1"] == "Brief to broadcast", f"English browser must start in English: {s}"
            run.go(p, "/?lang=pl")
            s = lang_state(p)
            assert s["html"] == "pl" and s["saved"] == "pl" and s["h1"] == "Od briefu do emisji", f"?lang=pl must switch to Polish and remember it: {s}"
            assert "ł" in p.title() or "Spotlight" in p.title()
            run.go(p, "/claims")  # no parameter: the saved choice wins over navigator.languages (en-US)
            s = lang_state(p)
            assert s["html"] == "pl" and s["saved"] == "pl", f"the choice must survive navigation without ?lang=: {s}"
            run.go(p, "/?lang=en")
            s = lang_state(p)
            assert s["html"] == "en" and s["saved"] == "en" and s["h1"] == "Brief to broadcast", s
            c.close()

        def behaviour_switch_no_reload() -> None:
            run.go(page, "/?lang=pl")  # fresh state for this context
            assert lang_state(page)["html"] == "pl"
            page.evaluate("window.__noReload = 'still the same page'")
            switcher = page.get_by_test_id("lang-switcher")
            expect(switcher).to_be_visible()
            with run.api_calls(page) as log:
                switcher.select_option("en")
                expect(page.locator("h1")).to_have_text("Brief to broadcast")
                page.wait_for_timeout(900)
            s = lang_state(page)
            assert s["html"] == "en" and s["saved"] == "en", s
            assert page.evaluate("window.__noReload") == "still the same page", "switching the language must not reload the page"
            run.assert_headers(log, "en", "requests after switching to English")
            assert any("/api/studio/overview" in r.url for r in log), "the dashboard data was not re-requested after the language switch"
            assert page.get_by_role("link", name="New brief").first.is_visible(), "navigation is not English after the switch"
            # the saved choice wins over the browser's own language (pl-PL) on a reload
            page.reload(wait_until="networkidle")
            assert lang_state(page)["html"] == "en", "the saved English choice must beat navigator.languages (pl-PL) after a reload"
            with run.api_calls(page) as log:
                page.get_by_test_id("lang-switcher").select_option("pl")
                expect(page.locator("h1")).to_have_text("Od briefu do emisji")
                page.wait_for_timeout(900)
            run.assert_headers(log, "pl", "requests after switching back to Polish")
            assert lang_state(page)["html"] == "pl"

        def behaviour_browser_language() -> None:
            c = new_context("pl-PL")
            p = c.new_page()
            instrument(p)
            run.go(p, "/")  # nothing saved, no ?lang=: navigator.languages decides
            s = lang_state(p)
            assert s["html"] == "pl" and s["h1"] == "Od briefu do emisji", f"a Polish browser must get the Polish UI by default: {s}"
            assert p.evaluate("localStorage.getItem('studio.lang')") in (None, "pl")
            c.close()

        def behaviour_switch_everywhere() -> None:
            run.go(page, "/?lang=pl")
            for route in ROUTES + (["/campaigns/" + run.cid + "/script"] if run.cid else []):
                run.go(page, route)
                expect(page.get_by_test_id("lang-switcher")).to_be_visible()
                assert page.evaluate("document.documentElement.lang") == "pl", route
                expect(page.get_by_test_id("lang-switcher")).to_have_value("pl")
            # the language control is a labelled <select> (accessible name in the UI language)
            assert page.get_by_label(run.T(page, "Language")).count() >= 1

        def behaviour_api_headers_and_sse() -> None:
            run.go(page, "/claims")
            with run.api_calls(page) as log:
                page.get_by_test_id("lang-switcher").select_option("en")
                expect(page.locator("h1")).to_have_text("Claims library")
                page.wait_for_timeout(4500)  # the per-language query cache stays fresh for 4 s: let it go stale so the switch back refetches
                page.get_by_test_id("lang-switcher").select_option("pl")
                expect(page.locator("h1")).to_have_text("Biblioteka claimów")
                page.wait_for_timeout(900)
            langs = {r.headers.get("x-ui-lang") for r in log if "/api/claims" in r.url}
            assert {"en", "pl"} <= langs, f"/api/claims must be re-requested in each language, saw {langs}"
            # SSE: every job stream carries ?lang= (checked for real while the pipeline runs: see the strategy journey)

        def behaviour_campaign_language_select() -> None:
            run.go(page, "/?lang=pl")
            run.go(page, "/campaigns/new")
            sel = page.get_by_test_id("campaign-language")
            expect(sel).to_have_value("pl")  # defaults to the UI language …
            assert run.T(page, "Campaign language") in (page.get_by_label(run.T(page, "Campaign language")).first.get_attribute("aria-label") or "")
            page.get_by_test_id("lang-switcher").select_option("en")
            expect(sel).to_have_value("en")  # … and follows it until the user chooses
            sel.select_option("pl")  # explicit choice
            page.get_by_test_id("lang-switcher").select_option("pl")
            page.get_by_test_id("lang-switcher").select_option("en")
            expect(sel).to_have_value("pl")  # sticks
            page.get_by_test_id("lang-switcher").select_option("pl")
            expect(sel).to_have_value("pl")

        J("language: ?lang=, localStorage, <html lang>, saved beats browser", behaviour_url_and_storage)
        J("language: switch without reload, headers, refetch", behaviour_switch_no_reload)
        J("language: Polish browser gets Polish by default", behaviour_browser_language)
        J("language: header switch on every page", behaviour_switch_everywhere)
        J("language: Accept-Language + X-UI-Lang on API calls", behaviour_api_headers_and_sse)
        J("language: campaign language select (defaults to UI, editable)", behaviour_campaign_language_select)

        # ============================================================================================ static pages
        def brand_brain() -> None:
            run.go(page, "/brand")
            expect(page.get_by_test_id("brand-kit")).to_be_visible()
            expect(page.get_by_test_id("learnings").locator("li").first).to_be_visible(timeout=30000)
            page.get_by_label(run.T(page, "brand question")).fill("Jaki jest głos i ton marki?")
            page.get_by_role("button", name=run.T(page, "Retrieve")).click()
            expect(page.get_by_test_id("brain-hits").locator("li").first).to_be_visible(timeout=30000)
            assert page.get_by_test_id("brain-hits").locator("li").count() >= 3
            expect(page.get_by_test_id("brand-kit")).to_contain_text("Obudź się powoli", timeout=10000)  # the Polish tagline of the kit
            run.check(page, "/brand")
            run.shot(page, "03-brand-brain")

        def claims_library() -> None:
            run.go(page, "/claims")
            expect(page.get_by_test_id("claims-table").locator("tbody tr").first).to_be_visible(timeout=30000)
            expect(page.get_by_test_id("claims-lang")).to_have_value("pl")  # the claim pack follows the UI language
            rows_pl = page.get_by_test_id("claims-table").locator("tbody tr").count()
            assert rows_pl >= 10, f"Polish claim pack too small: {rows_pl}"
            # diacritic-insensitive search, ł included: the pack has "Palona w małych partiach" → "malych" finds it
            page.get_by_label(run.T(page, "search claims")).fill("malych")
            expect(page.get_by_test_id("claims-table")).to_contain_text("małych")
            page.get_by_label(run.T(page, "search claims")).fill("")
            page.get_by_label(run.T(page, "claim language")).select_option("all")
            assert page.get_by_test_id("claims-table").locator("tbody tr").count() > rows_pl
            page.get_by_label(run.T(page, "claim language")).select_option("pl")
            unsorted = page.evaluate(
                """() => {
                  const c = new Intl.Collator('pl', { sensitivity: 'base', numeric: true });
                  const rows = [...document.querySelectorAll('[data-testid=claims-table] tbody tr')].map((tr) => ({ t: tr.children[1].innerText.trim(), n: tr.children[0].querySelector('b').innerText.trim() }));
                  const bad = [];
                  for (let i = 1; i < rows.length; i++) if (rows[i].t === rows[i - 1].t && c.compare(rows[i - 1].n, rows[i].n) > 0) bad.push([rows[i - 1].n, rows[i].n]);
                  return bad;
                }"""
            )
            assert not unsorted, f"claims must be sorted in the Polish alphabet within each type: {unsorted[:3]}"
            run.check(page, "/claims")
            run.shot(page, "04-claims-library")

        def claims_checker() -> None:
            run.go(page, "/claims")
            page.get_by_role("button", name=run.T(page, "Check"), exact=True).click()
            expect(page.get_by_test_id("claim-result")).to_be_visible(timeout=15000)
            expect(page.get_by_test_id("claim-result")).to_contain_text(run.E(page, "status", "block"), ignore_case=True)  # a Polish prohibited claim → block, verdict in Polish
            assert page.get_by_test_id("claim-result").locator("mark").count() >= 1, "the prohibited Polish phrase must be highlighted"
            run.check(page, "/claims (checker)")

        def rights_registry() -> None:
            run.go(page, "/rights")
            expect(page.get_by_test_id("rights-table").locator("tbody tr").first).to_be_visible(timeout=30000)
            page.get_by_role("button", name=run.T(page, "Check clearance")).click()
            expect(page.get_by_test_id("rights-result")).to_be_visible(timeout=15000)
            run.check(page, "/rights")
            run.shot(page, "05-rights-registry")

        J("brand brain (Polish retrieval, Polish kit)", brand_brain)
        J("claims library (Polish pack, language filter, diacritic-insensitive search)", claims_library)
        J("claims checker (Polish prohibited claim → block)", claims_checker)
        J("rights registry", rights_registry)

        # ============================================================================================ Polish pipeline
        def brief_wizard() -> None:
            run.go(page, "/campaigns/new")
            expect(page.get_by_test_id("brief-wizard")).to_be_visible()
            page.get_by_label(run.T(page, "Campaign name")).fill(f"{SCRATCH} Dawn Roast premiera PL")
            expect(page.get_by_test_id("campaign-language")).to_have_value("pl")
            for m in ("US", "DE", "FR"):  # a Polish campaign for the Polish market
                page.get_by_role("button", name=m, exact=True).click()
            run.check(page, "/campaigns/new (step 1)")
            page.get_by_role("button", name=run.T(page, "Continue")).click()
            page.get_by_role("button", name=run.T(page, "Load sample (Dawn Roast)")).click()
            expect(page.get_by_label(run.T(page, "Brief text"))).to_contain_text("Wprowadzamy na rynek Dawn Roast")  # the Polish sample, not the English one
            page.get_by_role("button", name=run.T(page, "Analyze with the Briefing agent")).click()
            # the briefing agent decides how many clarifying questions it needs (0-3): wait for the questions, or for a brief that is already complete
            finalize = page.get_by_role("button", name=run.T(page, "Finalize brief"))
            page.wait_for_function(
                "(label) => !!document.querySelector('[data-testid=questions]') || [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === label && !b.disabled)",
                arg=run.T(page, "Finalize brief"),
                timeout=ai(120000),
            )
            questions_box = page.get_by_test_id("questions")
            n = questions_box.locator("input").count() if questions_box.count() else 0
            assert n <= 3, f"the briefing agent asks at most 3 clarifying questions, got {n}"
            if n:
                questions = questions_box.inner_text()
                polish = r"[ąćęłńóśźż]|\b(?:czy|jak|jaki|jaka|jakie|jakich|kto|kiedy|ile|gdzie|który|która|które)\b"  # model wording varies: any Polish letter or interrogative
                assert re.search(polish, questions, re.I), f"the clarifying questions are not Polish: {questions[:120]!r}"
                run.check(page, "/campaigns/new (questions)")
                run.shot(page, "02-brief-wizard")
                answers = {"key_message": "Obudź się powoli.", "cta": "Sprawdź Dawn Roast na northwind.example/dawn", "duration_targets": "15"}
                inputs = questions_box.locator("input")
                for i in range(inputs.count()):
                    label = inputs.nth(i).get_attribute("aria-label")
                    for key, val in answers.items():
                        if label == run.E(page, "briefField", key):
                            inputs.nth(i).fill(val)
                page.get_by_role("button", name=run.T(page, "Apply answers")).click()
            else:
                run.check(page, "/campaigns/new (complete brief)")
                run.shot(page, "02-brief-wizard")
            expect(finalize).to_be_enabled(timeout=ai(60000))
            finalize.click()
            expect(page.get_by_test_id("findings")).to_be_visible(timeout=ai(60000))
            findings = page.get_by_test_id("findings").inner_text()
            assert "claims.prohibited" in findings and "rights.unlicensed" in findings, f"the early Guardian flags are missing: {findings[:200]!r}"
            assert re.search(r"leczy\s+poranny\s+niepok|Sunrise\s+Anthem", findings, re.I), f"Guardian messages must be Polish: {findings[:160]!r}"
            run.check(page, "/campaigns/new (finalized)")
            run.shot(page, "02b-brief-finalized")
            page.get_by_role("button", name=run.T(page, "Continue to Strategy →")).click()
            page.wait_for_url(re.compile(r"/campaigns/[^/]+/strategy"))
            run.cid = page.url.split("/campaigns/")[1].split("/")[0]
            run.scratch_ids.append(run.cid)
            camp = get_json(f"{run.base}/api/campaigns/{run.cid}")["campaign"]
            assert camp["language"] == "pl", f"campaign.language must be 'pl', got {camp['language']!r}"
            run.refresh_content()

        def existing_campaign() -> None:
            camps = get_json(f"{run.base}/api/campaigns")
            if args.campaign:
                cands = [c for c in camps if c["id"] == args.campaign]
            else:  # only our own scratch campaign: never mutate somebody else's campaign on a shared deployment
                cands = sorted((c for c in camps if c["name"] == SCRATCH_NAME and c.get("language") == "pl"), key=lambda c: c.get("created_at") or "", reverse=True)
            for c in cands:
                if get_json(f"{run.base}/api/campaigns/{c['id']}/spot").get("spots"):
                    run.cid = c["id"]
                    if c["name"].startswith(SCRATCH):
                        run.scratch_ids.append(c["id"])  # a reused scratch campaign is removed at the end unless --keep-scratch
                    run.refresh_content()
                    print(f"    reusing campaign {c['id']} ({c['name']})", flush=True)
                    return
            raise Skip("no produced scratch campaign — run once without --skip-live-ai (with --keep-scratch) or pass --campaign ID")

        def need_campaign(what: str) -> str:
            if not run.cid:
                raise Skip(f"{what} needs a produced campaign (none in this run)")
            return run.cid

        def wait_job(timeout: int = 240_000) -> None:
            card = page.get_by_test_id("job-progress")
            if remote:
                with suppress(Exception):
                    card.first.wait_for(state="visible", timeout=20_000)  # the card appears once the POST returned (a cached result may finish before we look: the assertions after the wait tell)
            else:
                page.wait_for_timeout(400)
            expect(card).to_have_count(0, timeout=ai(timeout))

        def strategy() -> None:
            need_campaign("the strategy agent")
            run.go(page, f"/campaigns/{run.cid}/strategy")
            with run.api_calls(page) as log:
                page.get_by_role("button", name=run.T(page, "Generate strategy")).click()
                wait_job()
            run.assert_headers(log, "pl", "strategy generation (incl. SSE stream)")
            assert any("/api/stream/jobs/" in r.url and "lang=pl" in r.url for r in log), "the job stream (EventSource) was not opened with ?lang=pl"
            expect(page.get_by_test_id("territories")).to_be_visible(timeout=ai(60000))
            assert page.get_by_test_id("territories").locator("button", has_text=run.T(page, "Pick this territory")).count() >= 3
            page.get_by_role("button", name=run.T(page, "Pick this territory")).first.click()
            expect(page.get_by_text(run.T(page, "Territory selected")).first).to_be_visible(timeout=15000)
            run.check(page, "strategy")
            run.shot(page, "05a-strategy-territories")

        def script_and_guardian_block() -> None:
            need_campaign("the script agent")
            run.go(page, f"/campaigns/{run.cid}/script")
            # 15 s is the default duration; the plural label comes from the dictionary (Polish: "Napisz scenariusz 15 s")
            label = run.TN(page, 1, "Write {list}s script", "Write {list}s scripts", list="15")
            page.get_by_role("button", name=label).click()
            wait_job()
            expect(page.get_by_test_id("beats")).to_be_visible(timeout=ai(60000))
            spoken = " ".join(page.get_by_test_id("beats").locator("input, textarea").evaluate_all("els => els.map((e) => e.value)"))
            # the brief's mandatory line is inserted verbatim (inflection-tolerant: the model may restructure the sentence around it)
            assert re.search(r"leczy\s+poranny\s+niepok", spoken, re.I), f"the mandatory (prohibited) Polish line must be in the script: {spoken[:200]!r}"
            expect(page.get_by_test_id("workspace")).to_contain_text(run.E(page, "verdict", "block"), ignore_case=True, timeout=ai(60000))
            run.check(page, "script")
            run.shot(page, "05b-script-guardian-block")

        def guardian_playground() -> None:
            run.go(page, "/guardian")
            first = page.get_by_label(run.T(page, "line {id}", id="v1"))
            expect(first).to_have_value("Dawn Roast leczy poranny niepokój.")  # Polish seeded violations
            page.get_by_role("button", name=run.T(page, "Run Guardian")).first.click()
            expect(page.get_by_test_id("verdict")).to_have_text(run.E(page, "verdict", "block"), timeout=ai(60000))
            cov = page.get_by_test_id("seeded-coverage")
            expect(cov).to_be_visible()
            assert cov.get_by_text(run.E(page, "status", "failed")).count() == 0, "a seeded Polish violation was missed"
            findings = page.get_by_test_id("findings").inner_text()
            assert re.search(r"leczy|odchudza|detoks|cudown|najlepsz", findings, re.I), f"Polish findings expected: {findings[:200]!r}"
            page.evaluate("window.scrollTo(0, 0)")
            run.check(page, "/guardian (blocked)")
            run.shot(page, "13-guardian-report-blocked")
            page.get_by_role("button", name=run.T(page, "Auto-revise (≤3 iterations)")).click()
            expect(page.get_by_test_id("iterations")).to_be_visible(timeout=ai(90000))
            expect(page.get_by_test_id("verdict")).not_to_have_text(run.E(page, "verdict", "block"))
            revised = " ".join(page.get_by_label(re.compile("^" + re.escape(run.T(page, "line {id}", id="v")))).evaluate_all("els => els.map(e => e.value)"))
            assert not re.search(r"leczy\s+poranny\s+niepok|cudown", revised, re.I), f"auto-revise must remove the prohibited Polish claims: {revised[:200]!r}"
            page.evaluate("window.scrollTo(0, 0)")
            run.check(page, "/guardian (auto-revised)")
            run.shot(page, "14-guardian-auto-revise")

        def campaign_guardian_autorevise() -> None:
            need_campaign("the campaign Guardian tab")
            run.go(page, f"/campaigns/{run.cid}/guardian")
            expect(page.get_by_test_id("guardian-report")).to_be_visible(timeout=30000)
            run.check(page, "campaign guardian")

        def revise_script_in_campaign() -> None:
            """The campaign's own script (mandatory Polish claim + unlicensed music) is blocked: auto-revise converges to a compliant Polish script."""
            need_campaign("auto-revise")
            run.go(page, f"/campaigns/{run.cid}/script")
            expect(page.get_by_test_id("beats")).to_be_visible(timeout=30000)
            page.get_by_role("button", name=run.T(page, "Auto-revise"), exact=True).click()
            expect(page.get_by_text(run.T(page, "Auto-revise converged")).first).to_be_visible(timeout=ai(120000))
            page.wait_for_function(
                "() => { const v = [...document.querySelectorAll('[data-testid=beats] input, [data-testid=beats] textarea')].map((e) => e.value).join(' '); return v.length > 20 && !/leczy\\s+poranny\\s+niepok/i.test(v); }",
                timeout=ai(60000),
            )
            expect(page.get_by_test_id("workspace")).not_to_contain_text(run.T(page, "Guardian {verdict}", verdict=run.E(page, "verdict", "block")), timeout=ai(60000))
            spoken = " ".join(page.get_by_test_id("beats").locator("input, textarea").evaluate_all("els => els.map((e) => e.value)"))
            assert spoken and not re.search(r"leczy\s+poranny\s+niepok", spoken, re.I), f"the claim must be rewritten: {spoken[:200]!r}"
            run.check(page, "script (revised)")

        def storyboard() -> None:
            need_campaign("the storyboard")
            run.go(page, f"/campaigns/{run.cid}/storyboard")
            page.get_by_role("button", name=run.T(page, "Build shot list")).click()
            wait_job()
            expect(page.get_by_test_id("shots")).to_be_visible(timeout=ai(60000))
            page.get_by_role("button", name=run.T(page, "Generate keyframes")).click()
            wait_job()
            expect(page.get_by_test_id("shots").locator("img").first).to_be_visible(timeout=ai(60000))
            assert page.get_by_test_id("shots").locator("img").count() >= 3
            run.check(page, "storyboard")
            run.shot(page, "06-creative-workspace-storyboard")

        def voice() -> None:
            need_campaign("the voice-over")
            run.go(page, f"/campaigns/{run.cid}/audio")
            page.get_by_role("button", name=run.T(page, "Generate voice-over")).click()
            wait_job()
            expect(page.locator("audio").first).to_be_visible(timeout=ai(60000))
            expect(page.get_by_test_id("music").get_by_role("button").first).to_be_visible(timeout=30000)
            run.check(page, "audio")
            run.shot(page, "08-voice-and-music")

        def video() -> None:
            need_campaign("the render")
            run.go(page, f"/campaigns/{run.cid}/video")
            page.get_by_role("button", name=run.T(page, "Render spot")).click()
            wait_job(300_000)
            expect(page.get_by_test_id("video-player").first).to_be_visible(timeout=ai(60000))
            page.wait_for_function("() => { const v = document.querySelector('[data-testid=video-player]'); return v && v.readyState >= 2 && v.duration > 5; }", timeout=ai(60000))
            expect(page.get_by_test_id("probe")).to_contain_text("h264")
            src = page.get_by_test_id("video-player").first.get_attribute("src") or ""
            assert "lang=pl" in src, f"media URLs must carry ?lang=pl: {src}"
            for label in ("Download MP4", "Download SRT"):
                href = page.get_by_role("link", name=run.T(page, label)).first.get_attribute("href") or ""
                assert "lang=pl" in href and "download=true" in href, f"{label}: download links must carry ?lang=pl: {href}"
            page.evaluate("const v = document.querySelector('[data-testid=video-player]'); v.currentTime = 6; v.scrollIntoView({block: 'center'})")
            run.check(page, "video")
            run.shot(page, "07-creative-workspace-video")

        def formats() -> None:
            need_campaign("the format factory")
            run.go(page, f"/campaigns/{run.cid}/formats")
            page.get_by_role("button", name=run.T(page, "Generate versions")).click()
            wait_job(300_000)
            expect(page.get_by_test_id("version-tree")).to_be_visible(timeout=ai(60000))
            run.check(page, "formats")
            run.shot(page, "09-formats-and-cutdowns")

        def localization() -> None:
            need_campaign("the localization")
            run.go(page, f"/campaigns/{run.cid}/localization")
            # the master is Polish: Polish is not a target, English is (PL → EN as well as EN → PL)
            chips = page.locator("button[aria-pressed]")
            names = [x.lower() for x in chips.all_inner_texts()]
            assert not any(n.startswith("polski") for n in names), f"a Polish master cannot be localized into Polish: {names}"
            assert any(n.startswith("angielski") for n in names), f"English must be a localization target of a Polish master: {names}"
            # keep it quick: English + German (the localized voice-over and render are switched off)
            for i in range(chips.count()):
                chip = chips.nth(i)
                want = chip.inner_text().lower().startswith(("angielski", "niemiecki"))
                if (chip.get_attribute("aria-pressed") == "true") != want:
                    chip.click()
            page.get_by_label(run.T(page, "also voice + render localized MP4")).uncheck()
            page.get_by_role("button", name=re.compile("^" + re.escape(run.T(page, "Localize ({n})", n=2)))).click()
            wait_job(300_000)
            tables = page.get_by_test_id("localizations")
            expect(tables.locator("table").first).to_be_visible(timeout=ai(60000))
            text = tables.inner_text()
            assert re.search(r"[ąćęłńóśźż]", text), "the Polish source lines are missing from the localization table"
            run.check(page, "localization")
            run.shot(page, "10-localization")

        def scorecard() -> None:
            need_campaign("the scorecard")
            run.go(page, f"/campaigns/{run.cid}/scorecard")
            page.get_by_role("button", name=run.T(page, "Score latest creative")).click()
            expect(page.get_by_test_id("scorecard")).to_be_visible(timeout=ai(60000))
            run.check(page, "scorecard")
            run.shot(page, "11-preflight-scorecard")

        def provenance() -> None:
            need_campaign("the provenance check")
            run.go(page, f"/campaigns/{run.cid}/provenance")
            expect(page.get_by_test_id("verification")).to_be_visible(timeout=ai(30000))
            page.get_by_role("button", name=run.T(page, "Run tamper test")).click()
            expect(page.get_by_test_id("tamper-result")).to_contain_text(run.T(page, "tampering detected ✔"), timeout=ai(60000))
            run.check(page, "provenance")
            run.shot(page, "12-provenance-tamper-test")

        def approvals() -> None:
            need_campaign("the approvals")
            run.allowed_console = [r"status of 422.*/api/approvals/[^/]+/decide"]  # the refused (Guardian-blocked) approval is part of the journey
            run.go(page, f"/campaigns/{run.cid}/approvals")
            page.get_by_label(run.T(page, "Acting as role")).select_option("admin")  # the admin can decide for every role (demo)
            page.wait_for_timeout(600)
            refusals = 0
            api = f"{run.base}/api/campaigns/{run.cid}"

            def gate_requests(gate: str) -> list[dict]:
                return [a for a in get_json(f"{api}/approvals")["approvals"] if a["stage"] == gate]

            def decisions(gate: str) -> int:
                return sum(len(a.get("decisions", [])) for a in gate_requests(gate))

            def refused_toast() -> bool:
                return page.get_by_text(re.compile("Nie można zatwierdzić")).count() > 0

            already_approved = all(p["artifact_status"] == "approved" for p in get_json(api)["pipeline"])  # a re-run on a kept campaign (--skip-live-ai)
            for gate in ("brief", "concept", "script", "storyboard", "final"):
                label = run.E(page, "gate", gate)
                btn = page.get_by_role("row").filter(has_text=label).get_by_role("button", name=run.T(page, "Request approval"))
                if btn.count():
                    btn.first.click()
                deadline = time.monotonic() + ai(30_000) / 1000  # the request re-runs the Guardian (real Content Safety calls on a deployment)
                while not gate_requests(gate) and time.monotonic() < deadline:
                    page.wait_for_timeout(500)
                if not gate_requests(gate):
                    continue
                expect(page.get_by_test_id("approval-card").filter(has_text=label).first).to_be_visible(timeout=ai(30000))
                for _ in range(8):  # every required role approves (the admin acts for each of them)
                    if all(a["state"] == "approved" for a in gate_requests(gate)):
                        break
                    card = page.get_by_test_id("approval-card").filter(has_text=label).first
                    approve = card.get_by_role("button", name=run.T(page, "Approve"), exact=True)
                    if approve.count() == 0:
                        page.wait_for_timeout(800)  # the card is still refetching after the previous decision
                        continue
                    before = decisions(gate)
                    approve.click()
                    outcome, deadline = "", time.monotonic() + ai(30_000) / 1000
                    while not outcome and time.monotonic() < deadline:
                        outcome = "refused" if refused_toast() else ("decided" if decisions(gate) > before else "")
                        if not outcome:
                            page.wait_for_timeout(400)
                    assert outcome, f"gate {gate}: neither a decision nor a refusal after clicking Approve"
                    if outcome == "refused":  # open Guardian blocks refuse the approval — in Polish; resolve them, then retry (as the smoke test does)
                        refusals += 1
                        art = next(p["artifact_id"] for p in get_json(api)["pipeline"] if p["gate"] == gate)
                        post_json(f"{api}/guardian/run", {"artifact_id": art, "auto_revise": True})
                        page.wait_for_timeout(5200)  # let the refusal toast go away
                    else:
                        page.wait_for_timeout(1200 if remote else 800)
            states = {p["gate"]: p["artifact_status"] for p in get_json(api)["pipeline"]}
            assert all(s == "approved" for s in states.values()), f"every gate must end up approved: {states}"
            assert refusals >= 1 or already_approved, "the Guardian must refuse at least one approval while blocking findings are open (brief with the prohibited claim)"
            page.reload(wait_until="networkidle")
            run.check(page, "campaign approvals")
            run.shot(page, "16-approvals-and-audit-chain")
            expect(page.get_by_text(re.compile("łańcuch zweryfikowany"))).to_be_visible(timeout=30000)
            run.go(page, "/approvals")
            expect(page.get_by_test_id("approval-inbox").locator("section").first).to_be_visible(timeout=30000)
            run.check(page, "/approvals")
            run.shot(page, "15-approvals-inbox")
            page.get_by_label(run.T(page, "Acting as role")).select_option("creative_director")
            run.allowed_console = []

        def variants() -> None:
            need_campaign("the variants experiment")
            run.go(page, "/experiments")
            sel = page.get_by_label(run.T(page, "campaign"))
            expect(sel).to_be_visible(timeout=30000)
            sel.select_option(value=run.cid)
            name = f"{SCRATCH} test wariantów {int(time.time()) % 100000}"
            page.get_by_label(run.T(page, "Name"), exact=True).fill(name)
            page.get_by_role("button", name=re.compile("^Utwórz 12 wariantów|^Create 12 variants")).click()
            expect(page.get_by_role("heading", name=name)).to_be_visible(timeout=30000)
            expect(page.get_by_test_id("variants-table").locator("tbody tr")).to_have_count(12)
            page.get_by_role("button", name=run.T(page, "Run simulation")).click()
            expect(page.get_by_test_id("experiment-card")).to_contain_text(run.E(page, "status", "completed"), timeout=60000)
            stats = page.get_by_test_id("experiment-stats")
            expect(stats).to_contain_text(run.T(page, "Leader"), timeout=30000)
            expect(page.get_by_test_id("allocation-chart").locator("svg.recharts-surface").first).to_be_visible()
            page.evaluate(
                """() => {
                  const el = document.querySelector('[data-testid=experiment-stats]');
                  let s = el.parentElement;
                  while (s && !(s.scrollHeight > s.clientHeight && /(auto|scroll)/.test(getComputedStyle(s).overflowY))) s = s.parentElement;
                  if (s) s.scrollTop += el.getBoundingClientRect().top - s.getBoundingClientRect().top - 14;
                }"""
            )
            run.check(page, "/experiments", allow=[re.escape(name)])
            run.shot(page, "17-variants-bandit-experiment")

        def performance() -> None:
            run.go(page, "/performance")
            expect(page.get_by_test_id("perf-stats")).to_be_visible(timeout=30000)
            page.get_by_role("button", name=run.T(page, "Generate insights")).click()
            expect(page.get_by_test_id("insights").locator("li").first).to_be_visible(timeout=30000)
            run.check(page, "/performance")
            run.shot(page, "18-performance-insights")

        def planner() -> None:
            run.go(page, "/planner")
            expect(page.get_by_test_id("plan-stats")).to_be_visible(timeout=30000)
            run.check(page, "/planner")
            run.shot(page, "19-media-planner")

        def library() -> None:
            run.go(page, "/library")
            expect(page.get_by_test_id("asset-grid").locator("button").first).to_be_visible(timeout=30000)
            page.get_by_label(run.T(page, "search")).first.fill("storyboard")
            page.wait_for_timeout(800)
            page.get_by_label(run.T(page, "search")).first.fill("")
            run.check(page, "/library")
            run.shot(page, "20-asset-library")
            page.get_by_test_id("asset-grid").locator("button").first.click()
            expect(page.get_by_role("dialog")).to_be_visible()
            page.keyboard.press("Escape")

        def cost() -> None:
            run.go(page, "/cost")
            expect(page.get_by_test_id("cost-chart").locator("svg").first).to_be_visible(timeout=30000)
            run.check(page, "/cost")
            run.shot(page, "21-cost-meter")

        def roi() -> None:
            run.go(page, "/roi")
            kpis = page.get_by_test_id("roi-kpis")
            expect(kpis).to_contain_text("140%", timeout=30000)
            text = kpis.inner_text()
            assert "mln" in text and "mies." in text, f"Polish number formats expected in the KPI tiles (6,98 mln USD · 15,0 mies.): {text!r}"
            assert re.search(r"6,98\s*mln", text) and not re.search(r"\$\d", text), text
            years = page.get_by_test_id("roi-acr-years")
            assert re.fullmatch(r"R1 65 tys\. USD · R2 305 tys\. USD · R3 465 tys\. USD", years.inner_text().replace("\xa0", " ")), years.inner_text()
            expect(page.get_by_test_id("roi-cashflow").locator("svg").first).to_be_visible()
            ticks = page.get_by_test_id("roi-cashflow").locator(".recharts-cartesian-axis-tick-value")
            expect(ticks.first).to_be_visible(timeout=15000)
            expect(page.get_by_test_id("roi-tiers")).to_contain_text("Skala korporacyjna")
            assert page.get_by_test_id("roi-tiers").locator("tbody tr").count() == 5
            axis = ticks.evaluate_all("els => els.map((e) => e.textContent)")
            assert axis and all("$" not in a for a in axis) and any("USD" in a for a in axis), f"Recharts ticks must use the pl-PL formatter: {axis}"
            before = kpis.inner_text()
            page.get_by_role("tab", name=run.E(page, "roiScenario", "conservative"), exact=True).click()
            page.wait_for_function("(b) => document.querySelector('[data-testid=roi-kpis]').innerText !== b", arg=before, timeout=15000)
            page.get_by_role("tab", name=run.E(page, "roiScenario", "upside"), exact=True).click()
            expect(page.get_by_test_id("roi-acr-years")).to_contain_text("R3 973 tys. USD", timeout=15000)
            page.get_by_role("tab", name=run.E(page, "roiScenario", "base"), exact=True).click()
            expect(page.get_by_test_id("roi-acr-years")).to_contain_text("R3 465 tys. USD", timeout=15000)
            page.get_by_role("tab", name=run.T(page, "Expansion on"), exact=True).click()
            expect(page.get_by_test_id("roi-acr-years")).to_contain_text("R3 940 tys. USD", timeout=15000)
            expect(page.get_by_test_id("roi-lever")).to_contain_text("E3", timeout=15000)
            page.get_by_test_id("roi-advanced").locator("summary").click()  # the 11 advanced override labels are Polish too
            run.check(page, "/roi (expansion on)")
            run.shot(page, "22b-roi-expansion-on")
            page.get_by_role("tab", name=run.T(page, "Expansion off"), exact=True).click()
            expect(page.get_by_test_id("roi-acr-years")).to_contain_text("R3 465 tys. USD", timeout=15000)
            page.evaluate("window.scrollTo(0, 0)")
            run.check(page, "/roi")
            run.shot(page, "22-roi-acr-calculator")

        def team() -> None:
            run.go(page, "/team")
            expect(page.get_by_test_id("permission-matrix").locator("tbody tr").first).to_be_visible(timeout=30000)
            run.check(page, "/team", allow=[r"^(POST|GET|PUT|DELETE) /api/"])
            run.shot(page, "23-team-and-integrations")

        def ops() -> None:
            run.go(page, "/ops")
            expect(page.get_by_text(run.T(page, "Dependencies (/readyz)"))).to_be_visible()
            run.check(page, "/ops", allow=[r"^(POST|GET|PUT|DELETE) /api/"])
            run.shot(page, "24-ops-observability")

        def feature_map() -> None:
            run.go(page, "/features")
            expect(page.get_by_test_id("feature-map")).to_be_visible(timeout=30000)
            assert page.locator("text=CS-25").count() >= 1 and page.locator("text=wdrożono").count() >= 25, "feature statuses must be Polish"
            # diacritic-insensitive filter, ł included: "wspolpraca" finds "Współpraca, role i integracje" (CS-22), "zespol" finds "Zespół"
            flt = page.get_by_test_id("feature-filter")
            ids = lambda: page.locator("[data-testid=feature-map]").get_by_text(re.compile(r"^CS-\d\d$")).count()  # noqa: E731
            assert ids() == 25, f"25 feature ids expected, saw {ids()}"
            flt.fill("wspolpraca")
            expect(page.get_by_test_id("feature-map")).to_contain_text("Współpraca")
            assert 1 <= ids() < 25, f"the filter must narrow the list (saw {ids()} features)"
            flt.fill("")
            assert ids() == 25
            run.check(page, "/features", allow=[r"^/api/"])
            run.shot(page, "25-feature-map")

        def dashboard() -> None:
            run.go(page, "/")
            expect(page.get_by_role("heading", name="Od briefu do emisji")).to_be_visible()
            expect(page.get_by_text(run.T(page, "Open workspace →")).first).to_be_visible()
            expect(page.get_by_text(run.T(page, "Synthetic data / simulated environment"))).to_be_visible()
            expect(page.locator("section", has_text=run.T(page, "Recent activity")).locator("li").first).to_be_visible(timeout=30000)
            assert page.get_by_test_id("campaign-lang-badge").filter(has_text="PL").count() >= 1, "the Polish campaign must carry its language badge"
            run.check(page, "/")
            run.shot(page, "01-dashboard")

        def fonts() -> None:
            run.go(page, "/")
            problems = glyph_check(ctx, page)
            assert not problems, "; ".join(problems)

        def api_docs() -> None:
            run.go(page, "/docs", spa=False)
            expect(page.locator(".swagger-ui").first).to_be_visible(timeout=30000)

        if args.skip_live_ai:
            run.journey("reuse an existing produced Polish campaign", existing_campaign, page)  # always runs, even with --only: the later journeys need the campaign id
        else:
            J("brief wizard (Polish brief, questions, normalized, early Guardian flags)", brief_wizard)
            J("strategy agent (Polish territories, SSE with ?lang=)", strategy)
            J("script agent + Guardian BLOCK on the Polish prohibited claim", script_and_guardian_block)
        J("guardian playground (Polish findings, auto-revise converges)", guardian_playground)
        if not args.skip_live_ai:
            J("campaign script auto-revise (claim rewritten, music swapped)", revise_script_in_campaign)
            J("storyboard (Polish shot list, keyframes)", storyboard)
            J("voice-over + music", voice)
            J("render the Polish spot (player, probe)", video)
            J("formats and cutdowns", formats)
            J("localization PL → EN (+ DE)", localization)
            J("pre-flight scorecard", scorecard)
        J("provenance verification + tamper test", provenance)
        J("approvals inbox + audit chain", approvals)
        J("campaign Guardian tab", campaign_guardian_autorevise)
        J("variants / bandit experiment", variants)
        J("performance insights", performance)
        J("media planner", planner)
        J("asset library", library)
        J("cost meter", cost)
        J("ROI / ACR calculator (pl-PL formats, Recharts ticks, model-key labels)", roi)
        J("team & integrations", team)
        J("ops & observability", ops)
        J("feature map (diacritic-insensitive filter)", feature_map)
        J("dashboard", dashboard)
        J("fonts: Polish letters from the bundled Inter / Fraunces", fonts)
        J("API docs (swagger)", api_docs)
        browser.close()

    removed = cleanup()
    if removed:
        print(f"\nremoved {removed} scratch '{SCRATCH}' campaign(s) created by this run")
    elif args.keep_scratch and run.scratch_ids:
        print(f"\nkept scratch campaign(s) {run.scratch_ids} (--keep-scratch): reuse with --skip-live-ai, remove with a final run without --keep-scratch")
    failed = [r for r in run.results if not r[1]]
    skipped = f"; {len(run.skipped)} skipped" if run.skipped else ""
    print(f"\n{len(run.results) - len(failed) - len(run.skipped)}/{len(run.results) - len(run.skipped)} journeys passed{skipped}; {run.pages_checked} page states checked; {len(run.shots)} screenshots" + (f"; FAILED: {[r[0] for r in failed]}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
