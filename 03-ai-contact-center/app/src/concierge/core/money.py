"""Currency handling for the multi-currency demo: one documented FIXED demo exchange rate, EUR-equivalent policy evaluation, locale-aware money
formatting / parsing, and Polish amounts in words for voice.

Orders are stored in their own currency (`EUR` for most markets, `PLN` for the Polish market). Policy caps and approval thresholds are always
EUR amounts (`refund_auto_cap_eur`, ...) and are evaluated on the EUR-equivalent of the order-currency amount at the fixed rate below. The rate is a
demo constant - NOT a market quote; production would read a rate service and record the rate used on every decision."""

from __future__ import annotations

import re
from typing import Any

BASE_CURRENCY = "EUR"
FX_PER_EUR: dict[str, float] = {"EUR": 1.0, "PLN": 4.30}  # 1 EUR = 4.30 PLN (fixed demo rate, documented in README / ARCHITECTURE)
CURRENCY_SYMBOLS = {"EUR": "EUR", "PLN": "zł"}
NBSP = "\u00a0"


def known(currency: str | None) -> str:
    c = (currency or BASE_CURRENCY).upper()
    return c if c in FX_PER_EUR else BASE_CURRENCY


def to_eur(amount: float, currency: str | None) -> float:
    """EUR-equivalent of an amount in `currency` (policy basis)."""
    return round(float(amount) / FX_PER_EUR[known(currency)], 4)


def from_eur(amount_eur: float, currency: str | None) -> float:
    return round(float(amount_eur) * FX_PER_EUR[known(currency)], 2)


def order_currency(order: dict[str, Any] | None) -> str:
    """Currency of an order document; connectors that do not carry one mean EUR."""
    return known((order or {}).get("currency"))


# ------------------------------------------------------------------------------------------------ result keys
def mkeys(currency: str | None, **amounts: float | None) -> dict[str, Any]:
    """Money fields of a tool result. EUR keeps the historic `<name>_eur` keys (unchanged contract); other currencies use the plain name plus
    `currency`, so a model never reads a PLN amount under a key that says EUR."""
    cur = known(currency)
    if cur == BASE_CURRENCY:
        return {f"{k}_eur": v for k, v in amounts.items()}
    return {**amounts, "currency": cur}


def pick(data: dict[str, Any], name: str) -> float | None:
    """Amount stored by `mkeys` under `<name>_eur` (EUR) or `<name>` (other currency)."""
    v = data.get(f"{name}_eur")
    if v is None:
        v = data.get(name)
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def pick_eur(data: dict[str, Any], name: str) -> float | None:
    """`pick`, converted to the EUR-equivalent (policy basis)."""
    v = pick(data, name)
    return None if v is None else to_eur(v, data.get("currency") if f"{name}_eur" not in data else BASE_CURRENCY)


# ------------------------------------------------------------------------------------------------ formatting
def _group(int_part: str, sep: str) -> str:
    out = []
    while len(int_part) > 3:
        out.insert(0, int_part[-3:])
        int_part = int_part[:-3]
    out.insert(0, int_part)
    return sep.join(out)


def format_number(value: float, lang: str = "en", decimals: int = 2) -> str:
    """`1 599,00` (pl: NBSP thousands, decimal comma) or `1599.00` (en/other: historic plain style, no grouping)."""
    neg = value < 0
    s = f"{abs(value):.{decimals}f}"
    ip, _, fp = s.partition(".")
    if lang == "pl":
        s = _group(ip, NBSP) + (f",{fp}" if fp else "")
    else:
        s = ip + (f".{fp}" if fp else "")
    return f"-{s}" if neg else s


def format_money(amount: float, currency: str | None = "EUR", lang: str = "en") -> str:
    """Polish: `1 599,00 zł` / `379,00 EUR`; English: `EUR 379.00` / `PLN 1599.00` (the English EUR rendering is the historic one)."""
    cur = known(currency)
    if lang == "pl":
        return f"{format_number(amount, 'pl')}{NBSP}{CURRENCY_SYMBOLS[cur]}"
    return f"{cur} {format_number(amount, 'en')}"


# ------------------------------------------------------------------------------------------------ parsing
_SEP = r"[ \u00a0\u202f]"
NUMBER_RX = re.compile(rf"(?<![\d.,])\d{{1,3}}(?:{_SEP}\d{{3}})+(?:[.,]\d{{1,2}})?(?!\d)|(?<![\d.,])\d{{1,3}}(?:\.\d{{3}})+(?:,\d{{1,2}})?(?!\d)|(?<![\d.,])\d{{1,3}}(?:,\d{{3}})+(?:\.\d{{1,2}})?(?!\d)|(?<![\d.,])\d+(?:[.,]\d{{1,2}})?(?!\d)")  # also English grouping: 1,599.00
_CUR = r"(?:z[łl](?:ot(?:ych|e|y|ego|ym|ymi|a|ą)?)?|pln|eur(?:o(?:s|w)?|ów)?|€)"  # `euros` (English plural), `eurów` / `eurow` (Polish genitive plural)
MONEY_RX = re.compile(rf"(?P<a>{NUMBER_RX.pattern})\s?(?P<c>{_CUR})(?![\w])|(?P<c2>€|(?<![\w])(?:eur(?:o)?|pln)(?![\w]))\s?(?P<a2>{NUMBER_RX.pattern})", re.IGNORECASE)


