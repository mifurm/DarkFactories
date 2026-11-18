"""Pre-flight creative scorecard heuristics (CS-16). PREDICTIVE / SIMULATED — a ranking aid, not a measurement.

Every heuristic knows English and Polish (Polish: folded, inflection-aware word lists). Advice is returned as ``tips`` = ``[{"key", "params"}]``
(catalog keys ``score.tip.*``) and rendered in the viewer's language at read time — see :func:`render_tips`."""

from __future__ import annotations

import re
from typing import Any

from ..i18n import t as tr
from . import colors as col
from .text import fold, reading_ease, sentences, word_count

HUMAN_WORDS = {"morning", "mornings", "before", "nurse", "baker", "dad", "mum", "mom", "hand", "quiet", "kitchen", "start", "hour", "slow", "slower", "you", "your", "porch", "window", "sun", "light"}
HUMAN_WORDS_PL = {
    "poranek", "poranki", "poranku", "poranka", "poranna", "porannej", "przed", "pielegniarka", "pielegniarki", "piekarz", "piekarka", "tata", "tato", "mama", "reka", "dlon", "cichy", "cicha", "cichych", "cisza",
    "kuchnia", "kuchni", "start", "poczatek", "godzina", "godzine", "wolno", "wolniej", "wolniejszy", "wolniejszym", "ty", "twoj", "twoja", "twoje", "ciebie", "tobie", "ci", "okno", "slonce", "swiatlo", "dzien", "dom", "filizanka",
}
WEIGHTS = {"hook": 0.25, "brand": 0.20, "clarity": 0.15, "cta": 0.15, "accessibility": 0.10, "compliance": 0.15}
Tip = dict[str, Any]


def tip(key: str, **params: Any) -> Tip:
    return {"key": f"score.tip.{key}", "params": params}


def render_tips(tips: list[Tip], locale: str | None = None) -> list[str]:
    """The advice in ``locale`` (de-duplicated, order kept)."""
    return list(dict.fromkeys(tr(t["key"], locale, **t.get("params", {})) for t in tips))


def _clip(x: float) -> int:
    return int(max(0, min(100, round(x))))


def hook_score(first_text: str, first_visual: str = "", lang: str = "en") -> tuple[int, list[Tip]]:
    pl = lang == "pl"
    words = re.findall(r"\w+", (fold(first_text) if pl else first_text).lower())
    tips: list[Tip] = []
    s = 40.0
    if 3 <= len(words) <= (11 if pl else 10):  # Polish words carry more per word: a slightly higher ceiling
        s += 20
    else:
        tips.append(tip("hook_length"))
    hits = sum(1 for w in words if w in (HUMAN_WORDS_PL if pl else HUMAN_WORDS))
    s += min(25, hits * 9)
    if first_text.strip().endswith("?"):
        s += 8
    visual = first_visual.lower()
    human_visual = re.search(r"\b(hand|face|smile|person|baker|nurse|dad|kitchen|window)\b", visual) or (pl and re.search(r"\b(dlon\w*|rek[aię]\w*|twarz\w*|usmiech\w*|osob\w*|piekar\w+|pielegniar\w+|tata|tat[aęy]|kuchni\w*|okn\w+)\b", fold(visual)))
    if first_visual and human_visual:
        s += 12
    else:
        tips.append(tip("hook_human"))
    return _clip(s), tips


def brand_score(vo_texts: list[str], supers: list[str], has_logo: bool, product_in_first_beats: bool, brand_name: str, tagline: str) -> tuple[int, list[Tip]]:
    blob = fold(" ".join(vo_texts + supers)).lower()
    s, tips = 30.0, []
    if fold(brand_name).lower().split()[0] in blob or "dawn roast" in blob:
        s += 25
    else:
        tips.append(tip("brand_name"))
    if fold(tagline).lower().rstrip(".") in blob:
        s += 20
    else:
        tips.append(tip("tagline", tagline=tagline))
    s += 15 if has_logo else 0
    s += 10 if product_in_first_beats else 0
    return _clip(s), tips


def clarity_score(vo_texts: list[str], duration_s: float, lang: str = "en") -> tuple[int, list[Tip]]:
    pl = lang == "pl"
    text = " ".join(vo_texts)
    wps = word_count(text) / max(duration_s, 1)
    ease = reading_ease(text, lang)
    s = 55.0 + (ease - 60) * 0.4
    tips: list[Tip] = []
    dense, long_sentence = (2.45, 14) if pl else (2.8, 16)  # Polish is spoken at ~2 words/s: the same message needs fewer words
    if wps > dense:
        s -= (wps - dense) * 25
        tips.append(tip("dense_vo", wps=round(wps, 1)))
    if max((word_count(x) for x in sentences(text)), default=0) > long_sentence:
        s -= 10
        tips.append(tip("long_sentences"))
    return _clip(s), tips


def cta_score(cta: str | None, url: str | None, vo_texts: list[str], last_beat_text: str, lang: str = "en") -> tuple[int, list[Tip]]:
    s, tips = 20.0, []
    if cta:
        s += 40
    else:
        tips.append(tip("cta_missing"))
    if url:
        s += 20
    else:
        tips.append(tip("cta_url"))
    blob = (cta or "") + " " + last_beat_text
    verbs = re.search(r"\b(find|try|get|buy|shop|visit|order|taste|pour|discover)\b", blob.lower()) or re.search(
        r"\b(znajdz|sprobuj|wyprobuj|kup|kupuj|zamow|odwiedz|odkryj|sprawdz|zasmakuj|nalej|poczuj|zacznij|wpadnij|szukaj)\b", fold(blob).lower()
    )
    if verbs:
        s += 20
    return _clip(s), tips


def accessibility_score(captions: bool, contrast_pairs: list[tuple[str, str]], badge: bool) -> tuple[int, list[Tip]]:
    s, tips = 30.0, []
    if captions:
        s += 40
    else:
        tips.append(tip("captions"))
    if contrast_pairs:
        worst = min(col.contrast_ratio(a, b) for a, b in contrast_pairs)
        s += 20 if worst >= 4.5 else 5
        if worst < 4.5:
            tips.append(tip("contrast", worst=worst))
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
