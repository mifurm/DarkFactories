"""Claims & compliance rule engine (CS-02): approved / prohibited / needs-substantiation claims per market & category."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from .pl_morph import clause_closed, clause_start, clitic_before, is_negated, lookup_form, pick_keyed
from .text import MatchView, contains_phrase, fold, match_views, squeeze

REGIONS: dict[str, set[str]] = {
    "EU": {"DE", "FR", "PL", "ES", "IT", "PT", "NL", "AT", "BE", "IE", "SE", "DK", "FI", "CZ", "GR", "HU", "RO", "BG", "SK", "SI", "HR", "LT", "LV", "EE", "LU", "MT", "CY"},
    "EEA": {"DE", "FR", "PL", "ES", "IT", "PT", "NL", "NO", "IS", "LI"},
    "UK": {"GB", "UK"},
    "NA": {"US", "CA", "MX"},
}


def market_matches(rule_markets: list[str], subject_markets: list[str]) -> bool:
    """True when the rule applies to at least one subject market ('*'/'WW' = everywhere; 'EU' covers member states)."""
    rm = {m.upper() for m in rule_markets or ["*"]}
    if "*" in rm or "WW" in rm:
        return True
    sm = {m.upper() for m in subject_markets or ["US"]}
    for r in list(rm):
        rm |= REGIONS.get(r, set())
    return bool(rm & sm) or any(s in REGIONS and REGIONS[s] & rm for s in sm)


def category_matches(rule_categories: list[str], category: str) -> bool:
    rc = {c.lower() for c in rule_categories or ["*"]}
    return "*" in rc or category.lower() in rc


class ClaimRule(BaseModel):
    id: str
    brand_id: str = "northwind"
    text: str
    type: Literal["approved", "prohibited", "needs_substantiation"]
    markets: list[str] = Field(default_factory=lambda: ["*"])
    categories: list[str] = Field(default_factory=lambda: ["*"])
    patterns: list[str] = Field(default_factory=list)
    required_disclaimer: str | None = None
    substantiation_url: str | None = None
    alternative: str | None = None
    severity: Literal["block", "warn"] = "block"
    notes: str = ""
    rule_pack: str | None = None
    # Language of the rule's wording and patterns: "en" (also the default for legacy rows), "pl", or "*" (language-neutral).
    lang: str = "en"
    # The rule's description in other languages ({lang: text}) so findings can be shown in the viewer's language.
    text_i18n: dict[str, str] = Field(default_factory=dict)
    # id of the rule this one is the <lang> counterpart of: for text in <lang> the Guardian then skips that other-language rule.
    concept: str | None = None
    # Agreement-correct replacements for inflected languages. Keys: a folded matched form ("zdrowa" -> "niespieszna"); "@sg3" / "@pl3" / "@pl1" / "@imp" / "@inf" for a match that
    # starts with a verb in that form; "re:<regex>" on the folded match. A rule that has "@" / "re:" keys offers NO replacement for a match none of them covers (the Guardian then
    # asks the LLM rewrite) instead of falling back to ``alternative``; a value of "=" stands for ``alternative`` itself.
    alternative_forms: dict[str, str] = Field(default_factory=dict)
    # Context guards (regexes on folded text): a match that starts inside one of these spans is not a claim (wishes, toasts, company names, technical terms).
    exclude: list[str] = Field(default_factory=list)

    def compiled(self) -> list[re.Pattern[str]]:
        """Patterns are matched against :func:`~spotlight.domain.text.fold`-ed text, so they are diacritic-insensitive (ł included)."""
        out = []
        for p in self.patterns or [self.text]:
            if p.startswith("re:"):
                out.append(re.compile(fold(p[3:]), re.IGNORECASE | re.DOTALL))
            else:
                out.append(re.compile(r"(?<!\w)" + re.escape(fold(p)) + r"(?!\w)", re.IGNORECASE))
        return out

    def compiled_exclude(self) -> list[re.Pattern[str]]:
        return [re.compile(fold(p), re.IGNORECASE) for p in self.exclude]


@dataclass
class ClaimHit:
    rule: ClaimRule
    span: str
    start: int
    end: int
    item_id: str | None = None
    lang: str = "en"
    text: str = field(default="", repr=False)  # the text the hit was found in: lets a replacement be checked against its surroundings

    @property
    def alternative(self) -> str | None:
        """Replacement wording for the matched span (inflection-aware when the rule carries per-form alternatives).

        For Polish rules a clause-level replacement is only offered when it can stand in its place: the span must reach the end of its clause and no
        pronoun clitic ("go leczy") may be left in front of it — otherwise the Guardian falls back to an LLM rewrite instead of producing broken grammar.
        A keyed value "=" stands for the rule's ``alternative``; a "^" in front (or "=^") adds that the span must start a clause (a noun phrase replacing a whole clause)."""
        rule = self.rule
        forms = rule.alternative_forms
        span = squeeze(self.span)  # "l e c z y" / "le-⏎czy" / soft hyphens: look the word up as it is meant
        if forms:
            word = lookup_form(forms, span)  # one inflected word replaced by its agreeing counterpart: always safe in place
            if word:
                return word
            if any(k.startswith(("@", "re:")) for k in forms):
                keyed = pick_keyed(forms, span)
                if not keyed:
                    return None
                needs_start = keyed.startswith(("^", "=^"))
                if keyed.startswith("=^"):
                    keyed = "="
                elif keyed.startswith("^"):
                    keyed = keyed[1:]
                alt = rule.alternative if keyed == "=" else keyed
                return alt if alt and self._fits(needs_start) and (not needs_start or self._starts_clause()) else None
        alt = rule.alternative
        return alt if alt and (rule.lang != "pl" or self._fits()) else None

    def _fits(self, noun_phrase: bool = False) -> bool:
        if not self.text:
            return True
        folded = fold(self.text)
        return not clitic_before(folded, self.start) and clause_closed(folded, self.end, noun_phrase)

    def _starts_clause(self) -> bool:
        return not self.text or clause_start(fold(self.text), self.start)

    @property
    def required_disclaimer(self) -> str | None:
        return self.rule.required_disclaimer


