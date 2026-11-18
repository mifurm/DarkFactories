"""CLDR plural categories for the supported languages (English: one/other, Polish: one/few/many/other)."""

from __future__ import annotations

from typing import Any

PLURAL_FORMS: dict[str, tuple[str, ...]] = {"en": ("one", "other"), "pl": ("one", "few", "many", "other")}


def _as_int(n: Any) -> int | None:
    """The integer value of ``n`` when it is integral (1, 2.0, '3'), else None (decimals use the 'other' form)."""
    try:
        f = float(n)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return int(abs(f)) if f.is_integer() else None


def plural_category(lang: str, n: Any) -> str:
    """CLDR cardinal plural category: ``one`` / ``few`` / ``many`` / ``other``.

    Polish: 1 plik · 2–4 pliki · 5–21 plików · 22–24 pliki · 25–31 plików · 1,5 pliku (decimals -> ``other``).
    """
    i = _as_int(n)
    if lang == "pl":
        if i is None:
            return "other"
        if i == 1:
            return "one"
        if 2 <= i % 10 <= 4 and not 12 <= i % 100 <= 14:
            return "few"
        return "many"
    return "one" if i == 1 else "other"


def pick_plural(forms: dict[str, str], lang: str, n: Any) -> str:
    """Choose the right template from a ``{one, few, many, other}`` mapping (missing forms fall back to ``other``)."""
    cat = plural_category(lang, n)
    return forms.get(cat) or forms.get("other") or next(iter(forms.values()))
