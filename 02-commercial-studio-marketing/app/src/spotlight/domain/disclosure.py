"""AI disclosure labels per jurisdiction / platform (CS-14). Illustrative rules — validate with counsel."""

from __future__ import annotations

from typing import Any

from ..i18n import has
from ..i18n import t as tr
from .claims import REGIONS

BADGE_TEXT = {
    "en": "AI-generated",
    "de": "KI-generiert",
    "fr": "Généré par IA",
    "es": "Generado con IA",
    "it": "Generato con IA",
    "pl": "Wygenerowano przez AI",
    "pt": "Gerado por IA",
    "nl": "AI-gegenereerd",
}

JURISDICTIONS: dict[str, dict[str, Any]] = {
    "EU": {
        "name": "European Union",
        "required": True,
        "basis": "EU AI Act Art. 50 — transparency obligations for AI-generated / manipulated image, audio and video (applies from Aug 2026).",
        "badge": True,
        "metadata": ["c2pa", "iptc"],
    },
    "UK": {"name": "United Kingdom", "required": False, "basis": "ASA/CAP guidance: do not mislead; disclose synthetic people where it affects consumer understanding.", "badge": True, "metadata": ["c2pa"]},
    "US": {"name": "United States", "required": False, "basis": "FTC truth-in-advertising; several state laws on synthetic media in ads; platform policies apply.", "badge": False, "metadata": ["c2pa"]},
}

PLATFORMS: dict[str, dict[str, Any]] = {
    "meta": {"label": "AI info", "mechanism": "C2PA/IPTC metadata is read to auto-label; use Meta's disclosure setting for photorealistic AI video.", "required": True},
    "youtube": {"label": "Altered or synthetic content", "mechanism": "Disclose in YouTube Studio ('altered or synthetic content') for realistic synthetic content.", "required": True},
    "tiktok": {"label": "AI-generated content", "mechanism": "Toggle 'AI-generated content' on upload; C2PA content credentials are auto-detected.", "required": True},
    "linkedin": {"label": "Content credentials", "mechanism": "LinkedIn displays C2PA content credentials (CR icon) when present.", "required": False},
    "ctv": {"label": "Broadcaster / publisher standards", "mechanism": "Pass the provenance pack to the publisher; some require an on-screen disclosure.", "required": False},
    "display": {"label": "Ad network policy", "mechanism": "Embed C2PA/IPTC metadata; network policies vary.", "required": False},
}


def market_to_jurisdiction(market: str) -> str | None:
    m = market.upper()
    if m in JURISDICTIONS:
        return m
    if m in REGIONS["EU"]:
        return "EU"
    if m in {"GB"}:
        return "UK"
    return None


def _localized(code: str, base: dict[str, Any], group: str, fields: tuple[str, ...], locale: str) -> dict[str, Any]:
    out = dict(base)
    for f in fields:
        key = f"disclosure.{group}.{code}.{f}"
        if has(key, locale):
            out[f] = tr(key, locale)
    return out


def platform_catalog(locale: str = "en") -> dict[str, dict[str, Any]]:
    """The platform disclosure catalog with each platform's label and mechanism text in ``locale``."""
    return {code: _localized(code, p, "platform", ("label", "mechanism"), locale) for code, p in PLATFORMS.items()}


def required_labels(markets: list[str], channels: list[str], ai_generated: bool = True, lang: str = "en", locale: str = "en") -> dict[str, Any]:
    """What disclosure a campaign needs: burned-in badge, metadata credentials and platform toggles.

    ``lang`` is the CONTENT language (the wording of the burned-in badge); ``locale`` is the viewer's language for the descriptive text.
    The signed provenance manifest always stores the English (``locale="en"``) rendering.
    """
    juris = sorted({j for m in markets if (j := market_to_jurisdiction(m))})
    plats = [c.lower() for c in channels if c.lower() in PLATFORMS]
    burn_in = ai_generated and any(JURISDICTIONS[j]["badge"] and JURISDICTIONS[j]["required"] for j in juris)
    advised_badge = ai_generated and any(JURISDICTIONS[j]["badge"] for j in juris)
    return {
        "ai_generated": ai_generated,
        "jurisdictions": [{"code": j, **_localized(j, JURISDICTIONS[j], "juris", ("name", "basis"), locale)} for j in juris],
        "platforms": [{"code": p, **_localized(p, PLATFORMS[p], "platform", ("label", "mechanism"), locale)} for p in plats],
        "burn_in_required": burn_in,
        "burn_in_advised": advised_badge,
        "badge_text": BADGE_TEXT.get(lang, BADGE_TEXT["en"]),
        "metadata": [tr("disclosure.metadata.manifest", locale), tr("disclosure.metadata.iptc", locale)],
        "notice": tr("disclosure.notice", locale),
    }


def localize_labels(labels: dict[str, Any] | None, locale: str) -> dict[str, Any] | None:
    """A stored labels dict (e.g. inside a signed manifest) re-rendered for the viewer; the stored copy is never modified."""
    if not labels:
        return labels
    out = dict(labels)
    out["jurisdictions"] = [{**j, **_localized(j["code"], {}, "juris", ("name", "basis"), locale)} for j in labels.get("jurisdictions", [])]
    out["platforms"] = [{**p, **_localized(p["code"], {}, "platform", ("label", "mechanism"), locale)} for p in labels.get("platforms", [])]
    out["metadata"] = [tr("disclosure.metadata.manifest", locale), tr("disclosure.metadata.iptc", locale)]
    out["notice"] = tr("disclosure.notice", locale)
    return out
