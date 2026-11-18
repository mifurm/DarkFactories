"""Voice-over timing: fit synthesized lines into script beat windows (speed-up, overflow flags) and estimate, before any audio exists,
whether a written line is too long for its beat (Polish needs ~15–25 % more speaking time than English)."""

from __future__ import annotations

import re
from typing import Any

from .polish import tts_text
from .text import syllables, words

LEAD = 0.25
TAIL = 0.10
MAX_SPEED = 1.3

# Speaking model at speed 1.0: seconds = syllables / rate + pauses (+ the small padding the voice keeps around the line).
# English is the long-validated default voice (OpenAI tts-hd). Polish was calibrated against REAL pl-PL-ZofiaNeural synthesis
# (24 lines, brand names respelled like production, SSML with exact silences — see core/ai/azure.py): RMSE 11 %, worst under-estimate 25 %.
SYLLABLE_RATE = {"en": 4.6, "pl": 5.4}  # syllables per second of speech
SENTENCE_PAUSE = {"en": 0.3, "pl": 0.6}  # silence after a sentence end that is followed by another sentence
COMMA_PAUSE = {"en": 0.0, "pl": 0.35}  # a comma / semicolon / colon followed by more text (Polish phrasing slows the clause down)
LINE_PAD = {"en": 0.0, "pl": 0.11}  # lead (0.03) + trail (0.08) that stay in the audio after the padding is trimmed
# The estimate may exceed the room in the beat by this much of the mixer's speed-up: the rest of MAX_SPEED is headroom for estimator error.
HEADROOM = {"en": MAX_SPEED, "pl": 1.05}


def _model(table: dict[str, float], lang: str) -> float:
    return table.get(lang, table["en"])


def fit_line(t_start: float, t_end: float, natural_duration: float) -> dict[str, Any]:
    """Where a VO line starts inside its beat and what speed it needs so it ends before the beat does."""
    avail = max(0.3, (t_end - t_start) - LEAD - TAIL)
    speed = 1.0
    if natural_duration > avail:
        speed = min(MAX_SPEED, natural_duration / avail)
    dur = natural_duration / speed
    return {"start": round(t_start + LEAD, 3), "speed": round(speed, 3), "expected_duration": round(dur, 3), "overflow": dur > avail + 0.15, "avail": round(avail, 3)}


def estimate_vo_seconds(text: str, lang: str = "en") -> float:
    """Spoken length of ``text`` at normal speed: syllables / rate + the pauses the voice adds at sentence ends (not the last) and commas.

    Polish is estimated on what the voice is actually given — numbers, units, prices, dates, times, phone numbers and web addresses in words (``polish.tts_text``) —
    not on the written digits: "Cena od 39,99 zł za 340 g." is spoken as 17 words, not 6."""
    if lang == "pl":
        text = tts_text(text)
    toks = words(text)
    if not toks:
        return 0.0
    syll = sum(syllables(w, lang) for w in toks)
    stops = len(re.findall(r"[.!?…]+(?=\s+\S)", text))
    commas = len(re.findall(r"[,;:](?=\s+\S)|\s[\u2014\u2013]\s", text))  # a spaced dash is paused like a comma (English has no comma pause in its model, so it is unchanged)
    return round(syll / _model(SYLLABLE_RATE, lang) + _model(SENTENCE_PAUSE, lang) * stops + _model(COMMA_PAUSE, lang) * commas + _model(LINE_PAD, lang), 2)


def beat_fit(beat: dict[str, Any], lang: str = "en") -> dict[str, Any]:
    """The 'line too long for its beat' check on the WRITTEN line: estimated spoken seconds vs. the room in the beat even at the speed-up
    the mixer may apply (``HEADROOM``, below ``MAX_SPEED``)."""
    window = max(0.3, float(beat["t_end"]) - float(beat["t_start"]))
    avail = max(0.3, window - LEAD - TAIL)
    est = estimate_vo_seconds(beat.get("vo") or "", lang)
    limit = avail * _model(HEADROOM, lang)
    return {"estimated_s": est, "available_s": round(avail, 2), "too_long": est > limit + 0.15, "over_pct": round(max(0.0, est / limit - 1.0) * 100)}
