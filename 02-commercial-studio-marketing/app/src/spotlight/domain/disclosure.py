"""AI disclosure labels per jurisdiction / platform (CS-14). Illustrative rules — validate with counsel."""

from __future__ import annotations

from typing import Any

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


def required_labels(markets: list[str], channels: list[str], ai_generated: bool = True, lang: str = "en") -> dict[str, Any]:
    """What disclosure a campaign needs: burned-in badge, metadata credentials and platform toggles."""
    juris = sorted({j for m in markets if (j := market_to_jurisdiction(m))})
    plats = [c.lower() for c in channels if c.lower() in PLATFORMS]
    burn_in = ai_generated and any(JURISDICTIONS[j]["badge"] and JURISDICTIONS[j]["required"] for j in juris)
    advised_badge = ai_generated and any(JURISDICTIONS[j]["badge"] for j in juris)
    return {
        "ai_generated": ai_generated,
        "jurisdictions": [{"code": j, **JURISDICTIONS[j]} for j in juris],
        "platforms": [{"code": p, **PLATFORMS[p]} for p in plats],
        "burn_in_required": burn_in,
        "burn_in_advised": advised_badge,
        "badge_text": BADGE_TEXT.get(lang, BADGE_TEXT["en"]),
        "metadata": ["c2pa-style manifest + sidecar JSON", "IPTC DigitalSourceType = trainedAlgorithmicMedia"],
        "notice": "Illustrative disclosure rules — validate with legal counsel for each market/platform.",
    }
