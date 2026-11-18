"""The environment knobs of the E2E suites, in one place.

LIVE            True when E2E_BASE_URL / BASE_URL points the journeys at a running (deployed) app instead of the offline server the suite starts itself.
E2E_AI_TIMEOUT_MS   ONE knob for every wait that depends on a model: how long one AI turn may take. Default 30 s offline (deterministic stub), 120 s when LIVE (real models,
                    voice streams audio for ~40-50 s); set it explicitly to override either.
ai(ms)          a wait written for the offline stub (`ai(30000)`), scaled by the knob: 30 s offline, 120 s live, 60 s with E2E_AI_TIMEOUT_MS=60000.
"""

from __future__ import annotations

import os

LIVE = bool(os.environ.get("E2E_BASE_URL") or os.environ.get("BASE_URL"))
AI_TIMEOUT_MS = int(os.environ.get("E2E_AI_TIMEOUT_MS") or (120_000 if LIVE else 30_000))
_OFFLINE_TURN_MS = 30_000


def ai(offline_ms: int) -> int:
    """`offline_ms` as written for the stub, scaled to the configured AI turn time (unchanged offline)."""
    return int(offline_ms * AI_TIMEOUT_MS / _OFFLINE_TURN_MS)


def poll(seconds: float) -> float:
    """A polling interval written for the local server, relaxed on a deployed app (it rate-limits per client IP)."""
    return seconds * (3 if LIVE else 1)
