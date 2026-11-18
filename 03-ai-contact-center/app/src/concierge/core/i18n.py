"""Server-side localization core: supported UI languages, locale resolution, the request-scoped locale, message catalogs and date/plural helpers.

Locale resolution order (spec §3 / §11): `?lang=` -> `X-UI-Lang` -> `Accept-Language` -> `en`. Supported: `en`, `pl`.
Deterministic human-readable messages (errors, QA notes, SLA texts, export headings, ...) come from the catalogs `catalog_en` / `catalog_pl`
(same keys, enforced by a unit test) and are rendered at READ time in the request locale; persisted records keep a stable `code` + `params`.
Conversation text spoken to a customer is in the conversation language (`conv.language`), not in the operator's UI language."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from . import catalog_en, catalog_pl

SUPPORTED: tuple[str, ...] = ("en", "pl")
DEFAULT = "en"
LANGUAGE_NAMES = {"en": {"en": "English", "pl": "Polish"}, "pl": {"en": "angielski", "pl": "polski"}}
NATIVE_NAMES = {"en": "English", "pl": "Polski"}

CATALOGS: dict[str, dict[str, str]] = {"en": catalog_en.MESSAGES, "pl": catalog_pl.MESSAGES}
_locale: ContextVar[str] = ContextVar("ui_locale", default=DEFAULT)

PL_WEEKDAYS = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
PL_WEEKDAYS_ACC = ["poniedziałek", "wtorek", "środę", "czwartek", "piątek", "sobotę", "niedzielę"]  # "na środę", "w sobotę"
PL_MONTHS_GEN = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września", "października", "listopada", "grudnia"]
EN_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
WARSAW = ZoneInfo("Europe/Warsaw")


# ------------------------------------------------------------------------------------------------ resolution
def normalize(code: str | None) -> str | None:
    """`pl`, `PL`, `pl-PL`, `pl_PL` -> `pl`; unsupported or empty -> None."""
    if not code:
        return None
    base = re.split(r"[-_;,\s]", code.strip().lower(), maxsplit=1)[0]
    return base if base in SUPPORTED else None


def parse_accept_language(header: str | None) -> str | None:
    """Best supported language of an Accept-Language header by q-value (`pl-PL,pl;q=0.9,en;q=0.8` -> pl)."""
    if not header:
        return None
    ranked: list[tuple[float, int, str]] = []
    for i, part in enumerate(header.split(",")):
        tag, _, params = part.strip().partition(";")
        q = 1.0
        m = re.search(r"q\s*=\s*([0-9.]+)", params)
        if m:
            try:
                q = float(m.group(1))
            except ValueError:
                q = 0.0
        lang = normalize(tag)
        if lang and q > 0:
            ranked.append((-q, i, lang))
    return sorted(ranked)[0][2] if ranked else None


def resolve_locale(query_lang: str | None = None, x_ui_lang: str | None = None, accept_language: str | None = None) -> str:
    return normalize(query_lang) or normalize(x_ui_lang) or parse_accept_language(accept_language) or DEFAULT


def current_locale() -> str:
    return _locale.get()


def set_locale(lang: str | None) -> None:
    _locale.set(normalize(lang) or DEFAULT)


@contextmanager
def use_locale(lang: str | None) -> Iterator[str]:
    token = _locale.set(normalize(lang) or DEFAULT)
    try:
        yield _locale.get()
    finally:
        _locale.reset(token)


class LocaleMiddleware:
    """Pure ASGI middleware: sets the request locale (HTTP and WebSocket) and echoes it as `Content-Language`."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        lang = resolve_locale((query.get("lang") or [None])[0], headers.get("x-ui-lang"), headers.get("accept-language"))
        scope.setdefault("state", {})["locale"] = lang
        token = _locale.set(lang)

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                hdrs = [(k, v) for k, v in message.get("headers", []) if k.lower() not in (b"content-language",)]
                hdrs += [(b"content-language", lang.encode()), (b"vary", b"Accept-Language, X-UI-Lang")]
                message = {**message, "headers": hdrs}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _locale.reset(token)


# ------------------------------------------------------------------------------------------------ catalogs
def has(code: str) -> bool:
    return code in CATALOGS["en"]


def msg(code: str, lang: str | None = None, /, **params: Any) -> str:
    """Catalog message in `lang` (default: request locale), `{param}` interpolation; falls back to English, then to the code itself."""
    lang = normalize(lang) or current_locale()
    template = CATALOGS.get(lang, {}).get(code) or CATALOGS["en"].get(code)
    if template is None:
        return code
    try:
        return template.format(**params) if params else template
    except (KeyError, IndexError, ValueError):
        return template


def label(prefix: str, key: str, lang: str | None = None, default: str | None = None) -> str:
    """Localized label of a stable key (`disposition.RESOLVED_REFUND_ISSUED`, `queue.returns`, ...); unknown keys return `default` or the key."""
    code = f"{prefix}.{key}"
    return msg(code, lang) if has(code) else (default if default is not None else key)


def catalog_codes(lang: str) -> set[str]:
    return set(CATALOGS[lang])


