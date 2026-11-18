"""Brand-kit localization helpers: a kit carries language-neutral parts (palette, logo, typography, markets) and per-language
``i18n[<lang>]`` overlays (tagline, voice rules, products, personas, sourcing text …).

* :func:`localized_kit` — the merged view for one language (what the UI shows and what agents ground on);
* :func:`apply_kit_update` — routes an edit made in a language to that language's overlay (not to the English base).
"""

from __future__ import annotations

from typing import Any

LANG_FIELDS = ("tagline", "voice", "products", "personas")


def kit_languages(kit: dict[str, Any]) -> list[str]:
    return ["en", *[lang for lang in (kit.get("i18n") or {}) if lang != "en"]]


def _merge_by_id(base: list[dict[str, Any]], overlay: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    over = {o.get("id"): o for o in overlay or []}
    merged = [{**b, **over.get(b.get("id"), {})} for b in base]
    known = {b.get("id") for b in base}
    return merged + [o for o in (overlay or []) if o.get("id") not in known]


def localized_kit(kit: dict[str, Any], lang: str) -> dict[str, Any]:
    """The kit as shown in ``lang`` (English base + that language's overlay). Lists in an overlay replace the base lists."""
    out = {k: v for k, v in kit.items() if k != "i18n"}
    out["lang"] = "en"
    out["languages"] = kit_languages(kit)
    loc = (kit.get("i18n") or {}).get(lang)
    if lang == "en" or not loc:
        return out
    out["lang"] = lang
    if loc.get("tagline"):
        out["tagline"] = loc["tagline"]
    out["voice"] = {**kit.get("voice", {}), **(loc.get("voice") or {})}
    out["products"] = _merge_by_id(kit.get("products", []), loc.get("products"))
    out["personas"] = _merge_by_id(kit.get("personas", []), loc.get("personas"))
    for k, v in loc.items():
        if k == "logo":  # only the descriptive text is translated: the wordmark and the numbers stay
            out["logo"] = {**kit.get("logo", {}), **v}
        elif k not in LANG_FIELDS:
            out[k] = v
    return out


def kit_voice(kit: dict[str, Any], lang: str) -> dict[str, Any]:
    return localized_kit(kit, lang).get("voice", {})


def kit_tagline(kit: dict[str, Any], lang: str) -> str:
    return str(localized_kit(kit, lang).get("tagline") or "")


def apply_kit_update(kit: dict[str, Any], update: dict[str, Any], lang: str) -> dict[str, Any]:
    """Apply ``update`` to a copy of ``kit``: language-specific fields go to ``i18n[lang]`` when editing in a non-English language."""
    new = dict(kit)
    i18n = {k: dict(v) for k, v in (kit.get("i18n") or {}).items()}
    for key, value in update.items():
        if lang != "en" and lang in i18n and key in LANG_FIELDS:
            i18n[lang][key] = value
        else:
            new[key] = value
    if i18n:
        new["i18n"] = i18n
    return new
