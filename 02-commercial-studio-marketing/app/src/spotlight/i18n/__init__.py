"""Server-side localization (en / pl): locale resolution, message catalogs, plural + number/date helpers."""

from __future__ import annotations

from .catalog import CATALOGS, has, label, placeholders, render_message, t
from .fmt import fmt_date, fmt_datetime, fmt_money, fmt_number, fmt_percent, join_list
from .locale import (
    DEFAULT,
    LANGUAGE_NAMES,
    SUPPORTED,
    LocaleMiddleware,
    current_locale,
    normalize_lang,
    parse_accept_language,
    resolve_locale,
    set_locale,
    use_locale,
)
from .plural import plural_category

__all__ = [
    "CATALOGS",
    "DEFAULT",
    "LANGUAGE_NAMES",
    "SUPPORTED",
    "LocaleMiddleware",
    "current_locale",
    "fmt_date",
    "fmt_datetime",
    "fmt_money",
    "fmt_number",
    "fmt_percent",
    "has",
    "join_list",
    "label",
    "normalize_lang",
    "parse_accept_language",
    "placeholders",
    "plural_category",
    "render_message",
    "resolve_locale",
    "set_locale",
    "t",
    "use_locale",
]
