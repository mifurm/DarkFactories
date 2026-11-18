"""Script normalisation: contiguous beats, word budgets, verbatim mandatories, claim-aware disclaimers (English and Polish)."""

from __future__ import annotations

import re
from typing import Any

from ..i18n import render_message
from .claims import ClaimRule, find_hits
from .text import fold, word_count
from .timing import HEADROOM, LEAD, TAIL, beat_fit, estimate_vo_seconds

WPS = 2.55  # comfortable voice-over rate, words per second
WPS_BY_LANG = {"en": WPS, "pl": 2.05}  # Polish words are longer: ~2 words/s keeps the same message inside the same beat
MAX_WPS_BY_LANG = {"en": 2.7, "pl": 2.3}  # hard ceiling used when trimming a beat to its window
STRUCTURE: dict[int, list[tuple[str, float]]] = {
    6: [("hook", 0.5), ("brand", 0.5)],
    15: [("hook", 0.22), ("product", 0.28), ("proof", 0.28), ("brand", 0.22)],
    30: [("hook", 0.16), ("product", 0.16), ("proof", 0.17), ("proof", 0.17), ("cta", 0.17), ("brand", 0.17)],
    60: [("hook", 0.10), ("product", 0.10), ("proof", 0.11), ("proof", 0.11), ("proof", 0.11), ("proof", 0.11), ("cta", 0.12), ("cta", 0.08), ("brand", 0.16)],
}
_QUOTED = re.compile(r"[“\"„«]([^”\"“»]{4,160})[”\"»]")
_TAGLINE_HINTS = ("tagline", "end on", "zakoncz", "hasl", "slogan")  # folded: "zakończ hasłem …"


def wps_for(lang: str = "en") -> float:
    return WPS_BY_LANG.get(lang, WPS)


def word_budget(duration_s: int, lang: str = "en") -> int:
    return int(duration_s * wps_for(lang) * 0.85)



def structure_for(duration_s: int) -> list[tuple[str, float, float]]:
    """[(role, t_start, t_end)] for the requested duration."""
    spec = STRUCTURE.get(duration_s) or STRUCTURE[15]
    t, out = 0.0, []
    for role, frac in spec:
        d = round(duration_s * frac, 2)
        out.append((role, round(t, 2), round(t + d, 2)))
        t += d
    out[-1] = (out[-1][0], out[-1][1], float(duration_s))
    return out


def normalize_beats(raw_beats: list[dict[str, Any]], duration_s: int) -> list[dict[str, Any]]:
    """Make beats contiguous, cover exactly 0..duration, assign ids and a words-per-second check."""
    beats = [dict(b) for b in raw_beats if b.get("visual") or b.get("vo")]
    if not beats:
        return []
    struct = structure_for(duration_s)
    n = len(beats)
    if n != len(struct):
        # re-time proportionally by the LLM's own proportions when the count differs from the template
        total = sum(max(0.5, float(b.get("t_end", 0)) - float(b.get("t_start", 0))) for b in beats) or float(duration_s)
        t = 0.0
        for b in beats:
            d = max(0.5, float(b.get("t_end", 0)) - float(b.get("t_start", 0))) / total * duration_s
            b["t_start"], b["t_end"] = round(t, 2), round(t + d, 2)
            t += d
    else:
        for b, (role, s, e) in zip(beats, struct, strict=True):
            b["t_start"], b["t_end"] = s, e
            b["role"] = b.get("role") or role
    beats[0]["t_start"] = 0.0
    beats[-1]["t_end"] = float(duration_s)
    for i, b in enumerate(beats):
        if i:
            b["t_start"] = beats[i - 1]["t_end"]
        b["id"] = f"b{i + 1}"
        b["vo"] = (b.get("vo") or "").strip()
        b["super_text"] = (b.get("super_text") or "").strip() or None
        dur = max(0.1, b["t_end"] - b["t_start"])
        b["wps"] = round(word_count(b["vo"]) / dur, 2)
        b["role"] = b.get("role") or "proof"
    return beats


