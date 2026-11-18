"""Localization logic (CS-10): glossary / do-not-translate enforcement, back-translation similarity, market notes."""

from __future__ import annotations

import re
from typing import Any

from .text import normalize

LANGS = {"en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "pl": "Polish", "pt": "Portuguese", "nl": "Dutch"}
LANG_MARKET = {"en": "US", "de": "DE", "fr": "FR", "es": "ES", "it": "IT", "pl": "PL", "pt": "PT", "nl": "NL"}
MARKET_NOTES = {
    "de": "Sober and factual; avoid superlatives and exaggerated promises; friendly 'du' is fine for this brand.",
    "fr": "Elegant and concise; light wordplay is welcome; avoid unnecessary anglicisms.",
    "pl": "Warm but direct; keep sentences short; address the viewer informally ('ty').",
    "es": "Warm and close; neutral Castilian Spanish; avoid regionalisms.",
    "it": "Expressive and sensory; food-and-ritual language works well.",
    "pt": "Warm and polite; European Portuguese; avoid Brazilian idioms.",
    "nl": "Direct and understated; avoid hype; informal 'je/jij'.",
    "en": "Neutral US English.",
}
DISCLAIMER = "Contains caffeine. Not recommended for children or pregnant women."
DISCLAIMER_TRANSLATIONS = {
    "de": "Enthält Koffein. Für Kinder und schwangere Frauen nicht empfohlen.",
    "fr": "Contient de la caféine. Déconseillé aux enfants et aux femmes enceintes.",
    "pl": "Zawiera kofeinę. Niezalecane dla dzieci i kobiet w ciąży.",
    "es": "Contiene cafeína. No recomendado para niños ni mujeres embarazadas.",
    "it": "Contiene caffeina. Non raccomandato ai bambini e alle donne in gravidanza.",
    "pt": "Contém cafeína. Não recomendado a crianças nem a grávidas.",
    "nl": "Bevat cafeïne. Niet aanbevolen voor kinderen en zwangere vrouwen.",
}


def mask_terms(text: str, glossary: list[dict[str, Any]]) -> tuple[str, dict[str, str]]:
    """Replace do-not-translate terms with opaque placeholders so the model cannot alter them."""
    mapping: dict[str, str] = {}
    out = text
    for n, g in enumerate(t for t in glossary if not t.get("translate", True)):
        ph = f"⟦T{n + 1}⟧"
        pat = re.compile(r"(?<!\w)" + re.escape(g["term"]) + r"(?!\w)")
        if pat.search(out):
            out = pat.sub(ph, out)
            mapping[ph] = g["term"]
    return out, mapping


def restore_terms(text: str, mapping: dict[str, str]) -> str:
    for ph, term in mapping.items():
        text = text.replace(ph, term)
    return text


def missing_placeholders(text: str, mapping: dict[str, str]) -> list[str]:
    return [ph for ph in mapping if ph not in text]


def forced_translations(source: str, glossary: list[dict[str, Any]], lang: str) -> list[tuple[str, str]]:
    """(source term, required translation) pairs that apply to this source text."""
    out = []
    for g in glossary:
        if g.get("translate", True) and g.get("translations", {}).get(lang) and re.search(re.escape(g["term"]), source, re.IGNORECASE):
            out.append((g["term"], g["translations"][lang]))
    return out


def check_terms(source: str, localized: str, glossary: list[dict[str, Any]], lang: str) -> list[dict[str, str]]:
    """Glossary / do-not-translate violations of a localized line."""
    issues: list[dict[str, str]] = []
    for g in glossary:
        if not g.get("translate", True) and re.search(re.escape(g["term"]), source) and g["term"] not in localized:
            issues.append({"term": g["term"], "rule": "do_not_translate", "message": f"“{g['term']}” must stay untranslated"})
    for term, req in forced_translations(source, glossary, lang):
        if normalize(req) not in normalize(localized):
            issues.append({"term": term, "rule": "glossary", "message": f"“{term}” must be rendered as “{req}” in {LANGS.get(lang, lang)}"})
    return issues


def repair_terms(source: str, localized: str, glossary: list[dict[str, Any]], lang: str) -> str:
    """Last-resort deterministic repair: ensure forced translations / DNT terms appear (appends nothing destructive)."""
    out = localized
    for _term, req in forced_translations(source, glossary, lang):
        if normalize(req) not in normalize(out):
            out = (out.rstrip(". ") + f" — {req}") if not out.strip().endswith(req) else out
    for g in glossary:
        if not g.get("translate", True) and re.search(re.escape(g["term"]), source) and g["term"] not in out:
            out = out.rstrip() + f" ({g['term']})"
    return out


def _trigrams(s: str) -> set[str]:
    s = f"  {normalize(s)}  "
    return {s[i : i + 3] for i in range(len(s) - 2)}


def similarity(a: str, b: str) -> float:
    """Average of token Jaccard and character-trigram Dice — robust for short marketing lines (used for back-translation QA)."""
    ta, tb = set(normalize(a).split()), set(normalize(b).split())
    jac = len(ta & tb) / max(1, len(ta | tb))
    ga, gb = _trigrams(a), _trigrams(b)
    dice = 2 * len(ga & gb) / max(1, len(ga) + len(gb))
    return round((jac + dice) / 2, 3)


def status_for(sim: float, issues: list[dict[str, str]], threshold: float = 0.5) -> str:
    if issues:
        return "glossary_violation"
    return "ok" if sim >= threshold else "review"
