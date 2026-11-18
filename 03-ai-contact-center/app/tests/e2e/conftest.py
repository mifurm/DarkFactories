"""Playwright fixtures: starts the offline app (real SPA build + API on port 8103) unless E2E_BASE_URL points at a running instance."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from e2e_env import ai
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

APP = Path(__file__).resolve().parents[2]
DIST = APP / "web" / "dist"
PORT = int(os.environ.get("E2E_PORT", "8103"))
SHOTS = os.environ.get("E2E_SHOTS_DIR")
# Polish journeys save their 1600x900 screenshots next to (never into) the English ones; E2E_PL_SHOTS_DIR overrides, E2E_NO_PL_SHOTS=1 disables
PL_SHOTS = Path(os.environ.get("E2E_PL_SHOTS_DIR") or APP.parent / "deck" / "assets" / "screens-pl")


def _up(url: str) -> bool:
    try:
        return httpx.get(f"{url}/healthz", timeout=5).status_code == 200
    except Exception:
        return False


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="session")
def base_url() -> Iterator[str]:
    explicit = os.environ.get("E2E_BASE_URL") or os.environ.get("BASE_URL")  # e.g. the live Azure URL: the same journeys run unchanged
    if explicit:
        for _ in range(15):  # a deployed app may be scaling up
            if _up(explicit.rstrip("/")):
                break
            time.sleep(2)
        else:
            raise AssertionError(f"{explicit} is not healthy")
        yield explicit.rstrip("/")
        return
    url = f"http://127.0.0.1:{PORT}"
    assert not _up(url), f"port {PORT} is already in use; stop that server or set E2E_BASE_URL"
    if not (DIST / "index.html").exists():
        subprocess.run(["npm", "run", "build"], cwd=APP / "web", check=True, capture_output=True)
    env = {**os.environ, "CONCIERGE_MODE": "offline", "STATIC_DIR": str(DIST), "PYTHONPATH": str(APP / "src")}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "concierge.main:create_app", "--factory", "--host", "127.0.0.1", "--port", str(PORT), "--no-access-log"], cwd=APP, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(120):
            if _up(url):
                break
            if proc.poll() is not None:
                raise RuntimeError("the e2e server exited during start-up")
            time.sleep(0.5)
        else:
            raise RuntimeError("the e2e server did not become healthy")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        assert not _port_open(PORT), "the e2e server must not outlive the test session"


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def context(browser: Browser) -> Iterator[BrowserContext]:
    ctx = browser.new_context(viewport={"width": 1600, "height": 900})
    yield ctx
    ctx.close()


@pytest.fixture
def page(context: BrowserContext) -> Iterator[Page]:
    p = context.new_page()
    errors: list[str] = []
    p.on("pageerror", lambda e: errors.append(f"pageerror: {e} {(getattr(e, 'stack', '') or '')[:600]}"))
    p.on("console", lambda m: errors.append(f"console.error: {m.text}") if m.type == "error" and "favicon" not in m.text else None)
    yield p
    assert not errors, errors


@pytest.fixture
def axe_page(browser: Browser) -> Iterator[Page]:
    """The app's CSP (script-src 'self') rightly blocks injected scripts; only this fixture bypasses it so that axe-core can run."""
    ctx = browser.new_context(viewport={"width": 1600, "height": 900}, bypass_csp=True)
    yield ctx.new_page()
    ctx.close()


@pytest.fixture
def shot(page: Page):
    def take(name: str) -> None:
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(SHOTS) / f"{name}.png"))

    return take


@pytest.fixture
def pl_context(browser: Browser) -> Iterator[BrowserContext]:
    """A Polish visitor: pl-PL browser locale and the Europe/Warsaw time zone (the app still honours ?lang= first)."""
    ctx = browser.new_context(viewport={"width": 1600, "height": 900}, locale="pl-PL", timezone_id="Europe/Warsaw")
    yield ctx
    ctx.close()


@pytest.fixture
def pl_page(pl_context: BrowserContext) -> Iterator[Page]:
    p = pl_context.new_page()
    errors: list[str] = []
    p.on("pageerror", lambda e: errors.append(f"pageerror: {e} {(getattr(e, 'stack', '') or '')[:600]}"))
    p.on("console", lambda m: errors.append(f"console.error: {m.text}") if m.type == "error" and "favicon" not in m.text else None)
    yield p
    assert not errors, errors


@pytest.fixture
def pl_shot(pl_page: Page):
    def take(name: str) -> None:
        if not os.environ.get("E2E_NO_PL_SHOTS"):
            PL_SHOTS.mkdir(parents=True, exist_ok=True)
            pl_page.screenshot(path=str(PL_SHOTS / f"{name}.png"))

    return take


@pytest.fixture
def api(base_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=base_url, timeout=ai(60_000) / 1000, headers={"X-Demo-Role": "admin"}) as c:  # a chat turn behind the API may take a real model's time
        yield c
