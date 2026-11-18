"""Polish text toolkit for the video pipeline: numbers in words (TTS), NBSP typography ("sierotki"), URL / abbreviation reading.

* Voice-over text goes through :func:`tts_text` so the speech engine never has to guess how to read ``100%``, ``340 g`` or ``379,00 zł``
  (the captions keep the digits).
* Captions, supers, the end card and legal lines go through :func:`typeset` so single-letter words (``i w z o u a``) and number+unit
  pairs never end a line (NBSP), and brand names do not break across lines.
"""

from __future__ import annotations

import re

NBSP = "\u00a0"

_UNITS = ["zero", "jeden", "dwa", "trzy", "cztery", "pięć", "sześć", "siedem", "osiem", "dziewięć"]
_TEENS = ["dziesięć", "jedenaście", "dwanaście", "trzynaście", "czternaście", "piętnaście", "szesnaście", "siedemnaście", "osiemnaście", "dziewiętnaście"]
_TENS = ["", "", "dwadzieścia", "trzydzieści", "czterdzieści", "pięćdziesiąt", "sześćdziesiąt", "siedemdziesiąt", "osiemdziesiąt", "dziewięćdziesiąt"]
_HUNDREDS = ["", "sto", "dwieście", "trzysta", "czterysta", "pięćset", "sześćset", "siedemset", "osiemset", "dziewięćset"]
_SCALES = [("tysiąc", "tysiące", "tysięcy"), ("milion", "miliony", "milionów"), ("miliard", "miliardy", "miliardów")]


def plural_form(n: int, one: str, few: str, many: str) -> str:
    """Polish noun form after a numeral: 1 plik · 2–4 pliki (not 12–14) · 5+ plików."""
    n = abs(n)
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _unit_word(n: int, feminine: bool) -> str:
    """Last digit as a word; feminine nouns take "dwie" after "dwadzieścia" / "sto" (dwadzieścia dwie godziny). A compound ending in 1 stays "jeden" for every
    gender ("dwadzieścia jeden godzin", "sto jeden kaw"); only a lone 1 is "jedna" (see :func:`cardinal`)."""
    return "dwie" if (feminine and n == 2) else _UNITS[n]


