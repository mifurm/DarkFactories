"""Claims & compliance rule engine (CS-02): approved / prohibited / needs-substantiation claims per market & category."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from .text import contains_phrase

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

    def compiled(self) -> list[re.Pattern[str]]:
        out = []
        for p in self.patterns or [self.text]:
            if p.startswith("re:"):
                out.append(re.compile(p[3:], re.IGNORECASE | re.DOTALL))
            else:
                out.append(re.compile(r"(?<!\w)" + re.escape(p) + r"(?!\w)", re.IGNORECASE))
        return out


@dataclass
class ClaimHit:
    rule: ClaimRule
    span: str
    start: int
    end: int
    item_id: str | None = None


def rule_applies(rule: ClaimRule, markets: list[str], category: str) -> bool:
    return market_matches(rule.markets, markets) and category_matches(rule.categories, category)


def find_hits(text: str, rules: list[ClaimRule], markets: list[str], category: str, item_id: str | None = None) -> list[ClaimHit]:
    hits: list[ClaimHit] = []
    for rule in rules:
        if not rule_applies(rule, markets, category):
            continue
        for pat in rule.compiled():
            m = pat.search(text)
            if m:
                hits.append(ClaimHit(rule, m.group(0), m.start(), m.end(), item_id))
                break
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
