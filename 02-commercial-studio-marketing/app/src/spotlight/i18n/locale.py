"""Locale resolution for the API: ``?lang=`` -> ``X-UI-Lang`` -> ``Accept-Language`` -> ``en``.

The resolved locale lives in a ContextVar, so deterministic server messages (errors, Guardian findings, job titles, audit
summaries, notifications, exports …) can be rendered in the caller's language without threading a parameter through every
function. Background tasks created while serving a request inherit it (``asyncio.create_task`` copies the context).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Message, Receive, Scope, Send

SUPPORTED: tuple[str, ...] = ("en", "pl")
DEFAULT = "en"
LANGUAGE_NAMES = {"en": "English", "pl": "Polski"}

locale_var: ContextVar[str] = ContextVar("ui_locale", default=DEFAULT)


def current_locale() -> str:
    return locale_var.get()


def set_locale(lang: str) -> str:
    """Set the locale for the current context (unsupported values fall back to the default)."""
    value = normalize_lang(lang) or DEFAULT
    locale_var.set(value)
    return value


@contextmanager
def use_locale(lang: str | None) -> Iterator[str]:
    """Temporarily render in ``lang`` (tests, background jobs that must follow a campaign language)."""
    value = normalize_lang(lang) or current_locale()
    token = locale_var.set(value)
    try:
        yield value
    finally:
        locale_var.reset(token)


_TAG = re.compile(r"^\s*([A-Za-z]{2,3})(?:[-_][A-Za-z0-9]{2,8})*\s*$")


def normalize_lang(value: str | None) -> str | None:
    """'pl-PL' / 'PL' / 'pl_pl' -> 'pl'; anything unsupported -> None."""
    if not value:
        return None
    m = _TAG.match(value)
    if not m:
        return None
    primary = m.group(1).lower()
    return primary if primary in SUPPORTED else None


def parse_accept_language(header: str | None) -> list[str]:
    """Primary language subtags of an Accept-Language header ordered by quality (q=0 entries dropped, ties keep order)."""
    if not header:
        return []
    ranked: list[tuple[float, int, str]] = []
    for i, part in enumerate(header.split(",")):
        bits = part.strip().split(";")
        tag = bits[0].strip()
        if not tag or tag == "*":
            continue
        q = 1.0
        for b in bits[1:]:
            b = b.strip()
            if b.lower().startswith("q="):
                try:
                    q = float(b[2:])
                except ValueError:
                    q = 0.0
        if q > 0:
            ranked.append((-q, i, tag.split("-")[0].split("_")[0].lower()))
    return [tag for _, _, tag in sorted(ranked)]


def resolve_locale(query_lang: str | None = None, x_ui_lang: str | None = None, accept_language: str | None = None) -> str:
    """First supported value among ``?lang=``, ``X-UI-Lang`` and the (q-ordered) ``Accept-Language`` list, else ``en``."""
    for candidate in (query_lang, x_ui_lang):
        lang = normalize_lang(candidate)
        if lang:
            return lang
    for tag in parse_accept_language(accept_language):
        if tag in SUPPORTED:
            return tag
    return DEFAULT


class LocaleMiddleware:
    """Pure-ASGI middleware: resolves the locale per request/WebSocket and tags responses with ``Content-Language``."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        qs = parse_qs(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=False)
        lang = resolve_locale((qs.get("lang") or [None])[0], headers.get("x-ui-lang"), headers.get("accept-language"))
        scope.setdefault("state", {})["locale"] = lang
        token = locale_var.set(lang)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                hdrs = list(message.get("headers", []))
                if not any(k.lower() == b"content-language" for k, _ in hdrs):
                    hdrs.append((b"content-language", lang.encode()))
                message = {**message, "headers": hdrs}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            locale_var.reset(token)
