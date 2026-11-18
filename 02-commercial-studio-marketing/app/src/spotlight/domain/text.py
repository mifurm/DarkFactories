"""Text helpers shared by the guardian, claims, localization and scorecard logic."""

from __future__ import annotations

import re
import unicodedata

_WORD = re.compile(r"[\w'’-]+", re.UNICODE)
_SENT = re.compile(r"(?<=[.!?…])\s+")


def normalize(text: str) -> str:
    """Lower-case, strip accents' effect on punctuation/whitespace; keeps letters/digits for comparisons."""
    t = unicodedata.normalize("NFKC", text).lower()
    t = re.sub(r"[^\w\s%$€£-]", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text.strip()) if s.strip()]


def word_count(text: str) -> int:
    return len(words(text))


def token_set(text: str) -> set[str]:
    return set(normalize(text).split())


def jaccard(a: str, b: str) -> float:
    sa, sb = token_set(a), token_set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / max(1, len(sa | sb))


def contains_phrase(haystack: str, phrase: str) -> bool:
    """Case/punctuation-insensitive whole-phrase containment, with token-overlap fallback for long phrases."""
    h, p = normalize(haystack), normalize(phrase)
    if not p:
        return True
    if f" {p} " in f" {h} ":
        return True
    pt = p.split()
    if len(pt) >= 4:
        ht = set(h.split())
        return sum(1 for t in pt if t in ht) / len(pt) >= 0.85
    return False


def reading_ease(text: str) -> float:
    """Flesch-style reading ease (English heuristic); higher is easier. Clamped 0..100."""
    w = words(text)
    s = max(1, len(sentences(text)))
    if not w:
        return 100.0
    syll = sum(max(1, len(re.findall(r"[aeiouyäöüéèêàáíóúąęåæø]+", x.lower()))) for x in w)
    score = 206.835 - 1.015 * (len(w) / s) - 84.6 * (syll / len(w))
    return max(0.0, min(100.0, score))


def replace_ci(text: str, find: str, repl: str) -> str:
    return re.sub(re.escape(find), repl, text, flags=re.IGNORECASE)
