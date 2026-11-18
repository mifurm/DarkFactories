"""Feature registry: every Release-1 feature self-registers; the catalog is the contract from the brief."""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter

EPICS = {
    "A": "Brand Brain & governance data",
    "B": "Creative pipeline (the crew)",
    "C": "Governance & safety",
    "D": "Performance & optimization",
    "E": "Platform",
}

# (id, name, epic, priority, ui_route, api_prefix)
CATALOG: list[tuple[str, str, str, str, str, str]] = [
    ("CS-01", "Brand Kit & Brand Brain", "A", "P0", "/brand-brain", "/api/brand"),
    ("CS-02", "Claims & Compliance Library", "A", "P0", "/claims", "/api/claims"),
    ("CS-03", "Rights & Consent Registry", "A", "P0", "/rights", "/api/rights"),
    ("CS-04", "Brief intake & Briefing agent", "B", "P0", "/campaigns/new", "/api/campaigns"),
    ("CS-05", "Strategy agent", "B", "P0", "/campaigns/:id/strategy", "/api/campaigns/{id}/strategy"),
    ("CS-06", "Script & Copy agent", "B", "P0", "/campaigns/:id/script", "/api/campaigns/{id}/script"),
    ("CS-07", "Storyboard & Art Direction agent", "B", "P0", "/campaigns/:id/storyboard", "/api/campaigns/{id}/storyboard"),
    ("CS-08", "Spot compositor / Video", "B", "P0", "/campaigns/:id/video", "/api/campaigns/{id}/spot"),
    ("CS-09", "Voice & audio agent", "B", "P0", "/campaigns/:id/audio", "/api/campaigns/{id}/audio"),
    ("CS-10", "Localization agent", "B", "P1", "/campaigns/:id/localization", "/api/campaigns/{id}/localization"),
    ("CS-11", "Format factory & versioning", "B", "P0", "/campaigns/:id/formats", "/api/campaigns/{id}/formats"),
    ("CS-12", "Brand Guardian", "C", "P0", "/guardian", "/api/guardian"),
    ("CS-13", "Approval workflow & audit trail", "C", "P0", "/approvals", "/api/approvals"),
    ("CS-14", "AI disclosure & provenance", "C", "P0", "/campaigns/:id/provenance", "/api/provenance"),
    ("CS-15", "Budget & cost guardrails", "C", "P0", "/cost", "/api/budget"),
    ("CS-16", "Pre-flight creative scorecard", "D", "P1", "/campaigns/:id/scorecard", "/api/campaigns/{id}/scorecard"),
    ("CS-17", "Variant engine & experimentation", "D", "P0", "/experiments", "/api/experiments"),
    ("CS-18", "Performance ingestion & insights", "D", "P0", "/performance", "/api/performance"),
    ("CS-19", "Campaign planner & media-mix hints", "D", "P2", "/planner", "/api/planner"),
    ("CS-20", "Studio UI", "E", "P0", "/", "/api/studio"),
    ("CS-21", "Asset library / DAM", "E", "P1", "/library", "/api/library"),
    ("CS-22", "Collaboration, roles & integrations", "E", "P1", "/team", "/api/team"),
    ("CS-23", "ROI & ACR calculator", "E", "P0", "/roi", "/api/roi"),
    ("CS-24", "Observability, security & IaC", "E", "P0", "/ops", "/api/ops"),
    ("CS-25", "Cinematic motion (generative video)", "B", "P0", "/campaigns/:id/video", "/api/motion"),
]


@dataclass
class Feature:
    id: str
    summary: str = ""
    router: APIRouter | None = None
    status: str = "implemented"
    extra: dict[str, Any] = field(default_factory=dict)


def discover() -> dict[str, Feature]:
    """Import every ``spotlight.features.<pkg>`` and collect the ``FEATURES`` / ``FEATURE`` it declares."""
    pkg = importlib.import_module("spotlight.features")
    found: dict[str, Feature] = {}
    for mod_info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda m: m.name):
        mod = importlib.import_module(f"spotlight.features.{mod_info.name}")
        feats = getattr(mod, "FEATURES", None)
        if feats is None and hasattr(mod, "FEATURE"):
            feats = [mod.FEATURE]
        for f in feats or []:
            found[f.id] = f
    return found


def registry_view(found: dict[str, Feature]) -> list[dict[str, Any]]:
    out = []
    for fid, name, epic, prio, ui, api in CATALOG:
        f = found.get(fid)
        out.append(
            {
                "id": fid,
                "name": name,
                "epic": epic,
                "epic_name": EPICS[epic],
                "priority": prio,
                "status": f.status if f else "planned",
                "ui_route": ui,
                "api_prefix": api,
                "summary": f.summary if f else "",
            }
        )
    return out
