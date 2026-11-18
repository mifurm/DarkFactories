"""Polish morphology helpers for rule matching (brand-voice terms, hype terms).

Polish inflects nouns, adjectives and verbs (``tani / tania / tanie / taniego / tanim``, ``leczy / leczyć / wyleczy``) and is very often
typed without diacritics on phones, so keyword lists must be matched by *stem + ending classes* on **folded** text
(:func:`spotlight.domain.text.fold`, which also handles ``ł``). Replacements must agree in gender/case with the word they replace
("tania kawa" -> "przystępna kawa", not "przystępny kawa"), hence the per-form tables below. Terms without a deterministic,
grammatical replacement fall back to the Guardian's LLM rewrite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .text import fold


@dataclass(frozen=True)
class PlTerm:
    """A forbidden Polish brand-voice term: folded regex of its inflected forms + agreement-aware replacements."""

    word: str
    pattern: str  # regex on FOLDED text, anchored with \b by the caller
    forms: dict[str, str] = field(default_factory=dict)  # matched form (lower-case, with or without diacritics) -> replacement; "" = no deterministic replacement for that form
    default: str | None = None
    strict: bool = False  # True: a matched form that is not in ``forms`` gets no replacement (the LLM rewrites it) instead of the pack-wide / default one


def _forms(**pairs: str) -> dict[str, str]:
    return pairs


def _agree(base_forms: dict[str, str]) -> dict[str, str]:
    """Add the diacritic-less spelling of every key so replacements are found for text typed without diacritics."""
    out = dict(base_forms)
    for k, v in base_forms.items():
        out.setdefault(fold(k), v)
    return out


def _comparative_forms() -> dict[str, str]:
    """tani / tańszy / najtańszy: every inflected form maps to the agreeing neutral adjective (superlatives lose their "naj-")."""
    cheap = {"y": "przystępny", "a": "przystępna", "ą": "przystępną", "e": "przystępne", "ego": "przystępnego", "ej": "przystępnej", "emu": "przystępnemu", "ym": "przystępnym", "ych": "przystępnych", "ymi": "przystępnymi"}
    cmp_ = {"y": "korzystniejszy", "a": "korzystniejsza", "ą": "korzystniejszą", "e": "korzystniejsze", "ego": "korzystniejszego", "ej": "korzystniejszej", "emu": "korzystniejszemu", "ym": "korzystniejszym", "ych": "korzystniejszych", "ymi": "korzystniejszymi"}
    out = {"tani": cheap["y"], "tania": cheap["a"], "tanią": cheap["ą"], "tanie": cheap["e"], "taniego": cheap["ego"], "taniemu": cheap["emu"], "tanim": cheap["ym"], "tanich": cheap["ych"], "tanimi": cheap["ymi"], "tanio": "w dobrej cenie",
           "taniej": "", "najtaniej": ""}  # "taniej" is both the adverb ("kup taniej") and the feminine genitive ("do taniej kawy"): only a rewrite can tell
    for end, word in cmp_.items():
        out["tańsz" + end] = word
        out["najtańsz" + end] = cheap[end]
    return _agree(out)


BUILTIN_TERMS: dict[str, PlTerm] = {
    "tani": PlTerm("tani", r"(?:naj)?tan(?:i|ia|ie|io|ich|im|imi|iego|iej|iemu)|(?:naj)?tansz\w*", _comparative_forms(), "w dobrej cenie"),
    "cudowny": PlTerm(
        "cudowny",
        r"cudown(?:y|a|e|ego|ej|emu|ym|ych|ymi|ie)",
        _agree({
            "cudowny": "wyjątkowy", "cudowna": "wyjątkowa", "cudowną": "wyjątkową", "cudowne": "wyjątkowe", "cudownego": "wyjątkowego", "cudownej": "wyjątkowej",
            "cudownemu": "wyjątkowemu", "cudownym": "wyjątkowym", "cudownych": "wyjątkowych", "cudownymi": "wyjątkowymi", "cudownie": "wyjątkowo",
        }),
        "wyjątkowy",
    ),
    "cud": PlTerm("cud", r"cud(?:u|em|a|ow|om|ach|zie)?|cudotwor\w*|cudenk\w*"),
    # "detoks" is a masculine noun: only its own (inflected) forms have a grammatical stand-in ("Poranny detoks" -> "Poranny rytuał"); verbs and English spellings go to the rewrite
    "detoks": PlTerm(
        "detoks",
        r"detoks\w*|detox\w*",
        _agree({"detoks": "rytuał", "detoksu": "rytuału", "detoksem": "rytuałem", "detoksie": "rytuale", "detoksy": "rytuały", "detoksów": "rytuałów", "detoksom": "rytuałom", "detoksach": "rytuałach", "detoksami": "rytuałami"}),
        None,
        True,
    ),
    "hack": PlTerm(
        "hack",
        r"(?:life\s?)?hack(?:a|u|iem|owi|i|ow|ach|ami|om)?",
        _agree({"hack": "nawyk", "hacka": "nawyku", "hackiem": "nawykiem", "hacku": "nawyku", "hacki": "nawyki", "hacków": "nawyków", "life hack": "nawyk", "lifehack": "nawyk"}),
        "nawyk",
    ),
    "uzależniający": PlTerm(
        "uzależniający",
        r"uzalezn\w*",
        _agree({
            "uzależniający": "łatwy do pokochania", "uzależniająca": "łatwa do pokochania", "uzależniające": "łatwe do pokochania", "uzależniającego": "łatwego do pokochania",
            "uzależniającej": "łatwej do pokochania", "uzależniającym": "łatwym do pokochania", "uzależnia": "przyciąga",
        }),
        None,
        True,
    ),
    "gwarantowany": PlTerm(
        "gwarantowany",
        # a guarantee as a promise ("gwarancja jakości", "gwarantujemy") — not the plain warranty information of a product ("2 lata gwarancji producenta")
        r"gwarant\w*|(?<!lata )(?<!lat )(?<!rok )(?<!miesiace )(?<!miesiecy )(?<!miesiac )(?<!\d )gwarancj\w*(?!\s+(?:producenta|sprzedawcy|dystrybutora|na\s+(?:ekspres|sprzet|urzadzeni|maszyn)\w*|rozszerzon\w+)|\s*:?\s*\d+\s*(?:miesi|lat|rok|dni|tygod)\w*)",
        _agree({
            "gwarantowany": "niezawodny", "gwarantowana": "niezawodna", "gwarantowane": "niezawodne", "gwarantowanego": "niezawodnego", "gwarantowanej": "niezawodnej",
            "gwarantowanym": "niezawodnym", "gwarantujemy": "dbamy o", "gwarantuje": "dba o", "gwarantuję": "dbam o", "gwarantujesz": "dbasz o", "gwarantujecie": "dbacie o",
            "gwarancja": "obietnica", "gwarancji": "obietnicy", "gwarancję": "obietnicę", "gwarancją": "obietnicą",
        }),
        None,
        True,
    ),
    "przełomowy": PlTerm(
        "przełomowy",
        r"przelomow(?:y|a|e|ego|ej|emu|ym|ych|ymi|o)|game[\s-]?changer\w*",
        _agree({"przełomowy": "nowy", "przełomowa": "nowa", "przełomowe": "nowe", "przełomowego": "nowego", "przełomowej": "nowej", "przełomowym": "nowym", "przełomową": "nową", "game-changer": "mile widziana zmiana", "gamechanger": "mile widziana zmiana", "game changer": "mile widziana zmiana"}),
        "nowy",
    ),
}


_BUILTIN_BY_FOLDED = {fold(k).lower(): v for k, v in BUILTIN_TERMS.items()}  # "uzależniający" and "uzalezniajacy" find the same term


def generic_pattern(word: str) -> str:
    """Stem + ending-class regex (folded) for a user-added word, chosen by the word's ending (adjective / feminine / neuter / consonant)."""
    w = fold(word).lower().strip()
    if len(w) < 4 or " " in w:
        return re.escape(w).replace(r"\ ", r"\s+")
    if w.endswith(("y", "i")):  # adjectives: tani, cudowny
        return re.escape(w[:-1]) + r"(?:y|i|a|e|o|ego|ej|emu|ym|im|ych|ich|ymi|imi|ie)"
    if w.endswith("a"):  # feminine nouns: kawa
        return re.escape(w[:-1]) + r"(?:a|y|e|ie|om|ami|ach|o)"
    if w.endswith(("o", "e")):  # neuter nouns
        return re.escape(w[:-1]) + r"(?:o|e|a|u|em|ach|om|ami|ow)"
    return re.escape(w) + r"(?:u|a|em|owi|ie|y|ow|om|ami|ach)?"  # masculine nouns: detoks


