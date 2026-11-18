"""Prompts for the image-to-video model.

The approved storyboard keyframe is the first frame of the clip, so the prompt only has to say what MOVES: the subject action, the camera move and
the ambient motion (steam, light, dust). Everything is English (the model is prompted in English whatever the campaign language is).
"""

from __future__ import annotations

import re
from typing import Any

from .models import NEGATIVE_PROMPT

CAMERA_PHRASES = {
    "zoom_in": "slow push-in",
    "zoom_out": "slow pull-back",
    "pan_left": "gentle truck left",
    "pan_right": "gentle truck right",
    "pan_up": "slow tilt up",
    "pan_down": "slow tilt down",
    "parallax": "subtle parallax drift",
}
STYLE_SUFFIX = "realistic cinematic commercial footage, natural motion, shallow depth of field"
PRODUCT_SAFETY = "the product packaging stays unchanged and legible, no text overlays"

# What moves when a (legacy) storyboard shot carries no motion text of its own: physically plausible, ambient, one idea per role.
DEFAULT_MOTION = {
    "hook": "soft light slowly shifts across the scene while a subtle ambient motion brings it to life",
    "product": "steam drifts upward in the backlight while the product stays perfectly still",
    "proof": "liquid and steam move gently and the light glints on the surface",
    "cta": "a subtle, natural movement of the person in warm light",
    "brand": "a calm, nearly still scene where steam rises softly and the light glows",
}
GENERIC_MOTION = "subtle natural motion and drifting light"
MAX_PROMPT_CHARS = 900
MAX_MOTION_CHARS = 300

__all__ = ["CAMERA_PHRASES", "NEGATIVE_PROMPT", "build_motion_prompt", "camera_phrase", "default_motion", "motion_text", "opening_text"]


def camera_phrase(movement: str | None) -> str:
    return CAMERA_PHRASES.get(movement or "", "slow, steady camera")


def default_motion(role: str | None) -> str:
    return DEFAULT_MOTION.get(role or "", GENERIC_MOTION)


def _sentence(text: str) -> str:
    """One clean sentence: whitespace collapsed, first letter capitalised, a single full stop at the end."""
    t = re.sub(r"\s+", " ", (text or "")).strip().rstrip(".;,: ")
    return f"{t[0].upper()}{t[1:]}." if t else ""


def opening_text(shot: dict[str, Any]) -> str:
    """The first instant of the shot (English): ``opening_en``, else the (English) description of older storyboards.

    A line that was hand-edited in another language (``opening_edited_lang``) reached the image model, but the video model only reads English: it is left out."""
    if shot.get("opening_edited_lang") not in (None, "en"):
        return ""
    return str(shot.get("opening_en") or shot.get("description_en") or shot.get("description") or "").strip()


def motion_text(shot: dict[str, Any], role: str | None = None) -> str:
    """What moves during the shot (English): the English motion prompt, else ``motion_en``, else a role default.

    ``motion.prompt`` is the text shown to people (the campaign's language); it only stands in for a missing English prompt when nobody edited it, so a hand-edit made in
    another language never reaches the English-only model."""
    m = shot.get("motion")
    prompt = (m.get("prompt_en") or (None if m.get("edited") else m.get("prompt"))) if isinstance(m, dict) else None
    text = str(prompt or shot.get("motion_en") or "").strip()
    return text[:MAX_MOTION_CHARS] if text else default_motion(role or shot.get("role"))


def build_motion_prompt(shot: dict[str, Any], bible: dict[str, Any] | None, role: str | None, movement: str | None) -> str:
    """``opening. framing. motion. Camera: …. Lighting: …. realistic cinematic commercial footage…; the product packaging stays unchanged…``."""
    role = role or shot.get("role")
    movement = movement or shot.get("movement")
    framing = str(shot.get("framing_en") or shot.get("framing") or "")
    lighting = str((bible or {}).get("lighting") or "")
    must = [_sentence(motion_text(shot, role)), _sentence(f"Camera: {camera_phrase(movement)}"), _sentence(f"Style: {STYLE_SUFFIX}"), _sentence(f"Constraints: {PRODUCT_SAFETY}")]
    nice = [_sentence(opening_text(shot)), _sentence(f"Framing: {framing}") if framing else "", _sentence(f"Lighting: {lighting}") if lighting else ""]
    parts = [nice[0], nice[1], must[0], must[1], nice[2], must[2], must[3]]
    text = " ".join(p for p in parts if p)
    for drop in (2, 1, 0):  # too long: shed the optional context (lighting, framing, opening) in that order, never the motion itself
        if len(text) <= MAX_PROMPT_CHARS:
            break
        nice[drop] = ""
        parts = [nice[0], nice[1], must[0], must[1], nice[2], must[2], must[3]]
        text = " ".join(p for p in parts if p)
    return text[:MAX_PROMPT_CHARS]
