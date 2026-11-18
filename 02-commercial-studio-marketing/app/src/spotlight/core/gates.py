"""Pipeline stage gates (CS-13) and campaign pipeline overview."""

from __future__ import annotations

import asyncio
from typing import Any

from ..i18n import label

GATES: list[dict[str, Any]] = [
    {"id": "brief", "label": "Brief", "kind": "brief", "roles": ["brand_manager"], "sla_hours": 24},
    {"id": "concept", "label": "Concept (strategy)", "kind": "strategy", "roles": ["creative_director"], "sla_hours": 48},
    {"id": "script", "label": "Script", "kind": "script", "roles": ["creative_director", "legal"], "sla_hours": 48},
    {"id": "storyboard", "label": "Storyboard", "kind": "storyboard", "roles": ["creative_director"], "sla_hours": 48},
    {"id": "final", "label": "Final spot", "kind": "spot", "roles": ["creative_director", "legal"], "sla_hours": 72},
]
GATE_BY_ID = {g["id"]: g for g in GATES}
GATE_BY_KIND = {g["kind"]: g for g in GATES}


async def stage_overview(st: Any, campaign_id: str) -> list[dict[str, Any]]:
    """Latest artifact per gate with its Guardian verdict and approval state (gate lookups run concurrently)."""
    camp = await st.campaign(campaign_id)
    approvals, *latest_by_gate = await asyncio.gather(
        st.repo.query("approvals", {"type": "approval"}, pk=campaign_id, order_by="created_at", desc=True),
        *[st.gate_artifact(camp, g["kind"]) for g in GATES],
    )
    out = []
    for g, latest in zip(GATES, latest_by_gate, strict=True):
        ap = next((a for a in approvals if latest and a["stage"] == g["id"] and a["artifact_id"] == latest["id"]), None)
        out.append(
            {
                "gate": g["id"],
                "label": label("label.gate", g["id"]),
                "roles": g["roles"],
                "artifact_id": latest["id"] if latest else None,
                "version": latest["version"] if latest else None,
                "artifact_status": latest["status"] if latest else "empty",
                "guardian": (latest or {}).get("guardian"),
                "approval_id": ap["id"] if ap else None,
                "approval_state": ap["state"] if ap else None,
                "approvals_in": ap.get("decisions", []) if ap else [],
            }
        )
    return out