def term_for(word: str) -> PlTerm:
    return _BUILTIN_BY_FOLDED.get(fold(word).lower().strip()) or PlTerm(word, generic_pattern(word))


def term_regex(term: PlTerm) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)(?:" + term.pattern + r")(?!\w)", re.IGNORECASE)


def hype_regex(spec: str) -> re.Pattern[str]:
    """``re:…`` entries are regexes (folded); plain entries are matched as whole words/phrases with the generic inflection classes."""
    if spec.startswith("re:"):
        return re.compile(fold(spec[3:]), re.IGNORECASE | re.DOTALL)
    return re.compile(r"(?<!\w)(?:" + generic_pattern(spec) + r")(?!\w)", re.IGNORECASE)


def match_case(original: str, replacement: str) -> str:
    """Carry the capitalisation of the replaced word over to its replacement ("Tania" -> "Przystępna")."""
    if not original or not replacement:
        return replacement
    if len(original) > 1 and original.isupper():
        return replacement.upper()
    if original[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def lookup_form(forms: dict[str, str], span: str) -> str | None:
    """Replacement for ``span`` from a per-form table, tried with and without diacritics."""
    low = span.lower().strip()
    return forms.get(low) or forms.get(fold(low))


def form_for(forms: dict[str, str], span: str) -> str | None:
    """Like :func:`lookup_form`, but an explicit empty value ("no deterministic replacement for this form") is returned as ``""``, not ``None``."""
    low = span.lower().strip()
    if low in forms:
        return forms[low]
    return forms.get(fold(low))


# ---------------------------------------------------------------------------------------------------------- context guards (folded text)
_CLAUSE_BREAK = re.compile(r"[.!?;:\n\u2014\u2013()]")
_NEGATION = re.compile(r"(?:\b(?:nie|ani)\s+(?:[^\W\d_]+\s+){0,2}|\bbez\s+|\bzadn\w+\s+(?:[^\W\d_]+\s+)?)$", re.IGNORECASE)
_DISCLAIMING = re.compile(r"\bnie\s+(?:twierdz|obiecuj|mow|sugeruj|gwarantuj|deklaruj|zapewni)\w*\s*,?\s*(?:ze|iz)\s+(?:[^\W\d_]+\s+){0,4}$", re.IGNORECASE)
_ASKED = re.compile(r"\bczy\s+(?:[^\W\d_]+\s+){0,3}$", re.IGNORECASE)  # "Czy kawa leczy?" asks, it does not claim; "Czy wiesz, że kawa leczy…?" still does


def is_negated(folded: str, start: int) -> bool:
    """True when the match at ``start`` is inside the scope of a negation: "nie leczy", "nie jest tania", "bez cudów", "żadnych cudownych obietnic", "nie twierdzimy, że kawa …"
    (or of a plain question: "Czy kawa leczy?").

    Only the words directly in front of the match count (and never across a clause boundary or a comma), so "Nie czekaj, zamów cudowną kawę" is still a claim."""
    clause = _CLAUSE_BREAK.split(folded[max(0, start - 90) : start])[-1]
    return _NEGATION.search(clause) is not None or _DISCLAIMING.search(clause) is not None or _ASKED.search(clause) is not None


_CLITICS = frozenset("go ja je ich im cie ci mu jej nas was wam sie mi nam sobie ciebie jego".split())  # noqa: SIM905
_PREV_WORD = re.compile(r"([^\W\d_]+)\s+$")
_CLOSER = re.compile(r"\s*(?:$|,(?!\s*(?:ktor\w+|jak\w*|co|czym|gdzie)\b)|[.;:!?…)\u2014\u2013\"'\u201d\u00bb]|(?:i|oraz|a|ale|bo|lub|albo|gdy|kiedy|zeby|aby|ktor\w+|jak|wiec|dzieki|dla|na|w|z|ze|do|po|przy|przed|od|przez|nad|pod|bez|za|o)\b)", re.IGNORECASE)
# a replacement that is a noun phrase must not be followed by a prepositional phrase or a coordinated word either ("Kawa, z której jesteśmy dumni w mieście")
_CLOSER_NP = re.compile(r"\s*(?:$|,(?!\s*(?:ktor\w+|jak\w*|co|czym|gdzie)\b)|[.;:!?…)\u2014\u2013\"'\u201d\u00bb]|(?:a|ale|bo|gdy|kiedy|zeby|aby|wiec)\b)", re.IGNORECASE)
_CLAUSE_START = re.compile(r"(?:^\s*|[.!?:;\u2014\u2013(\"\u201e\u201c\u00ab]\s*|\bto\s+)$", re.IGNORECASE)


def clitic_before(folded: str, start: int) -> bool:
    """A pronoun clitic right in front of a span ("kawa go leczy", "ją uspokaja") would be left stranded by replacing only the verb."""
    m = _PREV_WORD.search(folded[max(0, start - 30) : start])
    return bool(m and m.group(1).lower() in _CLITICS)


def clause_closed(folded: str, end: int, noun_phrase: bool = False) -> bool:
    """Does the clause end (or a new one / a prepositional phrase start) right after ``end``? Otherwise a replacement would leave dangling words behind it.
    A replacement that is a noun phrase (``noun_phrase``) needs the clause to really end: a prepositional phrase would attach to it."""
    return (_CLOSER_NP if noun_phrase else _CLOSER).match(folded, end) is not None


def clause_start(folded: str, start: int) -> bool:
    """Does a clause (or the predicate after "to") begin at ``start``? A nominative noun phrase may only replace a span that does."""
    return _CLAUSE_START.search(folded[:start]) is not None


# 3rd-person-singular forms (folded) of the verbs health / weight claims are made with; the 1st-person-plural form is derived ("leczy" -> "leczymy").
_SG3 = frozenset(
    "leczy wyleczy uleczy zaleczy uzdrawia uzdrowi lagodzi zlagodzi koi ukoi uspokaja uspokoi usmierza zwalcza zwalczy walczy chroni ochroni zapobiega zapobiegnie obniza obnizy reguluje normalizuje likwiduje "  # noqa: SIM905
    "eliminuje redukuje zmniejsza zmniejszy niweluje wzmacnia wzmocni wspiera wspomaga poprawia poprawi polepsza zwieksza zwiekszy podnosi buduje stymuluje regeneruje odzywia odmladza pobudza przyspiesza "
    "przyspieszy odchudza spala oczyszcza odtruwa usuwa dba dodaje pomaga pomoze sprzyja ulatwia usprawnia detoksykuje wyszczupla rozbudza daje przywraca".split()
)


def _first_person_plural(w: str) -> str:
    for ending, repl in (("uje", "ujemy"), ("aje", "ajemy"), ("a", "amy"), ("i", "imy"), ("y", "ymy"), ("e", "emy")):
        if w.endswith(ending):
            return w[: -len(ending)] + repl
    return w


_PL1 = frozenset(_first_person_plural(w) for w in _SG3)


def verb_class(span: str) -> str | None:
    """"sg3" / "pl1" when the span starts with one of the claim verbs in that form, else ``None`` (nouns, adjectives, other forms have no deterministic rewrite)."""
    m = re.match(r"[^\W\d_]+", span.strip())
    if not m:
        return None
    w = fold(m.group(0)).lower()
    if w in _SG3:
        return "sg3"
    return "pl1" if w in _PL1 else None


def pick_keyed(forms: dict[str, str], span: str) -> str | None:
    """Replacement chosen by the verb form the span starts with (``@sg3`` / ``@pl1`` keys) or by a ``re:`` key matched against the whole folded span."""
    cls = verb_class(span)
    if cls and f"@{cls}" in forms:
        return forms[f"@{cls}"]
    folded = fold(span).lower().strip()
    for key, value in forms.items():
        if key.startswith("re:") and re.fullmatch(key[3:], folded, re.DOTALL):
            return value
    return None


# Hype / superlative / sales-shouting patterns for the Polish voice pack (regexes on folded text).
HYPE_PATTERNS_PL: list[str] = [
    r"re:najlepsz\w*\s+(?:\w+\s+){0,2}na\s+swiecie",
    r"re:\bnumer\s+(?:jeden|1)\b",
    r"re:\bnr\s*1\b",
    r"re:(?<!powod )(?<!krok )(?<!punkt )(?<!zasada )(?<!miejsce )(?<!odcinek )(?<!sezon )#\s*1\b(?!\s*:)",
    r"re:bezkonkurencyjn\w+",
    r"re:niezrownan\w+",
    r"re:rewolucyjn\w+|\brewolucj\w+",
    r"re:zmieni\w+\s+zyci\w*",
    r"re:\btylko\s+(?:dzis|teraz|u\s+nas)\b",
    r"re:\b(?:super|mega|hiper)[\s-]*(?:oferta|okazja|cena|promocja|wyprzedaz|hit)\w*",
    r"re:\bhit\s+cenow\w+|\bszal\s+cenow\w+|\bwyprzedaz\w*|\bostatnie\s+sztuk\w+|\bnie\s+przegap\w*",
    r"re:(?<![\w.,])[-\u2212\u2013]\s?\d{1,2}\s?%",
]

# The Polish brand-voice pack the Guardian falls back to when a brand kit carries no Polish rules of its own.
DEFAULT_PL_FORBIDDEN = ["tani", "cud", "cudowny", "detoks", "hack", "uzależniający", "gwarantowany", "przełomowy"]
DEFAULT_PL_REPLACEMENTS = {"tani": "przystępny", "cudowny": "wyjątkowy", "detoks": "rytuał", "hack": "nawyk", "uzależniający": "łatwy do pokochania", "gwarantowany": "niezawodny", "przełomowy": "nowy"}