# ------------------------------------------------------------------------------------------------ plurals & dates
def plural(lang: str, n: int | float, forms: dict[str, str]) -> str:
    """CLDR plural selection: English one/other, Polish one/few/many/other (fractions use `other`)."""
    if lang == "pl":
        if isinstance(n, float) and not float(n).is_integer():
            return forms.get("other", forms.get("many", ""))
        k = abs(int(n))
        if k == 1:
            return forms.get("one", "")
        if 2 <= k % 10 <= 4 and not 12 <= k % 100 <= 14:
            return forms.get("few", forms.get("many", ""))
        return forms.get("many", forms.get("other", ""))
    return forms.get("one", "") if n == 1 else forms.get("other", forms.get("many", ""))


def _as_date(value: float | int | str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, UTC).date()
    return date.fromisoformat(str(value)[:10])


def weekday_name(value: Any, lang: str | None = None, *, accusative: bool = False) -> str:
    """Weekday name; `accusative` (Polish only) is the form after "na" / "w": `środa` -> `na środę`."""
    d = _as_date(value)
    if (normalize(lang) or current_locale()) == "pl":
        return (PL_WEEKDAYS_ACC if accusative else PL_WEEKDAYS)[d.weekday()]
    return EN_WEEKDAYS[d.weekday()]


def month_name(month: int, lang: str | None = None, *, genitive: bool = True) -> str:
    return (PL_MONTHS_GEN if (normalize(lang) or current_locale()) == "pl" else EN_MONTHS)[month - 1]


def fmt_date(value: Any, lang: str | None = None, *, long: bool = False) -> str:
    """pl: `19.11.2026` / `19 listopada 2026`; en: `2026-11-19` / `19 November 2026`."""
    lang = normalize(lang) or current_locale()
    d = _as_date(value)
    if long:
        return f"{d.day} {month_name(d.month, lang)} {d.year}"
    return f"{d.day:02d}.{d.month:02d}.{d.year}" if lang == "pl" else d.isoformat()


def fmt_datetime(ts: float, lang: str | None = None, *, tz: ZoneInfo | None = None) -> str:
    """Local date and 24 h time; Polish output defaults to Europe/Warsaw, English to UTC."""
    lang = normalize(lang) or current_locale()
    dt = datetime.fromtimestamp(ts, tz or (WARSAW if lang == "pl" else UTC))
    return f"{fmt_date(dt, lang)} {dt:%H:%M}"


def slot_phrase(slot_date: str, window: str, lang: str | None = None) -> str:
    """`czwartek 19.11.2026 w godzinach 09:00-13:00` / `Thursday 2026-11-19 between 09:00-13:00` (stored window text, unchanged)."""
    lang = normalize(lang) or current_locale()
    if lang == "pl":
        return f"{weekday_name(slot_date, lang)} {fmt_date(slot_date, lang)} w godzinach {window}"
    return f"{weekday_name(slot_date, lang)} {slot_date} between {window}"


_WINDOW_RX = re.compile(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})")


def fmt_window(window: str, lang: str | None = None) -> str:
    """A time window as it reads in `lang`: Polish writes the range with an en dash and no spaces (`09:00–13:00`); other languages keep the stored text."""
    return _WINDOW_RX.sub(r"\1–\2", window) if (normalize(lang) or current_locale()) == "pl" else window


def slot_when(slot_date: str, window: str, lang: str | None = None, *, accusative: bool = False) -> str:
    """Customer-facing slot as a phrase: `czwartek 19.11.2026, w godzinach 09:00–13:00` (after "na" / "w": `środę 18.11.2026, w godzinach 09:00–13:00`); English as `slot_phrase`."""
    lang = normalize(lang) or current_locale()
    if lang == "pl":
        return f"{weekday_name(slot_date, lang, accusative=accusative)} {fmt_date(slot_date, lang)}, w godzinach {fmt_window(window, lang)}"
    return slot_phrase(slot_date, window, lang)


# ------------------------------------------------------------------------------------------------ Polish typography
NBSP = "\u00a0"
_ONE_LETTER_RX = re.compile(r"(?<![\w/.\-])([aiouwzAIOUWZ]) (?=[\w„\"(€])")  # a, i, o, u, w, z must not end a line
_THOUSANDS_RX = re.compile(r"(?<![\w,.])(\d{1,3}) (\d{3})(?!\d)")  # 2 150
_NUMBER_UNIT_RX = re.compile(r"(?<=\d) (?=(?:zł|EUR|PLN|USD|€|kg|cm|mm|m|min|szt\.|r\.)(?!\w))")  # currency, measure units and "r." (year): "30 dni" keeps its ordinary space
_ABBREVIATION_RX = re.compile(r"\b(ok\.|nr|np\.|tj\.) (?=\d)")


def nbsp_pl(text: str) -> str:
    """Polish typography for customer-facing prose: a non-breaking space after one-letter words (`w`, `z`, `i`, `o`, `u`, `a`), inside numbers (`2 150`), between a
    number and its currency / measure unit (`500 EUR`, `1,5 m`) and after `ok.` / `nr` / `np.` before a number. Idempotent; the English `Keywords (en):` line of a
    knowledge article is left alone. Do not apply it to SMS text (a no-break space would force a longer encoding)."""
    out: list[str] = []
    for line in text.split("\n"):
        if not line.lower().startswith("keywords ("):
            line = _ONE_LETTER_RX.sub(r"\1" + NBSP, line)
            line = _THOUSANDS_RX.sub(r"\1" + NBSP + r"\2", line)
            line = _NUMBER_UNIT_RX.sub(NBSP, line)
            line = _ABBREVIATION_RX.sub(r"\1" + NBSP, line)
        out.append(line)
    return "\n".join(out)
