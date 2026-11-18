"""Number / money / percent / date helpers with en and pl-PL conventions (no external locale data, no ICU needed).

pl-PL: decimal comma, NBSP as the thousands separator (only from 5 digits up — CLDR ``minimumGroupingDigits=2``), ``18.11.2026``,
``18 listopada 2026``, 24-hour clock. Server timestamps are UTC; user-facing absolute times are shown in Europe/Warsaw when asked.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

NBSP = "\u00a0"
WARSAW = ZoneInfo("Europe/Warsaw")

MONTHS_PL_GEN = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września", "października", "listopada", "grudnia"]
MONTHS_PL = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
WEEKDAYS_PL = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
CURRENCY_SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£"}


def fmt_number(value: float | int, lang: str = "en", decimals: int | None = None) -> str:
    """1234567.891 -> '1,234,567.89' (en) / '1 234 567,89' (pl, NBSP). ``decimals=None`` keeps integers integral."""
    v = float(value)
    if decimals is None:
        decimals = 0 if v.is_integer() else 2
    body = f"{abs(v):.{decimals}f}"
    whole, _, frac = body.partition(".")
    if lang == "pl":
        grouped = f"{int(whole):,}".replace(",", NBSP) if len(whole) >= 5 else whole
        out = grouped + ("," + frac if frac else "")
    else:
        out = f"{int(whole):,}" + ("." + frac if frac else "")
    return ("-" if v < 0 and float(body) != 0 else "") + out


def fmt_money(value: float, currency: str = "USD", lang: str = "en", decimals: int | None = None) -> str:
    """$1,234.56 (en) / 1 234,56 USD (pl — ISO code after the amount, NBSP)."""
    v = float(value)
    if decimals is None:
        decimals = 2 if v >= 0.1 or v == 0 else 4
    num = fmt_number(v, lang, decimals)
    if lang == "pl":
        return f"{num}{NBSP}{currency}"
    sym = CURRENCY_SYMBOL.get(currency)
    return f"{sym}{num}" if sym else f"{num} {currency}"


def fmt_percent(ratio: float, lang: str = "en", decimals: int = 0) -> str:
    """0.125 -> '12.5%' (en) / '12,5%' (pl)."""
    return fmt_number(ratio * 100, lang, decimals) + "%"


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def fmt_date(value: Any, lang: str = "en", style: str = "short") -> str:
    """short: 2026-11-18 (en) / 18.11.2026 (pl) · long: Nov 18, 2026 (en) / 18 listopada 2026 (pl)."""
    d = _as_date(value)
    if lang == "pl":
        return f"{d.day} {MONTHS_PL_GEN[d.month - 1]} {d.year}" if style == "long" else f"{d.day:02d}.{d.month:02d}.{d.year}"
    return f"{MONTHS_EN[d.month - 1][:3]} {d.day}, {d.year}" if style == "long" else d.isoformat()


def fmt_datetime(value: Any, lang: str = "en", tz: ZoneInfo | None = None) -> str:
    """UTC timestamp -> '18.11.2026 14:05' (pl, Europe/Warsaw by default) / '2026-11-18 14:05' (en, UTC)."""
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    if lang == "pl":
        local = dt.astimezone(tz or WARSAW)
        return f"{fmt_date(local, 'pl')} {local:%H:%M}"
    local = dt.astimezone(tz or UTC)
    return f"{local:%Y-%m-%d %H:%M}"


def weekday_name(d: Any, lang: str = "en") -> str:
    idx = _as_date(d).weekday()
    return (WEEKDAYS_PL if lang == "pl" else WEEKDAYS_EN)[idx]


def join_list(items: list[str], lang: str = "en") -> str:
    """['a','b','c'] -> 'a, b and c' (en) / 'a, b i c' (pl; no comma before 'i')."""
    items = [str(i) for i in items]
    if len(items) <= 1:
        return "".join(items)
    word = "i" if lang == "pl" else "and"
    return f"{', '.join(items[:-1])} {word} {items[-1]}"


def format_value(value: Any, spec: str, lang: str) -> str:
    """Format-spec dispatcher used by the message catalog: ``{amount:usd}``, ``{n:int}``, ``{x:num1}``, ``{p:pct}``, ``{d:date}``."""
    if spec == "g2":  # two significant digits (p-values)
        text = f"{float(value):.2g}"
        return text.replace(".", ",") if lang == "pl" else text
    if spec == "raw":  # the value as Python prints it (keeps legacy English digits), with a decimal comma for Polish
        text = str(value)
        return text.replace(".", ",") if lang == "pl" else text
    if spec == "usd":
        return fmt_money(float(value), "USD", lang)
    if spec == "int":
        return fmt_number(round(float(value)), lang, 0)
    if spec.startswith("num"):
        return fmt_number(float(value), lang, int(spec[3:] or 2))
    if spec.startswith("pct"):
        return fmt_percent(float(value), lang, int(spec[3:] or 0))
    if spec == "date":
        return fmt_date(value, lang)
    if spec == "datelong":
        return fmt_date(value, lang, "long")
    if spec == "datetime":
        return fmt_datetime(value, lang)
    if spec == "list":
        return join_list(list(value) if isinstance(value, (list, tuple, set)) else [value], lang)
    return format(value, spec)