def rule_applies(rule: ClaimRule, markets: list[str], category: str) -> bool:
    return market_matches(rule.markets, markets) and category_matches(rule.categories, category)


def rules_for_lang(rules: list[ClaimRule], lang: str) -> list[ClaimRule]:
    """The rule pack for text in ``lang``: its own rules, language-neutral rules, and the English/legacy rules that
    have no counterpart in ``lang`` (so the Polish pack replaces — not duplicates — the English rule it mirrors)."""
    covered = {r.concept for r in rules if r.lang == lang and r.concept}
    return [r for r in rules if r.lang in ("*", lang) or (r.lang == "en" and r.id not in covered)]


def _first_polish_match(rule: ClaimRule, patterns: list[re.Pattern[str]], views: list[MatchView]) -> tuple[int, int] | None:
    """First match of a Polish rule that is a claim: not negated ("nie leczy", "bez cudów"), not inside one of the rule's excluded contexts. Offsets in the original text."""
    exclusions = rule.compiled_exclude()
    for pat in patterns:
        for view in views:
            blocked = [(m.start(), m.end()) for rx in exclusions for m in rx.finditer(view.text)]
            for m in pat.finditer(view.text):
                if is_negated(view.text, m.start()) or any(s <= m.start() < e for s, e in blocked):
                    continue
                return view.span(m.start(), m.end())
    return None


def find_hits(text: str, rules: list[ClaimRule], markets: list[str], category: str, item_id: str | None = None, lang: str = "en") -> list[ClaimHit]:
    hits: list[ClaimHit] = []
    if lang == "en":
        folded = fold(text)  # 1:1 with the original, so spans map straight back
        for rule in rules_for_lang(rules, lang):
            if not rule_applies(rule, markets, category):
                continue
            for pat in rule.compiled():
                m = pat.search(folded)
                if m:
                    hits.append(ClaimHit(rule, text[m.start() : m.end()], m.start(), m.end(), item_id, lang, text))
                    break
        return hits
    views = match_views(text)  # invisible characters and letter-spaced words are looked through; offsets map back to ``text``
    for rule in rules_for_lang(rules, lang):
        if not rule_applies(rule, markets, category):
            continue
        patterns = rule.compiled()
        if rule.lang == "pl":
            found = _first_polish_match(rule, patterns, views)
        else:
            found = next(((view.span(m.start(), m.end())) for pat in patterns for view in views if (m := pat.search(view.text))), None)
        if found:
            hits.append(ClaimHit(rule, text[found[0] : found[1]], found[0], found[1], item_id, lang, text))
    return hits


def disclaimer_satisfied(disclaimer: str, supporting_text: str) -> bool:
    return contains_phrase(supporting_text, disclaimer)


def unsatisfied_disclaimers(hits: list[ClaimHit], supporting_text: str) -> list[ClaimHit]:
    seen: set[str] = set()
    out: list[ClaimHit] = []
    for h in hits:
        d = h.rule.required_disclaimer
        if d and d not in seen and not disclaimer_satisfied(d, supporting_text):
            seen.add(d)
            out.append(h)
    return out
