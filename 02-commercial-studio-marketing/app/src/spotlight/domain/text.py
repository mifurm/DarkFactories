"""Text helpers shared by the guardian, claims, localization and scorecard logic.

Polish notes (spec §4): ``unicodedata.normalize("NFKD")`` does NOT decompose ``ł``/``Ł`` (nor ``ø``, ``đ``), so a naive
"strip the accents" helper leaves them in place and rules written without diacritics ("kanapa dotarla") miss the same
text typed with them. :func:`fold` handles those letters explicitly and is strictly **length-preserving** (one output
character per input character), so a match found in the folded text maps 1:1 back to the original text.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Literal

_WORD = re.compile(r"[\w'’-]+", re.UNICODE)
_SENT = re.compile(r"(?<=[.!?…])\s+")

# Letters whose accent/stroke is not removed by NFD decomposition (kept 1:1 so spans stay aligned).
_SPECIAL_FOLD = {"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ð": "d", "Ð": "D", "ħ": "h", "Ħ": "H", "ı": "i", "ß": "s"}
# Expanding variant used for slugs / file names (never for span matching).
_ASCII_EXPAND = {**_SPECIAL_FOLD, "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "þ": "th", "Þ": "Th"}
_SPACES = {"\u00a0", "\u202f", "\u2009", "\u2007", "\u2002", "\u2003", "\u200a"}


@lru_cache(maxsize=4096)
def _fold_char(ch: str) -> str:
    if ch < "\x80":
        return ch
    if ch in _SPACES:
        return " "
    mapped = _SPECIAL_FOLD.get(ch)
    if mapped:
        return mapped
    decomposed = unicodedata.normalize("NFD", ch)
    base = decomposed[0]
    if unicodedata.combining(base):  # a stray combining mark: keep the position, drop the mark's effect
        return " "
    return base


def fold(text: str) -> str:
    """Remove diacritics (ł/Ł included) and map exotic spaces to a plain space — 1 output char per input char."""
    return text if text.isascii() else "".join(_fold_char(c) for c in text)


def ascii_fold(text: str) -> str:
    """ASCII-only transliteration for identifiers (``Łódź`` -> ``Lodz``, ``Straße`` -> ``Strasse``). May change the length."""
    out: list[str] = []
    for ch in text:
        if ch < "\x80":
            out.append(ch)
        elif ch in _ASCII_EXPAND:
            out.append(_ASCII_EXPAND[ch])
        else:
            f = _fold_char(ch)
            out.append(f if f < "\x80" else "")
    return "".join(out)


# Invisible format characters that editors, PDFs and CMSs leave inside words (soft hyphen, zero-width space / joiners, BOM, direction marks).
_INVISIBLE = frozenset("\u00ad\u200b\u200c\u200d\u200e\u200f\u2060\ufeff\u180e")
_LETTER = r"[^\W\d_]"
_SPACED_RUN = re.compile(rf"(?<!{_LETTER})(?:{_LETTER}[ .\-]){{2,}}{_LETTER}(?!{_LETTER})")  # "l e c z y", "T-A-N-I-A"
_HYPHEN_BREAK = re.compile(rf"(?<={_LETTER})-[ \t]*\r?\n[ \t]*(?={_LETTER})")  # "le-\nczy": a word broken at the end of a line


class MatchView:
    """One normalised rendering of a text for rule matching, plus the map from its offsets back to the original text."""

    __slots__ = ("_index", "text")

    def __init__(self, text: str, index: list[int] | None) -> None:
        self.text = text
        self._index = index  # None: the view is 1:1 with the original

    def span(self, start: int, end: int) -> tuple[int, int]:
        """Offsets of a match in this view -> offsets in the original text (a word's invisible characters stay inside its span)."""
        if self._index is None or not self._index:
            return start, end
        first = self._index[min(start, len(self._index) - 1)]
        return first, (self._index[end - 1] + 1 if end > start else first)


def squeeze(text: str) -> str:
    """``text`` with its invisible characters removed and its letter-spaced words / line-broken words joined ("l e c z y" -> "leczy"): the form a replacement table is keyed on."""
    t = "".join(c for c in text if c not in _INVISIBLE)
    t = _HYPHEN_BREAK.sub("", t)
    return _SPACED_RUN.sub(lambda m: re.sub(r"[ .\-]", "", m.group(0)), t)


def match_views(text: str) -> list[MatchView]:
    """The renderings of ``text`` that claim / voice patterns are matched against.

    The first is :func:`fold` with invisible characters (soft hyphens, zero-width spaces…) removed. A second one is added only when the text
    contains letter-spaced words ("l e c z y", "T-A-N-I-A") or a word broken across a line ("le-⏎czy"); it joins those letters.
    Every view carries the offsets needed to map a match back to the original text, so findings and fixes quote what the author wrote.
    """
    index: list[int] | None = None
    if any(c in _INVISIBLE for c in text):
        kept = [(i, _fold_char(c)) for i, c in enumerate(text) if c not in _INVISIBLE]
        base, index = "".join(c for _, c in kept), [i for i, _ in kept]
    else:
        base = fold(text)
    drop: set[int] = set()
    for m in _SPACED_RUN.finditer(base):
        drop.update(j for j in range(m.start(), m.end()) if not base[j].isalpha())
    for m in _HYPHEN_BREAK.finditer(base):
        drop.update(range(m.start(), m.end()))
    views = [MatchView(base, index)]
    if drop:
        keep = [j for j in range(len(base)) if j not in drop]
        views.append(MatchView("".join(base[j] for j in keep), [index[j] if index is not None else j for j in keep]))
    return views


def normalize(text: str) -> str:
    """Lower-case, fold diacritics (ł-safe) and strip punctuation; keeps letters/digits for comparisons."""
    t = fold(unicodedata.normalize("NFKC", text).lower())
    if any(c in _INVISIBLE for c in t):
        t = "".join(c for c in t if c not in _INVISIBLE)
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
    """Case/punctuation/diacritic-insensitive whole-phrase containment, with token-overlap fallback for long phrases."""
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


_VOWELS_EN = re.compile(r"[aeiouyäöüéèêàáíóúąęåæø]+")
_VOWELS_PL = re.compile(r"[aeiouyąęó]+")


def syllables_pl(word: str) -> int:
    """Rough Polish syllable count (vowel groups; a consonant + 'i' + vowel, as in 'nia'/'cie', is one syllable)."""
    w = re.sub(r"(?<=[^aeiouyąęó\W\d_])i(?=[aąeęoóuy])", "", word.lower())
    return max(1, len(_VOWELS_PL.findall(w)))


def syllables(word: str, lang: str = "en") -> int:
    """Rough syllable count of one word in ``lang`` (used for voice-over duration estimates)."""
    return syllables_pl(word) if lang == "pl" else max(1, len(_VOWELS_EN.findall(word.lower())))


def reading_ease(text: str, lang: str = "en") -> float:
    """Readability 0..100 (higher = easier). English: Flesch-style; Polish: a Pisarek / Gunning-Fog-PL style index."""
    w = words(text)
    s = max(1, len(sentences(text)))
    if not w:
        return 100.0
    if lang == "pl":
        long_share = sum(1 for x in w if syllables_pl(x) >= 4) / len(w)
        fog = (len(w) / s + 100 * long_share) / 2  # Pisarek's FOG-PL: ≤ 6 very easy … ≥ 13 hard
        return max(0.0, min(100.0, 100.0 - (fog - 4.0) * 7.0))
    syll = sum(max(1, len(_VOWELS_EN.findall(x.lower()))) for x in w)
    score = 206.835 - 1.015 * (len(w) / s) - 84.6 * (syll / len(w))
    return max(0.0, min(100.0, score))


def replace_ci(text: str, find: str, repl: str) -> str:
    return re.sub(re.escape(find), repl, text, flags=re.IGNORECASE)


# ------------------------------------------------------------------------------------------------ language detection

# Frequent Polish words (diacritic-folded) incl. the marketing/coffee vocabulary the Studio deals with.
_PL_WORDS = frozenset(
    ["nie", "sie", "jest", "na", "to", "ze", "dla", "jak", "ale", "po", "do", "przez", "oraz", "lub", "tylko", "tez", "juz", "jeszcze", "bardzo", "gdy", "kiedy", "ktory", "ktora", "ktore", "ktorych", "jestesmy", "jestes", "sa", "byl", "byla", "bylo", "beda", "bedzie", "moze", "mozna", "musi", "chce", "chcemy", "chcesz", "czy", "co", "ten", "ta", "te", "tego", "tej", "tym", "tych", "tak", "nasz", "nasza", "nasze", "nasi", "twoj", "twoja", "twoje", "swoj", "swoja", "swoje", "moj", "moja", "moje", "wiec", "poniewaz", "zeby", "aby", "wszystko", "wszystkie", "kazdy", "kazda", "kazde", "kazdego", "nic", "nikt", "nigdy", "zawsze", "teraz", "dzis", "jutro", "wczoraj", "rano", "wieczor", "noc", "dzien", "dni", "rok", "lat", "roku", "kawa", "kawy", "kawe", "kawie", "kawowy", "kawowa", "kawowe", "palarnia", "palona", "palone", "palony", "paleni", "partiach", "partie", "partii", "ziarna", "ziaren", "poranek", "poranku", "poranki", "poranny", "poranna", "poranne", "porannym", "wolniejszy", "wolniej", "powoli", "niespiesznie", "spokojny", "spokojna", "obudz", "obudzi", "budzi", "swit", "swiatlo", "swiatla", "para", "filizanka", "filizanke", "kubek", "lyk", "lyka", "leczy", "lecza", "leczyc", "wyleczy", "lagodzi", "zapobiega", "zwalcza", "cudowny", "cudowna", "cudowne", "cud", "tani", "tania", "tanie", "tanio", "odchudza", "detoks", "zdrowy", "zdrowa", "zdrowe", "zdrowie", "zdrowia", "najlepsza", "najlepszy", "najlepsze", "swiecie", "niepokoj", "niepokoju", "stres", "bol", "glowy", "marka", "marki", "marce", "klient", "klienci", "klientow", "reklama", "reklamy", "spot", "spotu", "film", "filmu", "lektor", "napisy", "kampania", "kampanii", "kampanie", "rynek", "rynku", "rynkach", "polsce", "polska", "polski", "polskie", "niemczech", "francji", "kanaly", "kanalow", "budzet", "cel", "odbiorcy", "grupa", "docelowa", "produkt", "produkty", "produktu", "premiera", "ton", "przekaz", "haslo", "hasla", "zawiera", "zawieraja", "kofeine", "kofeina", "niezalecane", "dzieci", "kobiet", "ciazy", "pielegniarka", "piekarz", "tata", "mama", "praca", "pracy", "domu", "dom", "okno", "okna", "kuchnia", "kuchni", "slonce", "slonca", "ulica", "ulicy", "znajdz", "sprobuj", "kup", "zamow", "odwiedz", "odkryj", "sprawdz", "wyprobuj", "zasmakuj", "nalej", "poczuj", "zacznij", "prosimy", "dziekujemy", "prosze", "witamy", "czesc", "dobry", "dobra", "dzieki", "dziekuje", "dziekuj", "bez", "nas", "was", "wam", "nad", "pod", "przed", "miedzy", "pobliziu", "pospiechu", "pospiech", "slonce", "wschodzi", "zachodzi", "torba", "torbe", "torbie", "spokojnie", "cicho", "cisza", "ciszy"]
)
_EN_WORDS = frozenset(
    ["the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are", "be", "it", "this", "that", "at", "by", "as", "we", "our", "you", "your", "not", "no", "from", "have", "has", "had", "will", "can", "do", "does", "did", "but", "if", "then", "than", "so", "very", "just", "more", "most", "some", "any", "all", "each", "every", "one", "two", "three", "about", "into", "over", "under", "after", "before", "when", "where", "what", "which", "who", "whom", "how", "why", "morning", "mornings", "coffee", "roast", "roasted", "brew", "pour", "slow", "slowly", "wake", "up", "start", "cures", "cure", "heals", "prevents", "treat", "treats", "cheap", "miracle", "detox", "healthy", "best", "world", "find", "near", "buy", "order", "taste", "try", "new", "contains", "caffeine", "children", "pregnant", "women", "recommended", "brand", "spot", "film", "campaign", "market", "channel", "budget", "audience"]
)
_STRONG_PL = frozenset("ąęłńśźżćĄĘŁŃŚŹŻĆ")
# Polish vocabulary of advertising / claim copy (folded): a one-line claim ("Klinicznie przebadana.") carries no stop-words to go by.
_PL_COPY_WORDS = frozenset(
    "numer jeden jedyna jedyny jedyne taka taki takie idealna idealny idealne lepsza lepszy lepsze lepiej niz kazdej wszystkich wszystkim naturalna naturalny naturalne naturalnie ekologiczna ekologiczny "  # noqa: SIM905
    "organiczna certyfikatem certyfikat neutralna neutralny klimatu klimatyczna srodowisku srodowiska planety planete emisji wspiera wspomaga wzmacnia wzmocni poprawia pomaga chroni obniza reguluje zmniejsza "
    "przyspiesza dodaje daje lekarzy lekarze lekarz polecana polecany polecane polecaja poleca przebadana klinicznie naukowo odpornosc odpornosci serca serce sercu zdrowego zdrowej zdrowych zdrowym zdrowo "
    "organizm organizmu organizmem toksyn tluszcz tluszczu kalorie kalorii schudnac odchudzanie sen snu zasnac metabolizm trawienie krazenie cisnienie nerwy nerwow napiecie napiecia zmeczenie zmeczenia "
    "bolu glowy przeziebienia choroby chorobom chorob objawy pij wypij kup taniej tansza najtansza cudownie uzalezniajacy przelomowa gwarantujemy swiezosc jakosc jakosci receptura smak smaku aromat aromatu "
    "wlasciwosci wlasciwosciach lecznicze leczniczych lekarstwo przeciw ulga ulge koi lagodzi uspokaja detoksykuje oczyszcza odtruwa spala odchudzajaca kofeinowy kop kopa energii energia energie dawka "
    "bezkonkurencyjny bezkonkurencyjna niezrownany niezrownana lider rynku rynek wsrod wybor wyborze polecamy polecam zapraszamy zapraszam oferta oferty promocja zysk zysku ryzyka ryzyko zwrot zwrotu "
    "imprezy impreze odwagi towarzyski towarzyski sukces dzieci dzieciom ciazy mam mamy najmlodszych kawoszy kawosz palarni palarnie filizanki filizance filizanke torby torbie torbe puszka puszki "
    "opakowanie opakowania opakowaniu przyjazne przyjazny dobra dobry dobre planety zrownowazona zrownowazony uprawa uprawy plantacji plantacje etiopii kolumbii gwatemali pozyskiwana pozyskiwane "
    "kazdego kazdym codziennie rankiem wieczorem popoludniu weekend poniedzialek poniedzialku niedziele niedziela sobota piatek mocna mocny lagodna lagodny slodka slodki gorzka gorzki "
    "poziom poziomu cukru krwi jelita jelit zadbaj badania badaniami badan naukowe naukowymi potwierdzone potwierdzona potwierdzony udowodnione udowodniona demencji chorobie chorobach okazja okazje kupuj "
    "gwarancja gwarancji producenta ekspres ekspresu prezentu idealnego smacznego otwarte godzin parzenia kawiarni kawiarnia kawiarnie szum".split()
)
# Function words of the other Latin-script languages the Studio localizes into: Polish must beat them.
_OTHER_WORDS = frozenset(
    "der die das und ist nicht ich wir ein eine mit von zu auf im den dem des auch wie aber oder wenn dass weil wird sind war ihr sein kaffee morgen mein dein euch uns nach bei aus ohne "  # noqa: SIM905
    "le la les des une est pas pour avec dans sur que qui vous nous je tu il elle et ou mais au aux du en cafe "
    "el los las una es para con por su sus pero como mas muy del al lo "
    "il gli uno non per che di della nel nella sono piu come anche "
    "os as uma um nao seu sua muito dos das "
    "de het een niet voor van op aan ook maar als dat wordt zijn wat hij zij wij ons".split()
)
# Letter groups that only Polish (of the languages above) spells this way: przez, czas, wszystko, trzy, szczęście, krzesło, grzyb, przy …
_PL_SHAPE = re.compile(r"cz|prz|trz|drz|krz|grz|wsz|szcz|rzy|^nie[a-z]{4,}|(?:ych|ymi|owej|owym|owych|ujac|ajac|nosc|nosci)$|^.{5,}(?:ego|emu|iej|uje)$")


def _polish_shaped(token: str) -> bool:
    return len(token) >= 4 and _PL_SHAPE.search(token) is not None


def _evidence(text: str) -> tuple[int, int, int, int, int, int]:
    """(known Polish, Polish-shaped, English, other-language, token count, letters not seen in English) evidence counts for ``text``."""
    toks = re.findall(r"[^\W\d_]+", match_views(text)[-1].text.lower())  # letter-spaced words ("L E C Z Y") are read joined
    known = sum(1 for t in toks if t in _PL_WORDS or t in _PL_COPY_WORDS)
    shaped = sum(1 for t in toks if t not in _PL_WORDS and t not in _PL_COPY_WORDS and _polish_shaped(t))
    en = sum(1 for t in toks if t in _EN_WORDS)
    other = sum(1 for t in toks if t in _OTHER_WORDS)
    known += 2 * sum(1 for ch in text if ch in _STRONG_PL)
    strong_o = 1 if ("ó" in text or "Ó" in text) else 0
    if not other and strong_o:  # Polish, Spanish, Czech … use it: weak evidence, only when nothing points elsewhere
        known += 1
    return known, shaped, en, other, len(toks), strong_o


def detect_lang(text: str) -> Literal["pl", "en"] | None:
    """Conservative en/pl detector (stop-words, copy vocabulary, Polish letter groups and endings, characteristic letters); works with and without diacritics.

    Returns ``None`` when there is not enough evidence. Only used to *select rule packs* — never to reject input.
    """
    if not text or not text.strip():
        return None
    known, shaped, en, other, n, strong_o = _evidence(text)
    if not n:
        return None
    pl = known + shaped
    if pl >= 2 and pl > en and pl > other:
        return "pl"
    if en >= 2 and en > pl:
        return "en"
    if known == 1 and shaped == 0 and en == 0 and other == 0 and n <= 3 and not strong_o:
        return "pl"
    return None


def has_polish_evidence(text: str) -> bool:
    """Some Polish evidence (a Polish word, letter group or ending, a Polish letter) and none for English or another language — too little for :func:`detect_lang`
    to commit, enough to also try the Polish rules on an untagged line ("Pomaga zapomniec o stresie.")."""
    if not text or not text.strip():
        return False
    known, shaped, en, other, n, _ = _evidence(text)
    return bool(n) and known + shaped >= 1 and en == 0 and other == 0
