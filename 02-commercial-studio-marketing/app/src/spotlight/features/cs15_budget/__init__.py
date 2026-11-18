"""CS-15 Budget & cost guardrails — metering (tokens/images/TTS/render) -> $, per-campaign/per-day caps, alerts, premium approval,
cost per approved asset vs agency baseline."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...core.ai.meter import cost_per_approved_asset
from ...core.ai.pricing import (
    AGENCY_BASELINE_PER_ASSET_USD,
    IMAGE_PER_IMAGE,
    LLM_PER_MTOK,
    PRICES_AS_OF,
    PRICING_NOTE,
    TTS_PER_MCHAR,
)
from ...deps import mutate_limit, svc
from ...errors import ValidationFailed
from ...registry import Feature
from ...roles import Actor, require
from ...util import now_iso, today_utc
from ..common import studio

router = APIRouter(tags=["CS-15 Budget & Cost"])
HARD_MAX_DAILY = 50.0


@router.get("/api/budget")
async def overview(request: Request) -> dict[str, Any]:
    s = svc(request)
    st = studio(request)
    summary, caps, camps = await asyncio.gather(s.meter.summary(), s.guard.caps(), st.repo.query("campaigns"))

    async def row(c: dict[str, Any]) -> dict[str, Any]:
        spend, approved = await asyncio.gather(s.meter.campaign_total(c["id"]), st.repo.count("assets", {"kind": "video", "status": "approved", "campaign_id": c["id"]}))
        cap = float(c.get("budget_cap_usd") or s.settings.campaign_ai_budget_usd)
        return {"campaign_id": c["id"], "name": c["name"], "spent_usd": spend, "cap_usd": cap, "approved_assets": approved, "premium_approved": bool(c.get("premium_approved")), **cost_per_approved_asset(spend, approved)}

    per_campaign = list(await asyncio.gather(*[row(c) for c in camps]))
    total_spend = sum(r["spent_usd"] for r in per_campaign)
    total_approved = sum(r["approved_assets"] for r in per_campaign)
    return {
        "today": summary,
        "caps": caps,
        "campaigns": per_campaign,
        "kpi": cost_per_approved_asset(total_spend, total_approved),
        "alerts": [a for a in list(s.notifier.recent) if a["event"] == "budget.alert"][:10],
        "pricing": {"as_of": PRICES_AS_OF, "note": PRICING_NOTE, "agency_baseline_per_asset_usd": AGENCY_BASELINE_PER_ASSET_USD, "llm_per_mtok": {k: {"input": v[0], "cached": v[1], "output": v[2]} for k, v in LLM_PER_MTOK.items()}, "tts_per_mchar": TTS_PER_MCHAR, "image_per_image": {f"{m}/{q}/{c}": p for (m, q, c), p in IMAGE_PER_IMAGE.items()}},
        "guard": {"active": True, "refusals": s.guard.refusals, "fails_closed": True, "hard_max_daily_usd": HARD_MAX_DAILY},
        "simulated_prices": s.meter.simulated,
    }


@router.get("/api/budget/events")
async def events(request: Request, campaign_id: str | None = None, day: str | None = None, limit: int = 100) -> dict[str, Any]:
    rows = await svc(request).meter.events(day=day or (None if campaign_id else today_utc()), campaign_id=campaign_id, limit=min(limit, 300))
    return {"events": rows}


class CapIn(BaseModel):
    daily_cap_usd: float = Field(gt=0, le=HARD_MAX_DAILY)


@router.put("/api/budget/caps", dependencies=[Depends(mutate_limit)])
async def set_daily_cap(request: Request, body: CapIn, actor: Actor = Depends(require("admin"))) -> dict[str, Any]:
    s = svc(request)
    s.guard.daily_cap = body.daily_cap_usd
    await s.repo.upsert("settings", {"id": "budget", "pk": "tenant", "daily_cap_usd": body.daily_cap_usd, "by": actor.name, "at": now_iso()})
    await studio(request).audit(None, actor, "budget.daily_cap_changed", {"scope": "daily"}, {"daily_cap_usd": body.daily_cap_usd})
    return await s.guard.caps()


class CampaignCapIn(BaseModel):
    cap_usd: float = Field(gt=0, le=HARD_MAX_DAILY)


@router.put("/api/campaigns/{campaign_id}/budget", dependencies=[Depends(mutate_limit)])
async def set_campaign_cap(request: Request, campaign_id: str, body: CampaignCapIn, actor: Actor = Depends(require("budget.write"))) -> dict[str, Any]:
    st = studio(request)
    c = await st.campaign(campaign_id)
    c["budget_cap_usd"] = body.cap_usd
    await st.save_campaign(c)
    await st.audit(campaign_id, actor, "budget.campaign_cap_changed", {"campaign_id": campaign_id}, {"cap_usd": body.cap_usd})
    return await svc(request).guard.caps(campaign_id)


class PremiumIn(BaseModel):
    approved: bool
    note: str = Field(default="", max_length=300)


@router.post("/api/campaigns/{campaign_id}/premium", dependencies=[Depends(mutate_limit)])
async def premium(request: Request, campaign_id: str, body: PremiumIn, actor: Actor = Depends(require("premium.approve"))) -> dict[str, Any]:
    """Premium (hero-quality) generation costs up to ~$0.20 per image — it needs an explicit approval per campaign."""
    st = studio(request)
    c = await st.campaign(campaign_id)
    if body.approved and float(c.get("budget_cap_usd") or 0) < 0.5:
        raise ValidationFailed("Raise the campaign cap to at least $0.50 before approving premium generation.", code="cap_too_low")
    c["premium_approved"] = body.approved
    await st.save_campaign(c)
    await st.audit(campaign_id, actor, "budget.premium_" + ("approved" if body.approved else "revoked"), {"campaign_id": campaign_id}, {"note": body.note})
    return {"campaign_id": campaign_id, "premium_approved": body.approved}


async def load_budget_settings(s: Any) -> None:
    doc = await s.repo.get("settings", "budget", pk="tenant")
    if doc and 0 < float(doc.get("daily_cap_usd", 0)) <= HARD_MAX_DAILY:
        s.guard.daily_cap = float(doc["daily_cap_usd"])


FEATURE = Feature(id="CS-15", summary="Metering of tokens/images/TTS/render -> $, daily + per-campaign caps that fail closed, alerts, premium-generation approval, cost per approved asset vs agency baseline.", router=router, extra={"startup": load_budget_settings})