def ensure_mandatories(beats: list[dict[str, Any]], mandatories: list[str], tagline: str, lang: str = "en") -> list[str]:
    """Insert brief mandatories VERBATIM (quoted lines) — the Guardian, not the writer, decides if they are allowed."""
    added: list[str] = []

    def key(s: str) -> str:
        return fold(s.replace("’", "'")).lower().rstrip(". ")

    blob = " ".join((b.get("vo") or "") + " " + (b.get("super_text") or "") for b in beats)
    for m in mandatories:
        quotes = _QUOTED.findall(m)
        if not quotes:
            continue
        line = quotes[0].strip()
        if key(line) in key(blob):
            continue
        is_tagline = any(h in fold(m).lower() for h in _TAGLINE_HINTS) or key(line) == key(tagline)
        proof = next((b for b in beats if b["role"] == "proof"), None)
        target = beats[-1] if is_tagline else (proof or beats[len(beats) // 2])
        if is_tagline:
            target["vo"] = (target["vo"].rstrip() + " " + line).strip()
        else:
            # keep the beat speakable: the mandatory line goes first, then as much of the original VO as fits the window
            window = max(1.0, target["t_end"] - target["t_start"])
            budget = int(window * wps_for(lang))
            kept: list[str] = [line]
            used = word_count(line)
            sentences = [s for s in re.split(r"(?<=[.!?])\s+", target["vo"].strip()) if s]
            tail: list[str] = []
            if lang != "en" and target is beats[-1] and tagline:  # the closing tagline is itself a brief mandatory: never trade it away for another line
                tail = [s for s in sentences if key(tagline) in key(s)]
                used += sum(word_count(s) for s in tail)
            for sent in sentences:
                if sent in tail:
                    continue
                if lang == "en":
                    fits = used + word_count(sent) <= budget
                else:  # non-English: the calibrated speaking model decides (Polish pauses and syllables), not a word count
                    fits = _fits(" ".join([*kept, sent, *tail]), window, lang)
                if fits:
                    kept.append(sent)
                    used += word_count(sent)
            target["vo"] = " ".join([*kept, *tail])
        added.append(line)
        blob += " " + line
    return added


def _fits(text: str, window: float, lang: str) -> bool:
    """Can ``text`` be spoken inside a beat window per the calibrated speaking model (see ``domain.timing``)?"""
    return not beat_fit({"vo": text, "t_start": 0.0, "t_end": window}, lang)["too_long"]


def trim_to_window(beat: dict[str, Any], max_wps: float | None = None, lang: str = "en", keep: str | list[str] | None = None) -> bool:
    """Drop trailing sentences until the beat's voice-over is speakable inside its window. Returns True if trimmed.

    English counts words (as validated); other languages use the calibrated speaking model and never drop a sentence that carries one of the
    ``keep`` lines (the tagline and the brief's verbatim mandatories)."""
    window = max(0.5, float(beat["t_end"]) - float(beat["t_start"]))
    sents = [s for s in re.split(r"(?<=[.!?])\s+", (beat.get("vo") or "").strip()) if s]
    trimmed = False
    if lang == "en":
        max_wps = max_wps or MAX_WPS_BY_LANG.get(lang, MAX_WPS_BY_LANG["en"])
        while len(sents) > 1 and sum(word_count(s) for s in sents) > window * max_wps:
            sents.pop()
            trimmed = True
    else:
        guards = [fold(k).lower().rstrip(". ") for k in ([keep] if isinstance(keep, str) else keep or []) if k]
        while len(sents) > 1 and not _fits(" ".join(sents), window, lang):
            drop = next((i for i in range(len(sents) - 1, -1, -1) if not any(g in fold(sents[i]).lower() for g in guards)), None)
            if drop is None:
                break
            sents.pop(drop)
            trimmed = True
    if trimmed:
        beat["vo"] = " ".join(sents)
    return trimmed


def rebalance_beats(beats: list[dict[str, Any]], duration_s: int, lang: str) -> bool:
    """Non-English only: when a line cannot be spoken inside its beat, move the beat boundaries so every beat gets the time its line needs
    (calibrated speaking model + lead / tail), keeping the total length. Beats that already fit are left alone. Returns True if windows changed."""
    voiced = [b for b in beats if (b.get("vo") or "").strip()]
    if lang == "en" or not voiced or not any(beat_fit(b, lang)["too_long"] for b in voiced):
        return False
    orig = [max(0.5, float(b["t_end"]) - float(b["t_start"])) for b in beats]
    headroom = HEADROOM.get(lang, HEADROOM["en"])
    need = [max(1.2, estimate_vo_seconds(b["vo"], lang) / headroom + LEAD + TAIL) if (b.get("vo") or "").strip() else w for b, w in zip(beats, orig, strict=True)]
    total = sum(need)
    wins = [n * duration_s / total for n in need] if total >= duration_s else [n + (duration_s - total) * w / sum(orig) for n, w in zip(need, orig, strict=True)]
    t = 0.0
    for i, (b, w) in enumerate(zip(beats, wins, strict=True)):
        b["t_start"] = round(t, 1)
        t += w
        b["t_end"] = float(duration_s) if i == len(beats) - 1 else round(t, 1)
    return True


def localize_timing(art: dict[str, Any], locale: str | None = None) -> dict[str, Any]:
    """A script artifact with its timing issues rendered in the viewer's language (the stored issue is code + params)."""
    issues = art.get("timing_issues")
    if not issues:
        return art
    return {**art, "timing_issues": [{**i, "message": render_message(i.get("key"), i.get("params"), i.get("message", ""), locale)} for i in issues]}


def timing_issues(beats: list[dict[str, Any]], lang: str = "en") -> list[dict[str, Any]]:
    """The 'line too long for its beat' check on the written script. Stamps ``vo_est_s`` on every voiced beat and returns one issue per
    beat whose line cannot be spoken inside its window even at the maximum speed-up. Issues carry ``key`` + ``params`` (rendered at read time)."""
    out: list[dict[str, Any]] = []
    for b in beats:
        if not (b.get("vo") or "").strip():
            b.pop("vo_est_s", None)
            continue
        fit = beat_fit(b, lang)
        b["vo_est_s"] = fit["estimated_s"]
        if fit["too_long"]:
            out.append({"beat_id": b["id"], "role": b.get("role"), "estimated_s": fit["estimated_s"], "available_s": fit["available_s"], "over_pct": fit["over_pct"], "key": "script.line_too_long",
                        "params": {"beat_role": b.get("role") or "proof", "est": fit["estimated_s"], "avail": fit["available_s"], "over": fit["over_pct"]}})
    return out


def claim_aware_legal(texts: list[str], rules: list[ClaimRule], markets: list[str], category: str, lang: str = "en") -> list[str]:
    """Disclaimers that the claims library REQUIRES for approved/substantiated claims actually used in the copy."""
    out: list[str] = []
    for t in texts:
        for h in find_hits(t, rules, markets, category, lang=lang):
            d = h.rule.required_disclaimer
            if d and d not in out and h.rule.type == "approved":
                out.append(d)
    return out
