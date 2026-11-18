"""PII / PCI redaction (deterministic rules, Luhn / IBAN mod-97 validated). Used for transcripts, logs, audit and LLM context.

Card data must never reach the LLM, transcripts or logs: `redact()` is applied before anything is stored, logged or sent."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "for": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9",
    "null": "0", "eins": "1", "ein": "1", "zwei": "2", "drei": "3", "vier": "4", "fünf": "5", "fuenf": "5",
    "sechs": "6", "sieben": "7", "acht": "8", "neun": "9",
    "jeden": "1", "jedna": "1", "dwa": "2", "dwie": "2", "trzy": "3", "cztery": "4", "pięć": "5", "piec": "5", "sześć": "6", "szesc": "6",
    "siedem": "7", "osiem": "8", "dziewięć": "9", "dziewiec": "9",
}  # fmt: skip
# Polish number words read out as groups ("sześćset jeden dwa trzy ..." = 600 1 2 3 ..., "dwadzieścia trzy" = 23): teens (2 digits), tens (2 digits, merged with a following unit), hundreds (3 digits)
_PL_TEENS = {
    "dziesięć": "10", "dziesiec": "10", "jedenaście": "11", "jedenascie": "11", "dwanaście": "12", "dwanascie": "12", "trzynaście": "13", "trzynascie": "13", "czternaście": "14", "czternascie": "14",
    "piętnaście": "15", "pietnascie": "15", "szesnaście": "16", "szesnascie": "16", "siedemnaście": "17", "siedemnascie": "17", "osiemnaście": "18", "osiemnascie": "18", "dziewiętnaście": "19", "dziewietnascie": "19",
}  # fmt: skip
_PL_TENS = {
    "dwadzieścia": "2", "dwadziescia": "2", "trzydzieści": "3", "trzydziesci": "3", "czterdzieści": "4", "czterdziesci": "4", "pięćdziesiąt": "5", "piecdziesiat": "5",
    "sześćdziesiąt": "6", "szescdziesiat": "6", "siedemdziesiąt": "7", "siedemdziesiat": "7", "osiemdziesiąt": "8", "osiemdziesiat": "8", "dziewięćdziesiąt": "9", "dziewiecdziesiat": "9",
}  # fmt: skip
_PL_HUNDREDS = {
    "sto": "1", "dwieście": "2", "dwiescie": "2", "trzysta": "3", "czterysta": "4", "pięćset": "5", "piecset": "5", "sześćset": "6", "szescset": "6",
    "siedemset": "7", "osiemset": "8", "dziewięćset": "9", "dziewiecset": "9",
}  # fmt: skip
_SPOKEN_WORDS = "|".join(sorted({*_DIGIT_WORDS, *_PL_TEENS, *_PL_TENS, *_PL_HUNDREDS}, key=len, reverse=True)).replace("ü", "[uü]e?").replace("fünf", "f[uü]e?nf")

_SP = " \u00a0\u202f"  # space, no-break space, narrow no-break space (what a copy from a web page / e-banking brings along)
_CARD = re.compile(rf"(?<![\w-])(?:\d[{_SP}.-]?){{12,18}}\d(?![\w-])")
_IBAN = re.compile(rf"\b(?i:[A-Z]{{2}})\d{{2}}(?:[{_SP}]?[A-Z0-9]{{2,4}}){{3,8}}\b")  # the country code may be typed in lower case ("pl61 1090 ..."), the account part may not: it would run on into the next word
_EMAIL = re.compile(r"(?<![\w.%+-])[\w.%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")  # the look-behind keeps the scan linear on a long run of word characters
_EMAIL_SPOKEN = re.compile(r"(?i)(?<![\w.%+-])[\w.%+-]+\s*(?:\(at\)|\[at\]|\bma[łl]pa\b)\s*[\w-]+(?:\s*(?:\(dot\)|\[dot\]|\bkropka\b|\.)\s*[\w-]+)+")  # "anna.kowalska małpa example kropka pl"
_PHONE = re.compile(r"(?<![\w-])(?:\+|00)\d[\d ()./-]{7,17}\d(?![\w-])|(?<![\w+-])0\d{2,4}[ /-]?\d{3,}[ /-]?\d{2,}(?![\w-])|(?<![\w+-])\(0\d{2,5}\)[ /.-]?\d[\d .-]{4,12}\d(?![\w-])")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_NI = re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b")
_CVV = re.compile(
    r"\b(?:cvv2?|cvc2?|security code|sicherheitscode|prüfziffer|pruefziffer|kod bezpiecze[ńn]stwa|kod zabezpieczaj[ąa]cy|kod z ty[łl]u|(?:trzy|3)\s+cyfry\s+z\s+ty[łl]u(?:\s+karty)?)\D{0,6}(\d{3,4})\b",
    re.IGNORECASE,
)
_BLIK = re.compile(r"\bblik\w*\D{0,12}(\d{3}[ \u00a0-]?\d{3})\b", re.IGNORECASE)  # a BLIK code is a one-time payment secret, handled like the CVV
_POLISH_DIGIT_WORD = re.compile(r"(?i)\b(?:jeden|jedna|dwa|dwie|trzy|cztery|pi[eę][cć]|sze[sś][cć]|siedem|osiem|dziewi[eę][cć]|sto|dwie[sś]cie|trzysta|czterysta|pi[eę][cć]set|sze[sś][cć]set|siedemset|osiemset|dziewi[eę][cć]set)\b")
_SPOKEN = re.compile(rf"(?i)(?<![\w])(?:(?:{_SPOKEN_WORDS})[\s,.-]+){{3,}}(?:{_SPOKEN_WORDS})(?![\w])")

# ---- Polish identifiers (every checksum-bearing one is validated; an invalid checksum is NOT redacted as that type). A number that follows its own keyword
# ("PESEL 90051412346", "NIP: 526...", "konto 61 ...") but fails the checksum is still redacted - as `ID_NUMBER`: a mistyped PESEL is as sensitive as a correct one.
_KW_GAP = r"(?:[\s:.,;#-]+(?:to|jest|nr|numer\w*|no|is|number|wynosi|brzmi)){0,3}[\s:.,;#-]{0,4}"  # "PESEL to 900...", "NIP: 526...", "REGON firmy to ..."
_PESEL = re.compile(rf"(?<!\d)((?:\d[{_SP}-]?){{10}}\d)(?!\d)")
_PESEL_KEYWORD = re.compile(rf"\bPESEL\b{_KW_GAP}(\d(?:[{_SP}-]?\d){{9,11}})(?!\d)", re.IGNORECASE)
_NIP_FORMATTED = re.compile(rf"(?<![\w-])(?:PL[{_SP}]?)?(\d{{3}}-\d{{3}}-\d{{2}}-\d{{2}}|\d{{3}}-\d{{2}}-\d{{2}}-\d{{3}}|\d{{3}}[{_SP}]\d{{3}}[{_SP}]\d{{2}}[{_SP}]\d{{2}})(?![\w-])", re.IGNORECASE)
_NIP_KEYWORD = re.compile(rf"\b(?:NIP|VAT[ -]?ID|numer\s+identyfikacji\s+podatkowej|identyfikator\s+podatkowy)\b{_KW_GAP}(?:PL[{_SP}]?)?(\d[\d{_SP}-]{{7,14}}\d)(?!\d)", re.IGNORECASE)
_NIP_PREFIXED = re.compile(rf"(?<![\w-])PL[{_SP}]?(\d{{10}})(?![\w-])", re.IGNORECASE)
_REGON = re.compile(rf"\bREGON\w*\b{_KW_GAP}(\d[\d{_SP}-]{{6,16}}\d)(?!\d)", re.IGNORECASE)
_ID_CARD = re.compile(r"(?<![A-Za-z0-9])([A-Z]{3})[ -]?(\d{6})(?!\d)")  # capitals only: a lower-case 3-letter word + 6 digits is usually an OTP ("kod 482913")
_ID_CARD_KEYWORD = re.compile(
    rf"\b(?P<kw>dow[oó]d\w*\s+(?:osobist\w+|to[żz]samo[śs]ci)|(?:numer|nr)\s+dow[oó]d\w*|seri\w+\s+(?:i\s+)?(?:numer|nr)\w*(?:\s+dow[oó]d\w*)?|dow[oó]d\w*(?!\s+(?:zakup|wp[łl]at|sprzeda|dostaw)))"
    rf"[^\d\n]{{0,25}}?\b(?!kod\b|tel\b|pin\b|ref\b)(?P<letters>[A-Za-z]{{3}})[{_SP}-]?(?:(?:nr|numer)\.?\s*)?(?P<digits>\d{{6}})(?!\d)",
    re.IGNORECASE,
)
_PASSPORT = re.compile(
    rf"\b(?:paszport\w*|passport\w*)(?:[\s:.,;#-]+(?:nr|numer\w*|no|number|to|jest|is|seria|serii|i|oraz|ma|miał\w*)){{0,4}}[\s:.,;#-]{{0,6}}([A-Z]{{2}}[{_SP}-]?\d{{7}})(?![\w])", re.IGNORECASE
)  # the series/number has no public checksum we can rely on: the keyword is the evidence ("paszport nr EB 1234567", "my passport is ZS7654321")
_NRB = re.compile(rf"(?<![\w-])(?:PL[{_SP}]?)?((?:\d[{_SP}-]?){{25}}\d)(?![\w-])", re.IGNORECASE)
_NRB_KEYWORD = re.compile(rf"\b(?:konto|konta|kontem|rachun\w+|nrb|iban)\b[^\d\n]{{0,25}}((?:\d[{_SP}-]?){{23,27}}\d)(?!\d)", re.IGNORECASE)
_PL_RUN = re.compile(rf"(?<![\w+\-])(?<!\d[.,])[+(]?\d[\d(){_SP}.\-]{{6,30}}\d(?![\w\-])(?![.,]\d)")  # a run of digits and separators: windows of it are tested as Polish phone numbers
_PL_MOBILE = re.compile(r"[4-8]\d{8}")
_PL_LANDLINE = re.compile(r"(?:1[2-8]|2[2-59]|3[2-4]|4[1-48]|5[2-9]|6[1-8]|7[1-7]|8[1-9]|9[1-5])\d{7}")  # 600 123 456 / 22 555 01 66 / (22) 555-01-66 / +48 ... / 0048 ... / 022 ...


@dataclass
class Finding:
    kind: str
    start: int
    end: int


@dataclass
class Redaction:
    text: str
    findings: list[Finding]

    @property
    def kinds(self) -> set[str]:
        return {f.kind for f in self.findings}

    def has(self, kind: str) -> bool:
        return kind in self.kinds


def luhn_ok(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def iban_ok(value: str) -> bool:
    v = re.sub(r"\s+", "", value).upper()
    if not 15 <= len(v) <= 34 or not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", v):
        return False
    rearranged = v[4:] + v[:4]
    num = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(num) % 97 == 1


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def pesel_ok(value: str, today: date | None = None) -> bool:
    """11 digits, weighted checksum (1,3,7,9,...) and a plausible birth date encoded in YYMMDD (month offset = century: +0 1900s, +20 2000s, +40 2100s, +60 2200s, +80 1800s)."""
    d = _digits(value)
    if len(d) != 11:
        return False
    if (10 - sum(int(a) * w for a, w in zip(d[:10], (1, 3, 7, 9, 1, 3, 7, 9, 1, 3), strict=True)) % 10) % 10 != int(d[10]):
        return False
    yy, mm, dd = int(d[0:2]), int(d[2:4]), int(d[4:6])
    century = {0: 1900, 1: 2000, 2: 2100, 3: 2200, 4: 1800}.get(mm // 20)
    if century is None:
        return False
    try:
        born = date(century + yy, mm % 20, dd)
    except ValueError:
        return False
    today = today or datetime.now(UTC).date()
    return date(1900, 1, 1) <= born <= today


def nip_ok(value: str) -> bool:
    d = _digits(value)
    if len(d) != 10:
        return False
    c = sum(int(a) * w for a, w in zip(d[:9], (6, 5, 7, 2, 3, 4, 5, 6, 7), strict=True)) % 11
    return c != 10 and c == int(d[9])


def regon_ok(value: str) -> bool:
    """REGON-9 (weights 8,9,2,3,4,5,6,7) or REGON-14 (its first nine digits are a valid REGON-9; weights 2,4,8,5,0,9,7,3,6,1,2,4,8)."""
    d = _digits(value)
    if len(d) not in (9, 14):
        return False
    weights = (8, 9, 2, 3, 4, 5, 6, 7) if len(d) == 9 else (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8)
    c = sum(int(a) * w for a, w in zip(d[:-1], weights, strict=True)) % 11
    if (0 if c == 10 else c) != int(d[-1]):
        return False
    return len(d) == 9 or regon_ok(d[:9])


def id_card_ok(letters: str, digits: str) -> bool:
    """Polish identity card `ABC 123456`: letters count as 10..35, weights 7,3,1,9,7,3,1,7,3, the weighted sum must be divisible by 10 (the 9 sits on the check digit)."""
    if len(letters) != 3 or len(digits) != 6:
        return False
    vals = [ord(c.upper()) - 55 for c in letters] + [int(c) for c in digits]
    return sum(v * w for v, w in zip(vals, (7, 3, 1, 9, 7, 3, 1, 7, 3), strict=True)) % 10 == 0


def nrb_ok(value: str) -> bool:
    d = _digits(value)
    return len(d) == 26 and iban_ok("PL" + d)


def _below_100(tokens: list[str], i: int) -> tuple[str | None, int]:
    """Digits of the number word(s) at `tokens[i]`: teen (2 digits), tens (+ a following unit = 2 digits), unit (1 digit)."""
    t = tokens[i]
    if t in _PL_TEENS:
        return _PL_TEENS[t], i + 1
    if t in _PL_TENS:
        if i + 1 < len(tokens) and tokens[i + 1] in _DIGIT_WORDS and _DIGIT_WORDS[tokens[i + 1]] != "0":
            return _PL_TENS[t] + _DIGIT_WORDS[tokens[i + 1]], i + 2
        return _PL_TENS[t] + "0", i + 1
    if t in _DIGIT_WORDS:
        return _DIGIT_WORDS[t], i + 1
    return None, i


def _decode_spoken(tokens: list[str], group_hundreds: bool) -> str:
    out, i = "", 0
    while i < len(tokens):
        t = tokens[i]
        if t in _PL_HUNDREDS:
            if group_hundreds and i + 1 < len(tokens):  # "sto dwadzieścia trzy" = 123
                rest, nxt = _below_100(tokens, i + 1)
                if rest is not None:
                    out += _PL_HUNDREDS[t] + rest.zfill(2)
                    i = nxt
                    continue
            out += _PL_HUNDREDS[t] + "00"  # "sześćset jeden dwa trzy ..." = 600 1 2 3 ...
            i += 1
            continue
        digits, nxt = _below_100(tokens, i)
        if digits is None:
            i += 1
            continue
        out += digits
        i = nxt
    return out


def _spoken_digits(chunk: str) -> list[str]:
    """Every plausible reading of a run of number words as a digit string (a Polish number is read digit by digit, in pairs or in groups of three: both readings are tried)."""
    tokens = [w.lower() for w in re.findall(r"[A-Za-zÀ-ž]+", chunk)]
    readings = [_decode_spoken(tokens, False), _decode_spoken(tokens, True)]
    return list(dict.fromkeys(readings))


def _pl_phone_ok(d: str) -> bool:
    """9 digits of a Polish mobile (4xx-8xx) or landline (area code + 7 digits), optionally with the old trunk `0`, `48` or `0048` in front."""
    if len(d) == 13 and d.startswith("0048"):
        d = d[4:]
    elif len(d) == 11 and d.startswith("48"):
        d = d[2:]
    elif len(d) == 10 and d.startswith("0"):
        d = d[1:]
    return len(d) == 9 and bool(_PL_MOBILE.fullmatch(d) or _PL_LANDLINE.fullmatch(d))


def _pl_phone_spans(text: str) -> list[Finding]:
    out: list[Finding] = []
    for run in _PL_RUN.finditer(text):
        groups = [(g.start(), g.end(), g.group()) for g in re.finditer(r"\d+", run.group())]
        i = 0
        while i < len(groups):
            digits, hit = "", None
            for j in range(i, len(groups)):
                digits += groups[j][2]
                if len(digits) > 13:
                    break
                if _pl_phone_ok(digits):
                    hit = j  # the longest valid window that starts here
            if hit is None:
                i += 1
                continue
            start, end = run.start() + groups[i][0], run.start() + groups[hit][1]
            while start > 0 and text[start - 1] in "+(":
                start -= 1
            out.append(Finding("PHONE", start, end))
            i = hit + 1
    return out


def _card_spans(text: str) -> list[Finding]:
    out: list[Finding] = []
    for m in _CARD.finditer(text):
        if luhn_ok(m.group()):
            out.append(Finding("CARD", m.start(), m.end()))
            continue
        groups = [(g.start(), g.end(), g.group()) for g in re.finditer(r"\d+", m.group())]
        i = 0
        while len(groups) > 1 and i < len(groups):  # a card number followed by stray digits ("4111 1111 1111 1111 123"): any run of whole groups that is a valid card
            digits, hit = "", None
            for j in range(i, len(groups)):
                digits += groups[j][2]
                if len(digits) > 19:
                    break
                if luhn_ok(digits):
                    hit = j
                    break
            if hit is None:
                i += 1
                continue
            out.append(Finding("CARD", m.start() + groups[i][0], m.start() + groups[hit][1]))
            i = hit + 1
    return out


def _spans(text: str) -> list[Finding]:
    found: list[Finding] = _card_spans(text)
    for m in _SPOKEN.finditer(text):
        polish = bool(_POLISH_DIGIT_WORD.search(m.group()))
        for digits in _spoken_digits(m.group()):
            if len(digits) >= 13 and luhn_ok(digits):
                kind = "CARD"
            elif len(digits) == 26 and nrb_ok(digits):
                kind = "IBAN"
            elif len(digits) == 11 and pesel_ok(digits):
                kind = "PESEL"
            elif polish and re.fullmatch(r"(?:48)?\d{9}|0\d{9}|0048\d{9}", digits):
                kind = "PHONE"  # a Polish number read out loud ("sześć zero zero jeden dwa trzy cztery pięć sześć", "sześćset jeden dwa trzy cztery pięć sześć")
            else:
                continue
            found.append(Finding(kind, m.start(), m.end()))
            break
    for m in _IBAN.finditer(text):
        if iban_ok(m.group()):
            found.append(Finding("IBAN", m.start(), m.end()))
    for rx in (_CVV, _BLIK):
        for m in rx.finditer(text):
            found.append(Finding("CVV", m.start(1), m.end(1)))
    for m in _EMAIL.finditer(text):
        found.append(Finding("EMAIL", m.start(), m.end()))
    for m in _EMAIL_SPOKEN.finditer(text):
        found.append(Finding("EMAIL", m.start(), m.end()))
    for m in _SSN.finditer(text):
        found.append(Finding("SSN", m.start(), m.end()))
    for m in _NI.finditer(text):
        found.append(Finding("NATIONAL_ID", m.start(), m.end()))
    for m in _PHONE.finditer(text):
        if sum(c.isdigit() for c in m.group()) >= 9:
            found.append(Finding("PHONE", m.start(), m.end()))
    found.extend(_pl_phone_spans(text))
    for m in _PESEL.finditer(text):
        if pesel_ok(m.group(1)):
            found.append(Finding("PESEL", m.start(1), m.end(1)))
    for m in _PESEL_KEYWORD.finditer(text):
        if not pesel_ok(m.group(1)):
            found.append(Finding("ID_NUMBER", m.start(1), m.end(1)))
    for rx in (_NIP_FORMATTED, _NIP_KEYWORD, _NIP_PREFIXED):
        for m in rx.finditer(text):
            if nip_ok(m.group(1)):
                found.append(Finding("NIP", m.start(), m.end()))
            elif rx is _NIP_KEYWORD:
                found.append(Finding("ID_NUMBER", m.start(1), m.end(1)))
    for m in _REGON.finditer(text):
        if regon_ok(m.group(1)):
            found.append(Finding("REGON", m.start(1), m.end(1)))
        else:
            found.append(Finding("ID_NUMBER", m.start(1), m.end(1)))
    for m in _ID_CARD.finditer(text):
        if id_card_ok(m.group(1), m.group(2)):
            found.append(Finding("ID_CARD", m.start(), m.end()))
    for m in _ID_CARD_KEYWORD.finditer(text):
        kind = "ID_CARD" if id_card_ok(m.group("letters"), m.group("digits")) else "ID_NUMBER"
        if kind == "ID_CARD" or re.match(r"(?i)dow[oó]d\w*\s+(?:osobist|to[żz]samo)|(?:numer|nr)\s+dowod|seri", m.group("kw")):  # a bare "dowód" is also "proof of purchase": checksum or nothing
            found.append(Finding(kind, m.start("letters"), m.end("digits")))
    for m in _PASSPORT.finditer(text):
        found.append(Finding("PASSPORT", m.start(1), m.end(1)))
    for m in _NRB.finditer(text):
        if nrb_ok(m.group(1)):
            found.append(Finding("IBAN", m.start(), m.end()))
    for m in _NRB_KEYWORD.finditer(text):
        if not nrb_ok(m.group(1)):
            found.append(Finding("ID_NUMBER", m.start(1), m.end(1)))
    return found


def _merge(spans: list[Finding]) -> list[Finding]:
    """Overlapping findings become ONE span covering all of them (a card-like prefix of an IBAN must not leave the rest of the IBAN in clear); its kind is that of the longest member."""
    priority = {"CARD": 0, "CVV": 1, "IBAN": 2, "SSN": 3, "NATIONAL_ID": 4, "PESEL": 4, "NIP": 4, "REGON": 4, "ID_CARD": 4, "PASSPORT": 4, "ID_NUMBER": 4, "EMAIL": 5, "PHONE": 6}
    spans = sorted(spans, key=lambda f: (f.start, priority.get(f.kind, 9), -(f.end - f.start)))
    out: list[Finding] = []
    for s in spans:
        if out and s.start < out[-1].end:
            last = out[-1]
            if s.end > last.end:
                kind = s.kind if (s.end - s.start) > (last.end - last.start) else last.kind
                out[-1] = Finding(kind, last.start, s.end)
            continue
        out.append(s)
    return out


def redact(text: str, *, keep: set[str] | None = None) -> Redaction:
    """Replace PII/PCI with typed placeholders. `keep` lists kinds to leave in place (e.g. {'EMAIL'})."""
    if not text:
        return Redaction(text or "", [])
    spans = [s for s in _merge(_spans(text)) if not (keep and s.kind in keep)]
    out, pos = [], 0
    for s in spans:
        out.append(text[pos : s.start])
        out.append(f"[{s.kind}]")
        pos = s.end
    out.append(text[pos:])
    return Redaction("".join(out), spans)


def redact_text(text: str) -> str:
    return redact(text).text


def contains_card(text: str) -> bool:
    return redact(text).has("CARD")


def redact_obj(obj: Any) -> Any:
    """Recursively redact strings inside dict/list structures (for audit/log payloads)."""
    if isinstance(obj, str):
        return redact(obj).text
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [redact_obj(v) for v in obj]
    return obj


def mask_email(email: str) -> str:
    if "@" not in email:
        return "***"
    user, _, domain = email.partition("@")
    return f"{user[:1]}{'*' * max(len(user) - 1, 2)}@{domain}"


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return f"+{'•' * max(len(digits) - 4, 3)}{digits[-4:]}" if digits else "***"
