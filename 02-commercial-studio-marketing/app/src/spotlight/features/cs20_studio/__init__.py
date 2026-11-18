"""CS-20 Studio UI — backend side: dashboard overview, activity feed and demo administration (reseed / reset)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request

from ...core.gates import stage_overview
from ...deps import mutate_limit, svc
from ...domain.rights import RightsEntry, expiring
from ...registry import Feature
from ...roles import Actor, require
from ...seed import ensure_seeded, reset_demo
from ..common import studio

router = APIRouter(tags=["CS-20 Studio UI"])


@router.get("/api/studio/overview")
async def overview(request: Request) -> dict[str, Any]:
    s = svc(request)
    st = studio(request)
    camps, assets, arts, approvals, rights_rows, spend_today, exps, jobs = await asyncio.gather(
        st.repo.query("campaigns", order_by="created_at", desc=True, limit=50),
        st.repo.query("assets", limit=2000, fields=("id", "kind", "status")),
        st.repo.query("artifacts", limit=3000, fields=("id", "kind", "status", "campaign_id", "guardian")),
        st.repo.query("approvals", {"type": "approval"}, limit=300, fields=("id", "state")),
        st.repo.query("rights", pk="northwind"),
        s.meter.today_total(),
        st.repo.query("experiments", limit=20, fields=("id", "name", "status", "campaign_id", "leader")),
        s.jobs.list(None, 8),
    )
    rights = [RightsEntry(**{k: v for k, v in r.items() if k in RightsEntry.model_fields}) for r in rights_rows]
    spots = [a for a in arts if a["kind"] == "spot"]
    approved_video = [a for a in assets if a["kind"] == "video" and a.get("status") == "approved"]

    async def card(c: dict[str, Any]) -> dict[str, Any]:
        spent, pipe = await asyncio.gather(s.meter.campaign_total(c["id"]), stage_overview(st, c["id"]))
        return {
            "id": c["id"], "name": c["name"], "status": c.get("status"), "stage": c.get("stage"), "markets": c.get("markets", []), "channels": c.get("channels", []),
            "history": c.get("history", False), "spent_usd": spent,
            "pipeline": [{"gate": p["gate"], "label": p["label"], "state": p["approval_state"] or p["artifact_status"], "verdict": (p["guardian"] or {}).get("verdict")} for p in pipe],
            "spots": sum(1 for a in spots if a["campaign_id"] == c["id"]),
        }

    cards = list(await asyncio.gather(*[card(c) for c in camps]))
    total_spend = sum(c["spent_usd"] for c in cards)
    from ...core.ai.meter import cost_per_approved_asset

    return {
        "kpis": {
            "campaigns": len(camps), "assets": len(assets), "spots_rendered": len(spots), "approved_videos": len(approved_video),
            "pending_approvals": sum(1 for a in approvals if a["state"] == "pending"), "ai_spend_today_usd": spend_today, "ai_spend_total_usd": round(total_spend, 4),
            "guardian_blocks_open": sum(1 for a in arts if (a.get("guardian") or {}).get("blocks", 0) > 0 and a.get("status") != "approved"),
            **{f"cost_{k}": v for k, v in cost_per_approved_asset(total_spend, len(approved_video)).items()},
        },
        "campaigns": cards,
        "rights_alerts": expiring(rights, 45),
        "experiments": [{"id": e["id"], "name": e["name"], "status": e["status"], "campaign_id": e["campaign_id"], "leader": e.get("leader")} for e in exps],
        "jobs": jobs,
        "synthetic_data": True,
        "mode": s.settings.mode,
    }


@router.get("/api/studio/activity")
async def activity(request: Request, limit: int = 25) -> dict[str, Any]:
    st = studio(request)
    s = svc(request)
    chains = ["global", *[c["id"] for c in await st.repo.query("campaigns")]]
    names = {c["id"]: c["name"] for c in await st.repo.query("campaigns")}
    rows: list[dict[str, Any]] = []
    for ch in chains:
        for e in (await s.audit.entries(ch))[-15:]:
            rows.append({"ts": e["ts"], "chain": ch, "campaign": names.get(ch), "action": e["action"], "actor": e["actor"], "data": e.get("data", {})})
    rows.sort(key=lambda r: r["ts"], reverse=True)
    return {"activity": rows[: min(limit, 100)]}


@router.post("/api/admin/reseed", dependencies=[Depends(mutate_limit)])
async def reseed(request: Request, reset: bool = False, actor: Actor = Depends(require("admin"))) -> dict[str, Any]:
    """Load/refresh the synthetic Northwind sample data (idempotent); ``reset=true`` also wipes generated demo state."""
    s = svc(request)
    out = await reset_demo(s) if reset else await ensure_seeded(s, force=True)
    await studio(request).audit(None, actor, "admin.reseed", {}, {"reset": reset})
    return out


FEATURE = Feature(id="CS-20", summary="Campaign dashboard, brief wizard, Brand Brain console, creative workspace, Guardian report, approvals inbox, library, experiments, performance, cost meter, ROI calculator — polished editorial UI.", router=router)
