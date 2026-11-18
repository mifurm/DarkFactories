"""Flows shared by the English and the Polish journeys: the confirmation cards of a real model and the demo refund that can be issued only once."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable

import httpx
import pytest
from e2e_env import LIVE, ai, poll
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

RESET_BACKOFFICE = os.environ.get("E2E_RESET_BACKOFFICE") == "1"


def refunded(api: httpx.Client, customer: str) -> bool:
    """The customer already has a refund on the timeline: the one-time demo order was used."""
    timeline = api.get(f"/api/crm/customers/{customer}/360").json()["timeline"]
    return any(e["type"] == "refund" for e in timeline)


def prepare_demo_refund(api: httpx.Client, base_url: str, customer: str, *, reset_when_local: bool) -> None:
    """A golden journey refunds a demo order, which can be done once. An offline server the suite started starts from the seeded back office (reset when asked to).
    A deployed app is shared with other people and is never reset by the suite - only with E2E_RESET_BACKOFFICE=1 - so a used demo order skips the journey with the reason."""
    if RESET_BACKOFFICE or (reset_when_local and not LIVE):
        assert api.post("/api/admin/reset-backoffice").status_code < 300, "reset-backoffice failed"
    elif LIVE and refunded(api, customer):
        pytest.skip(f"the demo order of {customer} is already refunded on {base_url}; reset the back office first (E2E_RESET_BACKOFFICE=1 does it) to run this journey again")


def confirm_cards_until(
    page: Page,
    *,
    card_name: str,
    confirm_name: str,
    typing_label: str,
    done: Callable[[], bool],
    nudge: Callable[[], None],
    on_card: Callable[[str], None] | None = None,
    budget_ms: int = 240_000,
) -> list[str]:
    """Confirm every confirmation card the assistant shows until `done()` says the refund exists; return the card texts. `done` asks the API, every few seconds only
    (the `issue_refund` chip of the chat is already shown on the PROPOSED plan, so it is no proof). The offline stub proposes return, pickup and refund in ONE card;
    a real model proposes them one card at a time (and may ask a question in between: after a silent stretch of one AI turn the customer is nudged, at most twice).
    A card is confirmed once - while its tool runs the same card may still be on screen."""
    card = page.get_by_role("group", name=card_name)
    typing = page.get_by_label(typing_label)
    texts: list[str] = []
    last_clicked = ""
    nudges = 0
    last_check = 0.0
    quiet_since = time.monotonic()
    end = quiet_since + ai(budget_ms) / 1000
    while time.monotonic() < end:
        if time.monotonic() - last_check > poll(2.5):
            last_check = time.monotonic()
            if done():
                return texts
        if card.count():
            try:
                text = card.first.inner_text(timeout=2000)
            except Exception:  # the card went away between the check and the read
                continue
            if text != last_clicked:
                texts.append(text)
                if on_card:
                    on_card(text)
                card.first.get_by_role("button", name=confirm_name).click()
                last_clicked = text
                quiet_since = time.monotonic()
                last_check = 0.0
        elif nudges < 2 and time.monotonic() - quiet_since > ai(30_000) / 1000 and not typing.count():
            nudge()
            nudges += 1
            quiet_since = time.monotonic()
        page.wait_for_timeout(400)
    raise AssertionError(f"the refund was not issued after {len(texts)} confirmation card(s): {texts}")


def wait_quiet(page: Page, timeout_ms: int, settle_ms: int = 600) -> None:
    """Wait until no spinner / busy button is left on the page (an action with a model behind it has finished), then let the result render.
    A spinner that never ends does not abort the test: the page is scanned as it is."""
    try:
        page.wait_for_function("() => document.querySelectorAll('.animate-spin, [aria-busy=true]').length === 0", timeout=timeout_ms, polling=300)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(settle_ms)


def voice_ask(page: Page, question: str, answer: re.Pattern[str], *, placeholder: re.Pattern[str], greeting: re.Pattern[str], listening: str) -> None:
    """Ask a question on the call page's typed test path and wait for the caption that answers it.
    A typed message that reaches the live model while it is still speaking the opening disclosure is dropped, so wait for the disclosure caption and for
    the 'listening' state first; if no answer caption follows (the model phrases and paces it - up to ~90 s), ask once more. The caption is matched by pattern."""
    log = page.locator("[role=log]")
    expect(log.get_by_text(greeting).first).to_be_visible(timeout=ai(20000))
    box = page.get_by_placeholder(placeholder)
    for attempt, wait_ms in enumerate((ai(25000), ai(30000))):
        expect(page.get_by_text(listening, exact=True).first).to_be_visible(timeout=ai(20000))
        box.fill(question)
        box.press("Enter")
        try:
            expect(log.get_by_text(answer).first).to_be_visible(timeout=wait_ms)
            return
        except AssertionError:
            if attempt:
                raise
