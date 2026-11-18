"""How a cinematic render's motion report is shown: the reason a shot fell back to its still, in the viewer's language.

The stored report keeps the language-neutral ``reason`` code (one of ``models.FALLBACK_REASONS``); ``reason_text`` is added when the report is served."""

from __future__ import annotations

from typing import Any

from ..i18n import DEFAULT, has, t


def reason_text(reason: str | None, locale: str | None = None) -> str:
    key = f"motion.reason.{reason}"
    return t(key if has(key, DEFAULT) else "motion.reason.internal", locale)


def localize_motion(motion: dict[str, Any] | None, locale: str | None = None) -> dict[str, Any] | None:
    """``render.motion`` as served: every ``shots_fallback`` row gets ``reason_text`` (``locale`` defaults to the request's language). A report without fallbacks is returned as it is."""
    if not motion or not motion.get("shots_fallback"):
        return motion
    return {**motion, "shots_fallback": [{**f, "reason_text": reason_text(f.get("reason"), locale)} for f in motion["shots_fallback"]]}