def _below_1000(n: int, feminine: bool = False) -> list[str]:
    words: list[str] = []
    if n >= 100:
        words.append(_HUNDREDS[n // 100])
        n %= 100
    if n >= 20:
        words.append(_TENS[n // 10])
        n %= 10
        if n:
            words.append(_unit_word(n, feminine))
    elif n >= 10:
        words.append(_TEENS[n - 10])
    elif n or not words:
        words.append(_unit_word(n, feminine))
    return words


def cardinal(n: int, feminine: bool = False) -> str:
    """0 -> zero, 21 -> dwadzieścia jeden, 1000 -> tysiąc, 2025 -> dwa tysiące dwadzieścia pięć (up to 10^12)."""
    if n < 0:
        return "minus " + cardinal(-n, feminine)
    if n == 0:
        return "zero"
    if n == 1 and feminine:
        return "jedna"
    parts: list[str] = []
    chunks: list[int] = []
    m = n
    while m:
        chunks.append(m % 1000)
        m //= 1000
    for idx in range(len(chunks) - 1, -1, -1):
        c = chunks[idx]
        if not c:
            continue
        if idx == 0:
            parts += _below_1000(c, feminine)
            continue
        one, few, many = _SCALES[idx - 1]
        parts.append(one if c == 1 else f"{' '.join(_below_1000(c))} {plural_form(c, one, few, many)}")
    return " ".join(parts)


_CARDINAL_GENITIVE = {
    "zero": "zera", "jeden": "jednego", "jedna": "jednej", "dwa": "dwóch", "dwie": "dwóch", "trzy": "trzech", "cztery": "czterech", "pięć": "pięciu", "sześć": "sześciu", "siedem": "siedmiu",
    "osiem": "ośmiu", "dziewięć": "dziewięciu", "dziesięć": "dziesięciu", "jedenaście": "jedenastu", "dwanaście": "dwunastu", "trzynaście": "trzynastu", "czternaście": "czternastu",
    "piętnaście": "piętnastu", "szesnaście": "szesnastu", "siedemnaście": "siedemnastu", "osiemnaście": "osiemnastu", "dziewiętnaście": "dziewiętnastu", "dwadzieścia": "dwudziestu",
    "trzydzieści": "trzydziestu", "czterdzieści": "czterdziestu", "pięćdziesiąt": "pięćdziesięciu", "sześćdziesiąt": "sześćdziesięciu", "siedemdziesiąt": "siedemdziesięciu",
    "osiemdziesiąt": "osiemdziesięciu", "dziewięćdziesiąt": "dziewięćdziesięciu", "sto": "stu", "dwieście": "dwustu", "trzysta": "trzystu", "czterysta": "czterystu", "pięćset": "pięciuset",
    "sześćset": "sześciuset", "siedemset": "siedmiuset", "osiemset": "ośmiuset", "dziewięćset": "dziewięciuset", "tysiąc": "tysiąca", "tysiące": "tysięcy", "milion": "miliona",
    "miliony": "milionów", "miliard": "miliarda", "miliardy": "miliardów",
}


def genitive(words: str) -> str:
    """A cardinal in words in the genitive, as it stands after od / do / bez / dla ("trzydzieści dziewięć" -> "trzydziestu dziewięciu"). A compound ending in 1 keeps "jeden" ("dwudziestu jeden")."""
    parts = words.split()
    out = [_CARDINAL_GENITIVE.get(w, w) for w in parts]
    if len(parts) > 1 and parts[-1] in {"jeden", "jedna"}:
        out[-1] = parts[-1]
    return " ".join(out)


_ORD_UNITS = ["", "pierwszy", "drugi", "trzeci", "czwarty", "piąty", "szósty", "siódmy", "ósmy", "dziewiąty"]
_ORD_TEENS = ["dziesiąty", "jedenasty", "dwunasty", "trzynasty", "czternasty", "piętnasty", "szesnasty", "siedemnasty", "osiemnasty", "dziewiętnasty"]
_ORD_TENS = ["", "", "dwudziesty", "trzydziesty", "czterdziesty", "pięćdziesiąty", "sześćdziesiąty", "siedemdziesiąty", "osiemdziesiąty", "dziewięćdziesiąty"]


def _gen(word: str) -> str:
    """masculine nominative ordinal -> genitive ("piętnasty" -> "piętnastego")."""
    return word[:-1] + "ego" if word.endswith("y") else word[:-1] + "iego"


def ordinal_genitive(n: int) -> str:
    """Days and years in dates: 15 -> piętnastego · 2027 -> dwa tysiące dwudziestego siódmego."""
    if n >= 2000:
        rest = n - 2000
        head = "dwa tysiące" if rest else "dwutysięcznego"
        if not rest:
            return head
        return f"{head} {ordinal_genitive(rest)}"
    if n >= 100:
        return f"{cardinal(n - n % 100)} {ordinal_genitive(n % 100)}" if n % 100 else _gen(cardinal(n))
    if n >= 20:
        return _gen(_ORD_TENS[n // 10]) + (f" {_gen(_ORD_UNITS[n % 10])}" if n % 10 else "")
    if n >= 10:
        return _gen(_ORD_TEENS[n - 10])
    return _gen(_ORD_UNITS[n]) if n else "zerowego"


def ordinal_case(n: int, case: str = "gen") -> str:
    """The ordinal a date or year takes after its preposition: "gen" (do dwa tysiące dwudziestego szóstego), "loc" / "ins" (w dwa tysiące dwudziestym szóstym), "nom" (… dwudziesty szósty)."""
    out = []
    for w in ordinal_genitive(n).split():
        if case == "gen":
            out.append(w)
        elif w.endswith("iego"):
            out.append(w[:-4] + ("im" if case in {"loc", "ins"} else "i"))
        elif w.endswith("ego"):
            out.append(w[:-3] + ("ym" if case in {"loc", "ins"} else "y"))
        else:
            out.append(w)
    return " ".join(out)


def _ordinal_gender(word: str, gender: str) -> str:
    """Masculine nominative ordinal -> feminine / neuter ("trzeci" -> "trzecia" / "trzecie", "drugi" -> "druga" / "drugie", "pierwszy" -> "pierwsza" / "pierwsze")."""
    if gender == "m":
        return word
    a, e = ("a", "e")
    if word.endswith(("gi", "ki")):
        return word[:-1] + (a if gender == "f" else "ie")
    if word.endswith("y"):
        return word[:-1] + (a if gender == "f" else e)
    return word + (a if gender == "f" else e)


def ordinal_nominative(n: int, gender: str = "m") -> str:
    """"3." before a noun: trzeci dzień / trzecia edycja / trzecie miejsce (nominative; every part of a compound agrees: dwudziesta pierwsza)."""
    return " ".join(_ordinal_gender(w, gender) for w in ordinal_case(n, "nom").split())


_MONTHS_GEN = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września", "października", "listopada", "grudnia"]
_HOURS_ORD = [
    "północ", "pierwsza", "druga", "trzecia", "czwarta", "piąta", "szósta", "siódma", "ósma", "dziewiąta", "dziesiąta", "jedenasta", "dwunasta", "trzynasta", "czternasta",
    "piętnasta", "szesnasta", "siedemnasta", "osiemnasta", "dziewiętnasta", "dwudziesta", "dwudziesta pierwsza", "dwudziesta druga", "dwudziesta trzecia",
]


def _hour_genitive(word: str) -> str:
    """"siódma" -> "siódmej", "druga" -> "drugiej", "północ" -> "północy" (the form after o / od / do / po / przed)."""
    if word == "północ":
        return "północy"
    if word.endswith("ga"):
        return word[:-2] + "giej"
    return word[:-1] + "ej" if word.endswith("a") else word

# unit abbreviation -> (one, few, many, other[=genitive singular for decimals])
_UNIT_FORMS: dict[str, tuple[str, str, str, str]] = {
    "g": ("gram", "gramy", "gramów", "grama"),
    "kg": ("kilogram", "kilogramy", "kilogramów", "kilograma"),
    "ml": ("mililitr", "mililitry", "mililitrów", "mililitra"),
    "l": ("litr", "litry", "litrów", "litra"),
    "s": ("sekunda", "sekundy", "sekund", "sekundy"),
    "sek": ("sekunda", "sekundy", "sekund", "sekundy"),
    "min": ("minuta", "minuty", "minut", "minuty"),
    "h": ("godzina", "godziny", "godzin", "godziny"),
    "godz": ("godzina", "godziny", "godzin", "godziny"),
    "szt": ("sztuka", "sztuki", "sztuk", "sztuki"),
    "m": ("metr", "metry", "metrów", "metra"),
    "cm": ("centymetr", "centymetry", "centymetrów", "centymetra"),
    "km": ("kilometr", "kilometry", "kilometrów", "kilometra"),
    "tys": ("tysiąc", "tysiące", "tysięcy", "tysiąca"),
    "mln": ("milion", "miliony", "milionów", "miliona"),
    "mld": ("miliard", "miliardy", "miliardów", "miliarda"),
}
_CURRENCIES: dict[str, tuple[tuple[str, str, str, str], tuple[str, str, str]]] = {
    "zł": (("złoty", "złote", "złotych", "złotego"), ("grosz", "grosze", "groszy")),
    "pln": (("złoty", "złote", "złotych", "złotego"), ("grosz", "grosze", "groszy")),
    "usd": (("dolar", "dolary", "dolarów", "dolara"), ("cent", "centy", "centów")),
    "$": (("dolar", "dolary", "dolarów", "dolara"), ("cent", "centy", "centów")),
    "eur": (("euro", "euro", "euro", "euro"), ("cent", "centy", "centów")),
    "€": (("euro", "euro", "euro", "euro"), ("cent", "centy", "centów")),
}
_ABBREVIATIONS = [
    (r"\bnp\.", "na przykład"), (r"\bok\.(?=\s*\d)", "około"), (r"\bm\.in\.", "między innymi"), (r"\bitd\.", "i tak dalej"), (r"\bitp\.", "i tym podobne"),
    (r"\btzw\.", "tak zwany"), (r"\btj\.", "to jest"), (r"\bul\.", "ulica"), (r"\bal\.", "aleja"), (r"\bpl\.", "plac"), (r"\bnr\s*(?=\d)", "numer "), (r"#\s*(?=\d)", "numer "),
    (r"\btel\.\s*", "telefon "), (r"\bprof\.\s*", "profesor "), (r"(?-i:\bdr\s+(?=[A-ZŁŚŻŹĆŃÓ]))", "doktor "), (r"\bgodz\.\s*(?=\d{1,2}:\d{2})", "godzina "),
    (r"\bsp\.\s*z\s*o\.\s*o\.?", "spółka z ograniczoną odpowiedzialnością"), (r"(?-i:\bS\.\s?A\.)", "spółka akcyjna"),
    (r"&", " i "), (r"\+(?=\s*\d)", " plus "), (r"@", " małpa "), (r"(?:(?<=\s)|^)[-\u2212](?=\d)", "minus "),  # "-50%" / "−5 °C" -> "minus …"; "5-10 minut" is a range, not a minus
]
_NUM = r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
# "ul. Długa" is "ulica Długa", but "przy ul. Długiej" is "przy ulicy Długiej": the case of the street type follows the name after it
_STREET_TYPE = re.compile(r"\b(ul|al|pl)\.\s*(?=([^\W\d_]+))", re.IGNORECASE)


def _street_type_words(m: re.Match[str]) -> str:
    kind, name = m.group(1).lower(), m.group(2).lower()
    if kind == "ul":
        return "ulicy " if name.endswith("ej") else "ulica "
    if kind == "al":
        return "alei " if name.endswith("ej") else "aleja "
    return "placu " if name.endswith(("ym", "im", "ego")) else "plac "


def _parse_number(s: str) -> tuple[int, str]:
    """'1 234,56' -> (1234, '56'); '379.00' -> (379, '00')."""
    s = s.replace(" ", "").replace(NBSP, "").replace("\u202f", "")
    whole, _, frac = s.replace(",", ".").partition(".")
    return int(whole), frac


def number_words(s: str) -> str:
    """A written number (``1 234``, ``12,5``) read as Polish words ("dwanaście przecinek pięć")."""
    whole, frac = _parse_number(s)
    out = cardinal(whole)
    if frac.strip("0"):
        out += " przecinek " + " ".join(cardinal(int(d)) for d in frac)
    return out


_FEMININE_UNITS = {"s", "sek", "min", "h", "godz", "szt"}  # sekunda, minuta, godzina, sztuka


def _unit_phrase(num: str, unit: str, gen: bool = False) -> str:
    whole, frac = _parse_number(num)
    key = unit.lower().rstrip(".")
    forms = _UNIT_FORMS[key]
    one, few, many, other = forms
    if gen and not frac.strip("0"):  # after od / do / bez / dla: "od 250 g" -> "od dwustu pięćdziesięciu gramów"
        return f"{genitive(cardinal(whole, feminine=key in _FEMININE_UNITS))} {other if whole == 1 else many}"
    word = other if frac.strip("0") else plural_form(whole, one, few, many)
    if key in _FEMININE_UNITS and not frac.strip("0"):
        return f"{cardinal(whole, feminine=True)} {word}"
    return f"{number_words(num)} {word}"


def _money_phrase(num: str, cur: str, gen: bool = False) -> str:
    whole, frac = _parse_number(num)
    (z_one, z_few, z_many, z_other), (g_one, g_few, g_many) = _CURRENCIES[cur.lower()]
    grosze = int((frac + "00")[:2]) if frac else 0
    if gen:  # "od 39,99 zł" -> "od trzydziestu dziewięciu złotych dziewięćdziesięciu dziewięciu groszy"
        main = f"{genitive(cardinal(whole))} {z_other if whole == 1 else z_many}"
        if grosze:
            main += f" {genitive(cardinal(grosze))} {g_one + 'a' if grosze == 1 else g_many}"
        return main
    if cur.lower() in {"eur", "€"}:
        main = f"{cardinal(whole)} euro"
    else:
        main = f"{cardinal(whole)} {plural_form(whole, z_one, z_few, z_many)}"
    if grosze:
        sub = f"{cardinal(grosze)} {plural_form(grosze, g_one, g_few, g_many)}"
        return f"{main} {sub}"
    return main


_UNIT_ALT_MULTI = "|".join(sorted((re.escape(u) for u in _UNIT_FORMS if len(u) > 1), key=len, reverse=True))
_UNIT_ALT_SINGLE = "".join(u for u in _UNIT_FORMS if len(u) == 1)  # g l m s h — lower case only: "5G", "3D" and "4K" are not units
_UNIT_RX = re.compile(rf"(?<![\w])({_NUM})\s*((?i:{_UNIT_ALT_MULTI})|[{_UNIT_ALT_SINGLE}])\b\.?")
_NOT_AMOUNT = r"(?!\s*(?:zł|zl|pln|eur|usd|%|k?g\b|ml\b|l\b|szt|tys|mln|mld|min|godz|cm|km))"
# phone numbers are read digit by digit in their groups ("600 123 456" would be six hundred million …); the country code as a number
_PHONE = re.compile(
    rf"(?<![\w.,/-])(?:(?:\+|00)\s?(?P<cc>\d{{2}})[\s-]?)?(?P<num>\d{{3}}[\s-]\d{{3}}[\s-]\d{{3}}|\d{{2}}[\s-]\d{{3}}[\s-]\d{{2}}[\s-]\d{{2}}|\(\d{{2}}\)\s?\d{{3}}[\s-]\d{{2}}[\s-]\d{{2}})(?!\d){_NOT_AMOUNT}",
    re.IGNORECASE,
)
_POSTAL = re.compile(rf"(?<![\w-])(\d{{2}})-(\d{{3}})(?![\w-]){_NOT_AMOUNT}")
_SLASH = re.compile(r"(?<![\w/])(\d+)/(\d+)(?:\s*(kg|g|l|ml)\b)?(?![\w/])")
_STREET = re.compile(r"\b(?:ulic[ay]|aleja|alei|plac|placu|osiedle)\b[^.!?]{0,40}$", re.IGNORECASE)
_FRACTIONS = {(1, 2): "pół", (1, 4): "jedna czwarta", (3, 4): "trzy czwarte"}
_YEAR = re.compile(r"\b(?:(?P<prep>w|od|do|z|po|przed|na|o|za)\s+)?(?P<y>(?:19|20)\d{2})\s*(?:roku\b|r\b\.?)", re.IGNORECASE)
_YEAR_CASE = {"w": "loc", "po": "loc", "na": "loc", "o": "loc", "od": "gen", "do": "gen", "z": "gen", "przed": "ins", "za": "ins"}
_ORDINAL_NOUN = re.compile(r"(?<![\w.,])(\d{1,2})\.\s+(miejsce|edycja|rocznica|dzień|wydanie|część|sezon|krok|etap|poziom|nagroda|partia)\b", re.IGNORECASE)
_NOUN_GENDER = {"miejsce": "n", "edycja": "f", "rocznica": "f", "dzień": "m", "wydanie": "n", "część": "f", "sezon": "m", "krok": "m", "etap": "m", "poziom": "m", "nagroda": "f", "partia": "f"}
_CLOCK = re.compile(r"(?:(?P<prep>\b(?:o|od|do|po|przed|około|na|przez|koło|za)\s+))?\b(?P<h>[01]?\d|2[0-3]):(?P<m>[0-5]\d)\b", re.IGNORECASE)
# prepositions that only take the genitive: the numeral after them is genitive too ("od 39 zł" -> "od trzydziestu dziewięciu złotych"); "z" and "ponad" are left out (instrumental / either case)
_GENITIVE_PREP = re.compile(r"\b(?:od|do|bez|dla|poniżej|powyżej)\s+(?:(?:już|aż|niecałe|prawie|ponad|około|blisko)\s+)?$", re.IGNORECASE)


def _genitive_slot(text: str, pos: int) -> bool:
    return _GENITIVE_PREP.search(text[:pos]) is not None


def _digits(group: str) -> str:
    return " ".join(_UNITS[int(d)] for d in group if d.isdigit())


def _phone_words(m: re.Match[str]) -> str:
    groups = [_digits(g) for g in re.split(r"[\s()-]+", m.group("num")) if g]
    prefix = f"plus {cardinal(int(m.group('cc')))}, " if m.group("cc") else ""
    return prefix + ", ".join(groups)


def _postal_words(m: re.Match[str]) -> str:
    head = _digits(m.group(1)) if m.group(1).startswith("0") else cardinal(int(m.group(1)))
    return f"{head}, {_digits(m.group(2))}"


def _slash_words(m: re.Match[str], before: str) -> str:
    a, b, unit = int(m.group(1)), int(m.group(2)), m.group(3)
    if (a, b) in _FRACTIONS:
        word = _FRACTIONS[(a, b)]
        return f"{word} {_UNIT_FORMS[unit][3]}" if unit else word
    link = "łamane przez" if _STREET.search(before) else "na"  # "ul. Długa 5/12" is "pięć łamane przez dwanaście"; "24/7" and "50/50" are "na"
    return f"{m.group(1)} {link} {m.group(2)}" + (f" {unit}" if unit else "")


def _year_words(m: re.Match[str]) -> str:
    case = _YEAR_CASE.get((m.group("prep") or "").lower(), "nom")
    noun = {"gen": "roku", "loc": "roku", "ins": "rokiem", "nom": "rok"}[case]
    return (m.group("prep") + " " if m.group("prep") else "") + f"{ordinal_case(int(m.group('y')), case)} {noun}"


def tts_text(text: str) -> str:
    """Polish voice-over text prepared for speech synthesis: numbers, units, currencies, percents, times, dates, years, phone numbers, postal codes and URLs in words."""
    t = text.replace(NBSP, " ").replace("\u202f", " ")
    t = _PHONE.sub(_phone_words, t)
    t = _POSTAL.sub(_postal_words, t)
    t = _STREET_TYPE.sub(_street_type_words, t)
    t = re.sub(r"\b(czynne|otwarte|godz\.?|godzinach)(\s+)od\s+(\d{1,2})\s+do\s+(\d{1,2})\b(?![:.,]?\d)", lambda m: f"{m.group(1)}{m.group(2)}od {m.group(3)}:00 do {m.group(4)}:00" if int(m.group(3)) < 24 and int(m.group(4)) < 24 else m.group(0), t, flags=re.IGNORECASE)  # "czynne od 7 do 19": opening hours
    t = re.sub(r"(?<![\w.,:/-])(\d{1,3})\s*[-\u2013]\s*(\d{1,3})(?![\w.,:/-])", r"\1 do \2", t)  # "5-10 minut" -> "5 do 10 minut" -> "pięć do dziesięciu minut"
    for pat, repl in _ABBREVIATIONS:
        t = re.sub(pat, repl, t, flags=re.IGNORECASE)
    # dates: 12.01.2027 / 12 stycznia 2027 / 12. stycznia 2027 r. (before URLs, which also contain dots)
    t = re.sub(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s*r\b\.?|\s+roku\b)?", lambda m: f"{ordinal_genitive(int(m.group(1)))} {_MONTHS_GEN[int(m.group(2)) - 1]} {ordinal_genitive(int(m.group(3)))} roku" if 1 <= int(m.group(2)) <= 12 else m.group(0), t)
    t = re.sub(rf"\b(\d{{1,2}})\.?\s+({'|'.join(_MONTHS_GEN)})(?:\s+(\d{{4}})(?:\s*r\b\.?|\s+roku\b)?)?", lambda m: f"{ordinal_genitive(int(m.group(1)))} {m.group(2)}" + (f" {ordinal_genitive(int(m.group(3)))} roku" if m.group(3) else ""), t)
    t = _YEAR.sub(_year_words, t)  # "w 2026 r." -> "w dwa tysiące dwudziestym szóstym roku"
    t = _ORDINAL_NOUN.sub(lambda m: f"{ordinal_nominative(int(m.group(1)), _NOUN_GENDER[m.group(2).lower()])} {m.group(2)}", t)  # "3. miejsce" -> "trzecie miejsce"
    # URLs / domains: "northwind.example/dawn-roast" -> "northwind kropka example ukośnik dawn myślnik roast"
    t = re.sub(
        r"\b(?:https?://)?(?=[\w.-]*[a-z])([a-z0-9-]+(?:\.[a-z0-9-]+)+)(/[\w\-./]*)?",
        lambda m: re.sub(r"[./-]", lambda c: {".": " kropka ", "/": " ukośnik ", "-": " myślnik "}[str(c.group(0))], str(m.group(0)).removeprefix("https://").removeprefix("http://")),
        t,
        flags=re.IGNORECASE,
    )
    # clock times: "4:45" -> "czwarta czterdzieści pięć"; after o / od / do / po / przed: "o czwartej czterdzieści pięć"; "7:00-19:00" -> "od siódmej do dziewiętnastej"
    t = re.sub(r"(?<![\w:])(\d{1,2}:\d{2})\s*[-\u2013]\s*(\d{1,2}:\d{2})(?![\w:])", lambda m: ("" if re.search(r"\bod\s+$", t[: m.start()], re.IGNORECASE) else "od ") + f"{m.group(1)} do {m.group(2)}", t)
    t = _CLOCK.sub(lambda m: (m.group("prep") or "") + _time_words(int(m.group("h")), int(m.group("m")), genitive=bool(m.group("prep"))), t)
    t = _SLASH.sub(lambda m: _slash_words(m, t[: m.start()]), t)
    # money in thousands / millions: 120 tys. zł -> sto dwadzieścia tysięcy złotych (the unit step below would leave "zł" unread)
    t = re.sub(rf"({_NUM})\s*(tys\.|mln|mld)\s*(zł|PLN)\b", lambda m: f"{_unit_phrase(m.group(1), m.group(2), _genitive_slot(t, m.start()))} złotych", t, flags=re.IGNORECASE)
    # money: 379,00 zł / 9,99 PLN / $5
    t = re.sub(rf"({_NUM})\s*(zł|PLN|USD|EUR|€)\b", lambda m: _money_phrase(m.group(1), m.group(2), _genitive_slot(t, m.start())), t, flags=re.IGNORECASE)
    t = re.sub(rf"([$€])\s*({_NUM})", lambda m: _money_phrase(m.group(2), m.group(1), _genitive_slot(t, m.start())), t)
    # percents: 100% -> sto procent, 12,5 % -> dwanaście przecinek pięć procent
    t = re.sub(rf"({_NUM})\s*(?:%|proc\.|procent\w*)", lambda m: f"{_number_in_slot(m.group(1), _genitive_slot(t, m.start()))} procent", t)
    # degrees: 93 °C -> dziewięćdziesiąt trzy stopnie Celsjusza
    t = re.sub(r"(?<![\w])(\d+)\s*°\s*C\b", lambda m: f"{cardinal(int(m.group(1)))} {plural_form(int(m.group(1)), 'stopień', 'stopnie', 'stopni')} Celsjusza", t)
    # number + unit: 340 g -> trzysta czterdzieści gramów
    t = _UNIT_RX.sub(lambda m: _unit_phrase(m.group(1), m.group(2), _genitive_slot(t, m.start())), t)
    # number + feminine noun written in full: 2 sekundy -> dwie sekundy, 1 kawa -> jedna kawa
    t = re.sub(rf"({_NUM})(\s+(?:{_FEMININE_NOUN_STEMS})\w*)", lambda m: _feminine_number(m.group(1), _genitive_slot(t, m.start())) + m.group(2), t, flags=re.IGNORECASE)
    # remaining plain numbers (a number glued to letters — "A4", "3D" — is a name, not a quantity)
    t = re.sub(rf"(?<![\w])(?:{_NUM})(?![\w])", lambda m: _number_in_slot(m.group(0), _genitive_slot(t, m.start())), t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _number_in_slot(num: str, gen: bool) -> str:
    whole, frac = _parse_number(num)
    return genitive(cardinal(whole)) if gen and not frac.strip("0") else number_words(num)


_FEMININE_NOUN_STEMS = (
    "sekund|minut|godzin|sztuk|osob|parti|torb|puszk|filiżank|szklank|łyżeczk|łyżk|porcj|chwil|kaw|noc|plantacj|palarni|butelk|paczk|kapsułk|saszetk|kawiarni|herbat|dostaw|receptur|mieszank|zniżk|promocj|wizyt|rocznic|edycj|nagrod"
)


def _feminine_number(num: str, gen: bool = False) -> str:
    whole, frac = _parse_number(num)
    if frac.strip("0"):
        return number_words(num)
    return genitive(cardinal(whole, feminine=True)) if gen else cardinal(whole, feminine=True)


def _time_words(h: int, m: int, genitive: bool = False) -> str:
    """4:45 -> "czwarta czterdzieści pięć"; with genitive=True (after o / od / do / po / przed): "czwartej czterdzieści pięć"."""
    base = _hour_genitive_words(_HOURS_ORD[h]) if genitive else _HOURS_ORD[h]
    if m == 0:
        return base
    return f"{base} {'zero ' + cardinal(m) if m < 10 else cardinal(m)}"


def _hour_genitive_words(phrase: str) -> str:
    return " ".join(_hour_genitive(w) for w in phrase.split())


# ----------------------------------------------------------------------------------------------- typography (captions, supers, legal)

_ORPHANS = re.compile(r"(?<![\w])([aiouwzAIOUWZ])[ ](?=\S)")
_NUMBER_UNIT = re.compile(r"(?<=\d) (?=(?:zł|PLN|USD|EUR|€|\$|%|g|kg|ml|l|s|min|godz\.|szt\.|cm|m|km|tys\.|mln|mld)(?![\w]))")
_THOUSANDS = re.compile(r"(?<=\d) (?=\d{3}(?!\d))")  # "120 000 zł": a grouped number never breaks across two lines
# abbreviations stay with what they introduce: "tel. 600 100 200", "nr 5", "godz. 7:00", "ok. 200 g", "ul. Długa", "dr Anna", "prof. Kowalski", and a year with its "r."
_GLUE_BEFORE_NUMBER = re.compile(r"(?<![\w.])(?:[Nn]r|[Tt]el\.|[Gg]odz\.|ok\.) (?=\d)")
_GLUE_BEFORE_NAME = re.compile(r"(?<![\w.])(?:(?:[Uu]l|[Aa]l|[Pp]l|[Oo]s|[Ii]m|[Kk]s|[Pp]rof|[Ii]nż|św)\.|[Dd]r\.?|[Mm]gr\.?) (?=[A-ZĄĆĘŁŃÓŚŹŻ])")
_YEAR_ABBREVIATION = re.compile(r"(?<=\d) (?=r\.(?!\w))")
PROTECTED_PHRASES = ("Dawn Roast", "Midnight Blend", "Cold Brew", "Northwind Coffee Roasters")  # product / brand names never break across lines


def typeset(text: str) -> str:
    """Polish typography: NBSP after single-letter words, between number and unit, and inside brand names — never a widow at a line end."""
    t = text
    for phrase in PROTECTED_PHRASES:
        t = t.replace(phrase, phrase.replace(" ", NBSP))
    t = _ORPHANS.sub(lambda m: m.group(1) + NBSP, t)
    t = _ORPHANS.sub(lambda m: m.group(1) + NBSP, t)  # a second pass handles "i w z" runs
    t = _THOUSANDS.sub(NBSP, t)
    for glue in (_GLUE_BEFORE_NUMBER, _GLUE_BEFORE_NAME):
        t = glue.sub(lambda m: m.group(0).replace(" ", NBSP), t)
    t = _YEAR_ABBREVIATION.sub(NBSP, t)
    return _NUMBER_UNIT.sub(NBSP, t)


def typeset_for(text: str, lang: str) -> str:
    return typeset(text) if lang == "pl" else text


def spoken_text(text: str, lang: str, pronunciations: dict[str, str] | None = None) -> str:
    """Text as sent to the speech engine. Polish gets the brand's pronunciation respellings ("Dawn Roast" -> "dołn rołst") and numbers, units,
    currencies, percents, dates and URLs in words; captions and supers keep the original wording. Other languages are passed through."""
    if lang != "pl":
        return text
    out = text
    for term, say in (pronunciations or {}).items():
        out = re.sub(rf"(?<!\w){re.escape(term)}(?!\w)", say, out)
    return tts_text(out)
