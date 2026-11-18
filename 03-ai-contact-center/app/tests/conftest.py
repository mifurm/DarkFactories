"""Shared fixtures: fully offline services (in-memory repo, stub LLM, rules guard) with seeded back-office and KB."""

from __future__ import annotations

import pytest

from concierge.core.config import Settings
from concierge.services import Services, build_services


@pytest.fixture
async def svc() -> Services:
    s = build_services(Settings(mode="offline"))
    await s.start()
    await s.configs.load()
    await s.backoffice.seed()
    await s.kb.seed()
    yield s
    await s.stop()


def otp_of(conv) -> str:
    return next(o["code"] for o in reversed(conv.outbox) if o["kind"] == "otp")


async def say(svc: Services, conv_id: str, text: str) -> dict:
    return await svc.orchestrator.handle_message(conv_id, text)
