"""Script normalisation: contiguous beats, word budgets, verbatim mandatories, claim-aware disclaimers."""

from __future__ import annotations

import re
from typing import Any

from .claims import ClaimRule, find_hits
from .text import word_count

WPS = 2.55  # comfortable voice-over rate, words per second
STRUCTURE: dict[int, list[tuple[str, float]]] = {
    6: [("hook", 0.5), ("brand", 0.5)],
    15: [("hook", 0.22), ("product", 0.28), ("proof", 0.28), ("brand", 0.22)],
    30: [("hook", 0.16), ("product", 0.16), ("proof", 0.17), ("proof", 0.17), ("cta", 0.17), ("brand", 0.17)],
    60: [("hook", 0.10), ("product", 0.10), ("proof", 0.11), ("proof", 0.11), ("proof", 0.11), ("proof", 0.11), ("cta", 0.12), ("cta", 0.08), ("brand", 0.16)],
}


def word_budget(duration_s: int) -> int:
    return int(duration_s * WPS * 0.85)


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


def ensure_mandatories(beats: list[dict[str, Any]], mandatories: list[str], tagline: str) -> list[str]:
    """Insert brief mandatories VERBATIM (quoted lines) — the Guardian, not the writer, decides if they are allowed."""
    added: list[str] = []
    blob = " ".join((b.get("vo") or "") + " " + (b.get("super_text") or "") for b in beats).lower()
    for m in mandatories:
        quotes = re.findall(r"[“\"]([^”\"]{4,160})[”\"]", m)
        if not quotes:
            continue
        line = quotes[0].strip()
        if line.lower().rstrip(".") in blob.replace("’", "'"):
            continue
        is_tagline = "tagline" in m.lower() or "end on" in m.lower() or line.lower().rstrip(".") == tagline.lower().rstrip(".")
        proof = next((b for b in beats if b["role"] == "proof"), None)
        target = beats[-1] if is_tagline else (proof or beats[len(beats) // 2])
        if is_tagline:
            target["vo"] = (target["vo"].rstrip() + " " + line).strip()
        else:
            # keep the beat speakable: the mandatory line goes first, then as much of the original VO as fits the window
            window = max(1.0, target["t_end"] - target["t_start"])
            budget = int(window * WPS)
            kept: list[str] = [line]
            used = word_count(line)
            for sent in re.split(r"(?<=[.!?])\s+", target["vo"].strip()):
                if sent and used + word_count(sent) <= budget:
                    kept.append(sent)
                    used += word_count(sent)
            target["vo"] = " ".join(kept)
        added.append(line)
        blob += " " + line.lower()
    return added


def trim_to_window(beat: dict[str, Any], max_wps: float = 2.7) -> bool:
    """Drop trailing sentences until the beat's voice-over is speakable inside its window. Returns True if trimmed."""
    window = max(0.5, float(beat["t_end"]) - float(beat["t_start"]))
    sents = [s for s in re.split(r"(?<=[.!?])\s+", (beat.get("vo") or "").strip()) if s]
    trimmed = False
    while len(sents) > 1 and sum(word_count(s) for s in sents) > window * max_wps:
        sents.pop()
        trimmed = True
    if trimmed:
        beat["vo"] = " ".join(sents)
    return trimmed


def claim_aware_legal(texts: list[str], rules: list[ClaimRule], markets: list[str], category: str) -> list[str]:
    """Disclaimers that the claims library REQUIRES for approved/substantiated claims actually used in the copy."""
    out: list[str] = []
    for t in texts:
        for h in find_hits(t, rules, markets, category):
            d = h.rule.required_disclaimer
            if d and d not in out and h.rule.type == "approved":
                out.append(d)
    return out
