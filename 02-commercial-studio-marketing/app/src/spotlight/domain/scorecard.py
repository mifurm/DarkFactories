"""Pre-flight creative scorecard heuristics (CS-16). PREDICTIVE / SIMULATED — a ranking aid, not a measurement."""

from __future__ import annotations

import re
from typing import Any

from . import colors as col
from .text import reading_ease, sentences, word_count

HUMAN_WORDS = {"morning", "mornings", "before", "nurse", "baker", "dad", "mum", "mom", "hand", "quiet", "kitchen", "start", "hour", "slow", "slower", "you", "your", "porch", "window", "sun", "light"}
WEIGHTS = {"hook": 0.25, "brand": 0.20, "clarity": 0.15, "cta": 0.15, "accessibility": 0.10, "compliance": 0.15}


def _clip(x: float) -> int:
    return int(max(0, min(100, round(x))))


def hook_score(first_text: str, first_visual: str = "") -> tuple[int, list[str]]:
    words = re.findall(r"\w+", first_text.lower())
    tips: list[str] = []
    s = 40.0
    if 3 <= len(words) <= 10:
        s += 20
    else:
        tips.append("Keep the first line to 3–10 words so it lands inside 3 seconds.")
    hits = sum(1 for w in words if w in HUMAN_WORDS)
    s += min(25, hits * 9)
    if first_text.strip().endswith("?"):
        s += 8
    if first_visual and re.search(r"\b(hand|face|smile|person|baker|nurse|dad|kitchen|window)\b", first_visual.lower()):
        s += 12
    else:
        tips.append("Open on a human moment (hands, faces, a lived-in room) rather than the product.")
    return _clip(s), tips


def brand_score(vo_texts: list[str], supers: list[str], has_logo: bool, product_in_first_beats: bool, brand_name: str, tagline: str) -> tuple[int, list[str]]:
    blob = " ".join(vo_texts + supers).lower()
    s, tips = 30.0, []
    if brand_name.lower().split()[0] in blob or "dawn roast" in blob:
        s += 25
    else:
        tips.append("Mention the product name in the first 5 seconds.")
    if tagline.lower().rstrip(".") in blob:
        s += 20
    else:
        tips.append(f"End on the tagline “{tagline}”.")
    s += 15 if has_logo else 0
    s += 10 if product_in_first_beats else 0
    return _clip(s), tips


def clarity_score(vo_texts: list[str], duration_s: float) -> tuple[int, list[str]]:
    text = " ".join(vo_texts)
    wps = word_count(text) / max(duration_s, 1)
    ease = reading_ease(text)
    s = 55.0 + (ease - 60) * 0.4
    tips = []
    if wps > 2.8:
        s -= (wps - 2.8) * 25
        tips.append(f"Voice-over is dense ({wps:.1f} words/s) — trim a line.")
    if max((word_count(x) for x in sentences(text)), default=0) > 16:
        s -= 10
        tips.append("Split long sentences.")
    return _clip(s), tips


def cta_score(cta: str | None, url: str | None, vo_texts: list[str], last_beat_text: str) -> tuple[int, list[str]]:
    s, tips = 20.0, []
    if cta:
        s += 40
    else:
        tips.append("Add an explicit call to action on the end card.")
    if url:
        s += 20
    else:
        tips.append("Add a URL or store cue under the CTA.")
    if re.search(r"\b(find|try|get|buy|shop|visit|order|taste|pour|discover)\b", (cta or "").lower() + " " + last_beat_text.lower()):
        s += 20
    return _clip(s), tips


def accessibility_score(captions: bool, contrast_pairs: list[tuple[str, str]], badge: bool) -> tuple[int, list[str]]:
    s, tips = 30.0, []
    if captions:
        s += 40
    else:
        tips.append("Add captions: most social video is watched with sound off.")
    if contrast_pairs:
        worst = min(col.contrast_ratio(a, b) for a, b in contrast_pairs)
        s += 20 if worst >= 4.5 else 5
        if worst < 4.5:
            tips.append(f"Increase text contrast (worst {worst}:1 < 4.5:1).")
    s += 10 if badge else 0
    return _clip(s), tips


def overall(parts: dict[str, int]) -> int:
    return _clip(sum(parts[k] * w for k, w in WEIGHTS.items()))


def variant_score(attrs: dict[str, str], seed_noise: float = 0.0) -> dict[str, Any]:
    """Cheap heuristic for the 12-variant pre-flight ranking (copy attributes only)."""
    hook = {"Human moment first": 88, "Sensory close-up": 78, "Question hook": 72, "Product first": 58}.get(attrs.get("hook", ""), 65)
    cta = {"Find it near you": 80, "Try it today": 76, "Learn more": 55}.get(attrs.get("cta", ""), 65)
    vis = {"Macro pour": 82, "Warm kitchen": 80, "Street at dawn": 72}.get(attrs.get("visual", ""), 70)
    seg = {"Early-shift workers": 78, "Commuters": 74, "Remote workers": 68}.get(attrs.get("segment", ""), 74)
    score = 0.38 * hook + 0.22 * cta + 0.25 * vis + 0.15 * seg + seed_noise
    return {"predicted_score": _clip(score), "parts": {"hook": hook, "cta": cta, "visual": vis, "segment": seg}}
