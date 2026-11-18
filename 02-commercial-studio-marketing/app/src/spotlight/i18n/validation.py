"""Localized request-validation messages (pydantic v2 error ``type`` -> catalog ``valerr.<type>``)."""

from __future__ import annotations

from typing import Any

from .catalog import has, t
from .locale import DEFAULT, current_locale


def localize_validation_errors(errors: list[dict[str, Any]], locale: str | None = None, limit: int = 10) -> list[dict[str, str]]:
    """``[{loc, msg}]`` for the API error body; English keeps pydantic's own text, other languages use the catalog."""
    loc_lang = locale or current_locale()
    out: list[dict[str, str]] = []
    for e in errors[:limit]:
        msg = str(e.get("msg", ""))
        key = f"valerr.{e.get('type', '')}"
        if loc_lang != DEFAULT and has(key, loc_lang):
            ctx = {k: v for k, v in (e.get("ctx") or {}).items() if isinstance(v, (str, int, float))}
            if "expected" in (e.get("ctx") or {}):
                ctx["expected"] = str(e["ctx"]["expected"]).replace("'", "")
            count = ctx.get("min_length", ctx.get("max_length", 0))
            msg = t(key, loc_lang, count=count, **ctx)
        out.append({"loc": ".".join(str(x) for x in e.get("loc", [])), "msg": msg})
    return out
