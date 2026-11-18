"""Deterministic, language-aware safety word lists shared by the offline stub and the Azure adapter's local pre-check.

Azure AI Content Safety analyses Polish text natively, but Prompt Shields' documented training languages do not include Polish, so the
Azure adapter also runs :func:`local_attack` (defence in depth: a cheap local check before the service call). The stub uses the same lists
for its severity heuristics, so offline tests exercise Polish text exactly like English text. Polish patterns are word-anchored regexes on
diacritic-folded, lower-cased text (``ł`` included): "zabić" and "zabic" are the same word, "zabiera" (takes) is not.
"""

from __future__ import annotations

import re

from ...domain.text import fold

SEVERE: dict[str, list[str]] = {
    "Violence": ["kill", "stab", "murder", "shoot", "bomb", "massacre", "bloodbath"],
    "Hate": ["subhuman", "hate speech", "racial slur", "inferior race"],
    "SelfHarm": ["suicide", "self-harm", "hurt myself", "end my life"],
    "Sexual": ["pornographic", "explicit sex", "nsfw"],
}
MILD: dict[str, list[str]] = {"Violence": ["fight", "gun", "weapon", "attack"], "Hate": ["stupid", "idiot"], "SelfHarm": [], "Sexual": ["sexy"]}

SEVERE_PL: dict[str, str] = {
    "Violence": r"\b(?:zabi(?:c|j\w*|l\w*)|zamord\w+|morderstw\w+|zastrzel\w*|zadzga\w*|bomb(?:a|y|e|ie|ami|ach)|masakr\w+|rzez(?:i|ia|ie)?)\b",
    "Hate": r"\b(?:podludz\w*|gorsz\w+\s+ras\w+|mow\w+\s+nienawisci)\b",
    "SelfHarm": r"\b(?:samobojstw\w*|zabije\s+sie|odebrac\s+sobie\s+zycie|okaleczyc\s+sie|skrzywdze\s+sie)\b",
    "Sexual": r"\bpornograf\w*",
}
MILD_PL: dict[str, str] = {
    "Violence": r"\b(?:pistolet\w*|bron|broni|atak\w*|bijatyk\w*)\b",
    "Hate": r"\b(?:glup\w+|debil\w*|kretyn\w*|idiot\w*)\b",
    "SelfHarm": r"(?!x)x",
    "Sexual": r"\bseksown\w*",
}
_SEVERE_PL_RX = {k: re.compile(v) for k, v in SEVERE_PL.items()}
_MILD_PL_RX = {k: re.compile(v) for k, v in MILD_PL.items()}

PROTECTED_PHRASES = ["sunrise anthem lyrics", "la la la golden morning", "(c) universal sound publishing", "tekst piosenki sunrise anthem"]

ATTACKS = [
    r"ignore (all |any )?(previous|prior|above) (instructions|rules)",
    r"reveal (the |your )?(system|hidden) prompt",
    r"disregard (the )?(system|safety)",
    r"you are now (in )?(developer|dan) mode",
]
# Polish (matched on folded text): zignoruj / pomiń / zapomnij + poprzednie instrukcje · ujawnij prompt systemowy · tryb developera / DAN
ATTACKS_PL = [
    r"\b(?:zignoruj|ignoruj|pomin|zapomnij o|odrzuc)\s+(?:\w+\s+){0,3}(?:poprzedni\w*|wczesniejsz\w*|powyzsz\w*|wszystk\w*)\s+(?:\w+\s+){0,2}(?:instrukcj\w*|polecen\w*|zasad\w*|regul\w*|wytyczn\w*)",
    r"\b(?:zignoruj|ignoruj|pomin)\s+(?:\w+\s+){0,2}(?:instrukcj\w*|polecen\w*|zasad\w*)\s+(?:systemow\w*|bezpieczenstw\w*)",
    r"\b(?:ujawnij|pokaz|wyswietl|zdradz|podaj)\s+(?:\w+\s+){0,3}(?:prompt\w*|instrukcj\w*\s+systemow\w*|polecen\w*\s+systemow\w*)",
    r"\b(?:jestes|dzialaj|przelacz sie)\s+(?:teraz\s+)?(?:w\s+)?tryb\w*\s+(?:developera|dewelopera|programisty|dan)\b",
    r"\b(?:udawaj|zachowuj sie jak)\s+(?:\w+\s+){0,2}(?:bez\s+(?:zadnych\s+)?ogranicze\w*|dan)\b",
]
_ATTACK_RX = [re.compile(p) for p in ATTACKS]
_ATTACK_PL_RX = [re.compile(p) for p in ATTACKS_PL]


def _pl(text: str) -> str:
    return re.sub(r"\s+", " ", fold(text).lower())


def local_attack(text: str) -> bool:
    """True when ``text`` (English or Polish) contains an instruction-override / prompt-extraction pattern."""
    low = text.lower()
    if any(rx.search(low) for rx in _ATTACK_RX):
        return True
    folded = _pl(text)
    return any(rx.search(folded) for rx in _ATTACK_PL_RX)


def severity(text: str) -> dict[str, int]:
    """Per-category severity 0 / 2 / 4 from the word lists (stub only; Azure returns the service's own levels)."""
    low, folded = text.lower(), _pl(text)
    cats: dict[str, int] = {}
    for cat in ("Hate", "SelfHarm", "Sexual", "Violence"):
        sev = 0
        if any(w in low for w in SEVERE[cat]) or _SEVERE_PL_RX[cat].search(folded):
            sev = 4
        elif any(w in low for w in MILD[cat]) or _MILD_PL_RX[cat].search(folded):
            sev = 2
        cats[cat] = sev
    return cats


def protected(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in PROTECTED_PHRASES)
