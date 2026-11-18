"""Localization logic (CS-10): glossary / do-not-translate enforcement, back-translation similarity, market notes."""

from __future__ import annotations

import re
from typing import Any

from .text import fold, normalize

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


def source_form(g: dict[str, Any], lang: str) -> str | None:
    """A glossary term as written in ``lang``: ``term`` is the English form, ``translations[lang]`` the others."""
    return g["term"] if lang == "en" else (g.get("translations") or {}).get(lang)


def forced_translations(source: str, glossary: list[dict[str, Any]], lang: str, source_lang: str = "en") -> list[tuple[str, str]]:
    """(source-language term, required translation) pairs that apply to this source text (any direction: PL->EN, EN->PL, PL->DE …)."""
    out = []
    for g in glossary:
        if not g.get("translate", True):
            continue
        src, tgt = source_form(g, source_lang), source_form(g, lang)
        if src and tgt and src != tgt and re.search(re.escape(fold(src)), fold(source), re.IGNORECASE):
            out.append((src, tgt))
    return out


def check_terms(source: str, localized: str, glossary: list[dict[str, Any]], lang: str, source_lang: str = "en") -> list[dict[str, Any]]:
    """Glossary / do-not-translate violations of a localized line. Issues carry ``key`` + ``params`` (rendered in the viewer's language at read time)."""
    issues: list[dict[str, Any]] = []
    for g in glossary:
        if not g.get("translate", True) and re.search(re.escape(g["term"]), source) and g["term"] not in localized:
            issues.append({"term": g["term"], "rule": "do_not_translate", "message": f"“{g['term']}” must stay untranslated", "key": "loc.issue.dnt", "params": {"term": g["term"]}})
    for term, req in forced_translations(source, glossary, lang, source_lang):
        if normalize(req) not in normalize(localized):
            issues.append({"term": term, "rule": "glossary", "message": f"“{term}” must be rendered as “{req}” in {LANGS.get(lang, lang)}", "key": "loc.issue.glossary", "params": {"term": term, "required": req, "language": lang}})
    return issues


def repair_terms(source: str, localized: str, glossary: list[dict[str, Any]], lang: str, source_lang: str = "en") -> str:
    """Last-resort deterministic repair: ensure forced translations / DNT terms appear (appends nothing destructive)."""
    out = localized
    for _term, req in forced_translations(source, glossary, lang, source_lang):
        if normalize(req) not in normalize(out):
            out = (out.rstrip(". ") + f" — {req}") if not out.strip().endswith(req) else out
    for g in glossary:
        if not g.get("translate", True) and re.search(re.escape(g["term"]), source) and g["term"] not in out:
            out = out.rstrip() + f" ({g['term']})"
    return out


SOURCE_WORD = {"en": "Source", "pl": "Źródło", "de": "Quelle", "fr": "Source", "es": "Fuente", "it": "Fonte", "pt": "Fonte", "nl": "Bron"}
DISCLAIMER_BY_LANG = {"en": DISCLAIMER, **DISCLAIMER_TRANSLATIONS}
_SOURCE_LINE = re.compile(r"^\s*(?:" + "|".join(sorted({re.escape(w) for w in SOURCE_WORD.values()})) + r")\s*:\s*(.+?)\s*$", re.IGNORECASE)


def translate_legal(line: str, source_lang: str, target_lang: str) -> str:
    """Legal supers are fixed wording, not creative copy: the caffeine disclaimer and "Source: <url>" lines map to the target language."""
    stripped = line.strip()
    if fold(stripped).lower() == fold(DISCLAIMER_BY_LANG.get(source_lang, DISCLAIMER)).lower():
        return DISCLAIMER_BY_LANG.get(target_lang, line)
    m = _SOURCE_LINE.match(stripped)
    if m:
        return f"{SOURCE_WORD.get(target_lang, 'Source')}: {m.group(1)}"
    return line


def _trigrams(s: str) -> set[str]:
    s = f"  {normalize(s)}  "
    return {s[i : i + 3] for i in range(len(s) - 2)}


def _tokens(text: str, lang: str) -> set[str]:
    toks = normalize(text).split()
    return {t[:5] for t in toks} if lang == "pl" else set(toks)  # Polish inflects: 5-letter stems make "początek" / "początku" match


def similarity(a: str, b: str, lang: str = "en") -> float:
    """Average of token Jaccard and character-trigram Dice — robust for short marketing lines (used for back-translation QA).
    ``lang`` is the language of both strings (Polish tokens are compared by stem)."""
    ta, tb = _tokens(a, lang), _tokens(b, lang)
    jac = len(ta & tb) / max(1, len(ta | tb))
    ga, gb = _trigrams(a), _trigrams(b)
    dice = 2 * len(ga & gb) / max(1, len(ga) + len(gb))
    return round((jac + dice) / 2, 3)


def status_for(sim: float, issues: list[dict[str, str]], threshold: float = 0.5) -> str:
    if issues:
        return "glossary_violation"
    return "ok" if sim >= threshold else "review"
