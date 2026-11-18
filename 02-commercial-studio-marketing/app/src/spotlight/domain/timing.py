"""Voice-over timing: fit synthesized lines into script beat windows (speed-up, overflow flags)."""

from __future__ import annotations

from typing import Any

LEAD = 0.25
TAIL = 0.10
MAX_SPEED = 1.3


def fit_line(t_start: float, t_end: float, natural_duration: float) -> dict[str, Any]:
    """Where a VO line starts inside its beat and what speed it needs so it ends before the beat does."""
    avail = max(0.3, (t_end - t_start) - LEAD - TAIL)
    speed = 1.0
    if natural_duration > avail:
        speed = min(MAX_SPEED, natural_duration / avail)
    dur = natural_duration / speed
    return {"start": round(t_start + LEAD, 3), "speed": round(speed, 3), "expected_duration": round(dur, 3), "overflow": dur > avail + 0.15, "avail": round(avail, 3)}
