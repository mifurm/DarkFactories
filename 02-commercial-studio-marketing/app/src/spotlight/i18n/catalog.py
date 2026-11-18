"""Message catalogs (``en`` / ``pl``) and the ``t()`` renderer.

Keys are stable dotted identifiers (``err.brief_missing``, ``finding.claims.prohibited``, ``job.script.write`` …). A value is either a
template string (``str.format`` placeholders; ``{amount:usd}``, ``{n:int}``, ``{p:pct1}``, ``{d:date}`` are locale-aware) or a
``{one, few, many, other}`` mapping chosen by the ``count`` parameter (CLDR plural rules, Polish has four forms).

Persisted machine-generated records store ``key`` + ``params`` and are rendered at read time in the request locale — see
:func:`render_message`. Parity (same keys, same placeholders, same plural forms) between ``en`` and ``pl`` is enforced by tests.
"""

from __future__ import annotations

import string
from typing import Any

from .fmt import format_value
from .locale import DEFAULT, SUPPORTED, current_locale
from .messages_en import MESSAGES as EN
from .messages_pl import MESSAGES as PL
from .plural import pick_plural

CATALOGS: dict[str, dict[str, Any]] = {"en": EN, "pl": PL}

# Parameters that carry a stable machine value which should be shown as a human label (label.<group>.<value>); unknown values pass through.
LABEL_PARAMS = {
    "kind": "label.kind",
    "call": "label.call",
    "check": "label.check",
    "gate": "label.gate",
    "earlier": "label.gate",
    "stage": "label.gate",
    "role": "label.role",
    "beat_role": "label.beat",
    "language": "label.lang",
    "quality": "label.quality",
    "tone": "label.tone",
    "state": "label.state",
    "claim_type": "label.claim_type",
    "pack": "label.pack",
    "source": "label.source",
    "status": "label.status",
    "usage": "label.usage",
}


class _Formatter(string.Formatter):
    def __init__(self, lang: str) -> None:
        super().__init__()
        self.lang = lang

    def get_value(self, key: int | str, args: Any, kwargs: Any) -> Any:
        if isinstance(key, str):
            return kwargs.get(key, "{" + key + "}")  # an unknown placeholder stays visible instead of raising
        return args[key]

    def format_field(self, value: Any, format_spec: str) -> str:
        if format_spec in ("role", "roles"):  # English keeps the raw role ids (legacy wording), other languages show labels
            items = value if isinstance(value, (list, tuple)) else [value]
            shown = [str(v) if self.lang == DEFAULT else label("label.role", v, self.lang) for v in items]
            return ", ".join(shown)
        if format_spec:
            try:
                return format_value(value, format_spec, self.lang)
            except (TypeError, ValueError):
                return str(value)
        return str(value)


def entry(key: str, locale: str | None = None) -> Any | None:
    """The raw catalog value for ``key`` in ``locale`` (no fallback)."""
    return CATALOGS.get(locale or current_locale(), CATALOGS[DEFAULT]).get(key)


def has(key: str, locale: str | None = None) -> bool:
    return entry(key, locale) is not None


def _resolve_param(value: Any, locale: str) -> Any:
    """Per-language dicts ({'en': …, 'pl': …}) collapse to the caller's language (fallback: English, then any)."""
    if isinstance(value, dict) and value and set(value) <= set(SUPPORTED):
        return value.get(locale) or value.get(DEFAULT) or next(iter(value.values()))
    return value


def label(group: str, value: Any, locale: str | None = None) -> str:
    """Human label for a stable value (``label.role.legal`` -> 'Legal / Compliance'); unknown values are returned as text."""
    loc = locale or current_locale()
    found = entry(f"{group}.{value}", loc)
    if found is None:
        found = entry(f"{group}.{value}", DEFAULT)
    return str(found) if isinstance(found, str) else str(value)


def _prep(params: dict[str, Any], locale: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in params.items():
        v = _resolve_param(v, locale)
        group = LABEL_PARAMS.get(k)
        if group and isinstance(v, str):
            v = label(group, v, locale)
        out[k] = v
    return out


def t(key: str, locale: str | None = None, **params: Any) -> str:
    """Render ``key`` in ``locale`` (default: the request locale). Falls back to English, then to the key itself."""
    loc = locale or current_locale()
    raw = entry(key, loc)
    if raw is None:
        raw = entry(key, DEFAULT)
    if raw is None:
        return key
    if isinstance(raw, dict):
        count = params.get("count", params.get("n", 0))
        raw = pick_plural(raw, loc, count)
    return _Formatter(loc).vformat(raw, (), _prep(params, loc))


def render_message(key: str | None, params: dict[str, Any] | None, fallback: str = "", locale: str | None = None) -> str:
    """Render a stored ``key`` + ``params`` pair; ``fallback`` (the text stored at creation) is used for legacy records."""
    if key and has(key, DEFAULT):
        return t(key, locale, **(params or {}))
    return fallback


def placeholders(template: str) -> set[str]:
    """Placeholder names of a template (used by the en/pl parity test)."""
    return {name.split(".")[0].split("[")[0] for _, name, _, _ in string.Formatter().parse(template) if name}