def parse_number(text: str) -> float:
    """Parse `379,00`, `379.00`, `1 599,00`, `1.599,00`, `1,599.00` (NBSP / thin-space grouping accepted)."""
    s = re.sub(rf"{_SEP}", "", text.strip())
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = head.replace(",", "") + tail if len(tail) == 3 and head.isdigit() and 1 <= len(head) <= 3 else s.replace(",", ".")
    elif "." in s:
        head, _, tail = s.rpartition(".")
        s = head.replace(".", "") + tail if len(tail) == 3 and head.isdigit() and 1 <= len(head) <= 3 else s
    return round(float(s), 2)


def _cur_of(token: str) -> str:
    t = token.lower()
    return "PLN" if t.startswith(("z", "pln")) else "EUR"


def parse_money(text: str) -> list[tuple[float, str]]:
    """Every (amount, currency) in `text`: `379,00 zł`, `1 599 PLN`, `1.599,00 zł`, `EUR 379.00`, `€500`, `500 euro`."""
    out: list[tuple[float, str]] = []
    for m in MONEY_RX.finditer(text):
        raw, cur = (m.group("a"), m.group("c")) if m.group("a") else (m.group("a2"), m.group("c2"))
        try:
            out.append((parse_number(raw), _cur_of(cur)))
        except ValueError:
            continue
    return out


# ------------------------------------------------------------------------------------------------ Polish amounts in words (voice)
_ONES = ["zero", "jeden", "dwa", "trzy", "cztery", "pięć", "sześć", "siedem", "osiem", "dziewięć", "dziesięć", "jedenaście", "dwanaście", "trzynaście", "czternaście", "piętnaście", "szesnaście", "siedemnaście", "osiemnaście", "dziewiętnaście"]  # fmt: skip
_TENS = ["", "", "dwadzieścia", "trzydzieści", "czterdzieści", "pięćdziesiąt", "sześćdziesiąt", "siedemdziesiąt", "osiemdziesiąt", "dziewięćdziesiąt"]
_HUNDREDS = ["", "sto", "dwieście", "trzysta", "czterysta", "pięćset", "sześćset", "siedemset", "osiemset", "dziewięćset"]


def plural_form_pl(n: int, one: str, few: str, many: str) -> str:
    """CLDR plural rule of Polish for integers: 1 -> one; 2-4 (not 12-14) -> few; everything else -> many."""
    n = abs(int(n))
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _below_thousand(n: int) -> list[str]:
    words: list[str] = []
    h, rest = divmod(n, 100)
    if h:
        words.append(_HUNDREDS[h])
    if rest >= 20:
        words.append(_TENS[rest // 10])
        if rest % 10:
            words.append(_ONES[rest % 10])
    elif rest:
        words.append(_ONES[rest])
    return words


def number_words_pl(n: int) -> str:
    """`379` -> `trzysta siedemdziesiąt dziewięć`; `1 599` -> `tysiąc pięćset dziewięćdziesiąt dziewięć` (0 .. 999 999 999)."""
    n = int(n)
    if n == 0:
        return _ONES[0]
    if n < 0:
        return "minus " + number_words_pl(-n)
    words: list[str] = []
    millions, rest = divmod(n, 1_000_000)
    thousands, units = divmod(rest, 1000)
    if millions == 1:
        words.append("milion")
    elif millions:
        words += [*_below_thousand(millions), plural_form_pl(millions, "milion", "miliony", "milionów")]
    if thousands == 1:
        words.append("tysiąc")
    elif thousands:
        words += [*_below_thousand(thousands), plural_form_pl(thousands, "tysiąc", "tysiące", "tysięcy")]
    words += _below_thousand(units)
    return " ".join(w for w in words if w)


def spoken_money_pl(amount: float, currency: str | None = "PLN") -> str:
    """`379,00 zł` -> `trzysta siedemdziesiąt dziewięć złotych`; `12,50 zł` -> `dwanaście złotych pięćdziesiąt groszy` (EUR: euro / eurocentów)."""
    cur = known(currency)
    total = round(abs(float(amount)) * 100)
    whole, frac = divmod(total, 100)
    if cur == "PLN":
        major = plural_form_pl(whole, "złoty", "złote", "złotych")
        minor = plural_form_pl(frac, "grosz", "grosze", "groszy")
    else:
        major, minor = "euro", plural_form_pl(frac, "eurocent", "eurocenty", "eurocentów")
    words = f"{number_words_pl(whole)} {major}"
    if frac:
        words += f" {number_words_pl(frac)} {minor}"
    return ("minus " if amount < 0 else "") + words


def speakable_pl(text: str) -> str:
    """Rewrites every money amount in a Polish reply as words so that TTS reads `379,00 zł` as `trzysta siedemdziesiąt dziewięć złotych`."""

    def sub(m: re.Match[str]) -> str:
        raw, cur = (m.group("a"), m.group("c")) if m.group("a") else (m.group("a2"), m.group("c2"))
        try:
            return spoken_money_pl(parse_number(raw), _cur_of(cur))
        except ValueError:
            return m.group(0)

    return MONEY_RX.sub(sub, text)
