"""Text normalisation shared by understanding, retrieval, QA and the guard.

`unicodedata.normalize("NFKD")` does NOT decompose a few Latin letters - most importantly the Polish `ł`/`Ł` (also `ø`, `đ`, `ß`, `æ`, `œ`) -
so a plain "strip combining marks" fold leaves `wściekły` as `wsciekły` and a diacritic-less `wsciekly` never matches it. `fold` maps those
letters explicitly, which makes matching work with AND without diacritics."""

from __future__ import annotations

import unicodedata

_NON_DECOMPOSING = str.maketrans(
    {
        "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ð": "d", "Ð": "D", "ß": "ss", "ẞ": "SS",
        "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ı": "i", "þ": "th", "Þ": "TH",
    }
)  # fmt: skip


def strip_diacritics(text: str) -> str:
    """Remove accents / diacritics, keeping case (ą→a, ł→l, é→e, ß→ss)."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.translate(_NON_DECOMPOSING)) if not unicodedata.combining(c))


def fold(text: str) -> str:
    """Lower-case and strip diacritics so 'beschädigt' == 'beschadigt' and 'wściekły' == 'wsciekly' (ł→l) variants still match."""
    return strip_diacritics(text).lower()


# ---------------------------------------------------------------------------------------------------------------- Polish number words ("tysiąc dwieście" -> 1200)
_PL_UNITS = {"zero": 0, "jeden": 1, "jedna": 1, "jedno": 1, "dwa": 2, "dwie": 2, "trzy": 3, "cztery": 4, "piec": 5, "szesc": 6, "siedem": 7, "osiem": 8, "dziewiec": 9}
_PL_TEENS = {"dziesiec": 10, "jedenascie": 11, "dwanascie": 12, "trzynascie": 13, "czternascie": 14, "pietnascie": 15, "szesnascie": 16, "siedemnascie": 17, "osiemnascie": 18, "dziewietnascie": 19}
_PL_TENS = {"dwadziescia": 20, "trzydziesci": 30, "czterdziesci": 40, "piecdziesiat": 50, "szescdziesiat": 60, "siedemdziesiat": 70, "osiemdziesiat": 80, "dziewiecdziesiat": 90}
_PL_HUNDREDS = {"sto": 100, "dwiescie": 200, "trzysta": 300, "czterysta": 400, "piecset": 500, "szescset": 600, "siedemset": 700, "osiemset": 800, "dziewiecset": 900}
_PL_THOUSANDS = {"tysiac": 1000, "tysiace": 1000, "tysiecy": 1000}
_PL_MILLIONS = {"milion": 1_000_000, "miliony": 1_000_000, "milionow": 1_000_000}
_PL_BELOW_THOUSAND = {**_PL_UNITS, **_PL_TEENS, **_PL_TENS, **_PL_HUNDREDS}
NUMBER_WORDS_PL = frozenset({*_PL_BELOW_THOUSAND, *_PL_THOUSANDS, *_PL_MILLIONS})  # folded forms (no diacritics)


def words_to_int_pl(words: list[str]) -> int | None:
    """Value of a sequence of folded Polish number words (`['tysiac', 'dwiescie']` -> 1200, `['dwa', 'tysiace', 'piecset']` -> 2500); None for anything else."""
    total = current = 0
    for w in words:
        if w in _PL_BELOW_THOUSAND:
            current += _PL_BELOW_THOUSAND[w]
        elif w in _PL_THOUSANDS:
            total, current = total + (current or 1) * 1000, 0
        elif w in _PL_MILLIONS:
            total, current = total + (current or 1) * 1_000_000, 0
        else:
            return None
    return total + current if words else None
