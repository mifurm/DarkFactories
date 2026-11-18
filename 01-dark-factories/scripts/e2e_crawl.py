"""Visit every UI route of a running Nightshift instance and report console errors, page errors and failed API calls.

Usage (needs Playwright; the repo's shared venv has it):
    python scripts/e2e_crawl.py --base-url http://127.0.0.1:8101 [--screens deck/assets/screens/crawl]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROUTES = [
    "/", "/simulator", "/telemetry", "/twin", "/swarm", "/maintenance", "/quality", "/planner", "/materials", "/energy", "/safety",
    "/process", "/policy", "/inbox", "/ledger", "/readiness", "/copilot", "/handover", "/rca", "/kpis", "/value", "/fleet", "/access",
    "/observability", "/deployment", "/features",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8101")
    ap.add_argument("--screens", default="")
    ap.add_argument("--wait", type=float, default=3.0)
    args = ap.parse_args()
    out = Path(args.screens) if args.screens else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    bad = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1600, "height": 900})
        for route in ROUTES:
            page = ctx.new_page()
            errors: list[str] = []
            page.on("console", lambda m, errors=errors: errors.append(f"console: {m.text[:200]}") if m.type == "error" else None)
            page.on("pageerror", lambda e, errors=errors: errors.append(f"pageerror: {str(e)[:200]}"))
            page.on(
                "response",
                lambda r, errors=errors: errors.append(f"HTTP {r.status} {r.url[:120]}") if r.status >= 400 and "/api/" in r.url else None,
            )
            t0 = time.time()
            page.goto(args.base_url + route, wait_until="domcontentloaded")
            page.wait_for_timeout(int(args.wait * 1000))
            h1 = page.locator("h1").first.inner_text() if page.locator("h1").count() else "(no h1)"
            status = "OK " if not errors else "ERR"
            bad += bool(errors)
            print(f"{status} {route:15s} {h1[:44]:44s} {time.time() - t0:4.1f}s")
            for e in errors[:4]:
                print("      ", e)
            if out:
                page.screenshot(path=str(out / ((route.strip("/").replace("/", "-") or "home") + ".png")))
            page.close()
        browser.close()
    print(f"\n{len(ROUTES) - bad}/{len(ROUTES)} routes clean")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
