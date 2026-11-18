"""CS-19 Campaign planner & media-mix hints — recommended channel/budget split with expected reach/ROAS ranges (illustrative)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...deps import mutate_limit
from ...domain import planner as pl
from ...errors import ValidationFailed
from ...i18n import label, t
from ...registry import Feature
from ...roles import Actor, require
from ...util import new_id, now_iso
from ..common import studio

router = APIRouter(prefix="/api/planner", tags=["CS-19 Campaign Planner"])


@router.get("/channels")
async def channels() -> dict[str, Any]:
    return {"channels": pl.CHANNELS, "labels": {c: label("label.channel", c) for c in pl.CHANNELS}, "note": t("planner.note.channels")}


class PlanIn(BaseModel):
    budget_usd: float = Field(gt=1000, le=50_000_000)
    objective: str = Field(default="roas", pattern="^(roas|reach|conversions)$")
    channels: list[str] | None = None
    min_share: float = Field(default=0.0, ge=0, le=0.2)
    campaign_id: str | None = None
    seed: int = Field(default=7, ge=1, le=10_000)


def _localized_plan(result: dict[str, Any]) -> dict[str, Any]:
    """A stored plan with its note and channel names rendered in the viewer's language (channel ids and numbers are unchanged)."""
    return {**result, "note": t("planner.note.plan"), "allocation": [{**row, "label": label("label.channel", row["channel"])} for row in result["allocation"]]}


@router.post("/plan", dependencies=[Depends(mutate_limit)])
async def make_plan(request: Request, body: PlanIn, actor: Actor = Depends(require("campaign.write"))) -> dict[str, Any]:
    bad = [c for c in (body.channels or []) if c not in pl.CHANNELS]
    if bad:
        raise ValidationFailed(f"unknown channel(s) {bad}", code="bad_channel", params={"channels": ", ".join(bad)})
    chans = body.channels or list(pl.CHANNELS)
    if len(chans) * body.min_share > 0.95:
        raise ValidationFailed("min_share × channels exceeds the budget", code="bad_min_share")
    out = pl.plan(body.budget_usd, chans, "roas" if body.objective == "conversions" else body.objective, body.seed, min_share=body.min_share)
    base = pl.uniform_baseline(body.budget_usd, chans)
    out["vs_uniform_split"] = {"uniform_revenue": round(base), "optimised_revenue": out["totals"]["revenue"], "uplift_pct": round((out["totals"]["revenue"] / base - 1) * 100, 1) if base else None}
    doc = {"id": new_id("plan"), "pk": body.campaign_id or "global", "campaign_id": body.campaign_id, "input": body.model_dump(), "result": out, "created_at": now_iso(), "created_by": actor.name}
    await studio(request).repo.upsert("plans", doc)
    return {"id": doc["id"], **_localized_plan(out)}


@router.get("/plans")
async def plans(request: Request, campaign_id: str | None = None) -> list[dict[str, Any]]:
    rows = await studio(request).repo.query("plans", {"campaign_id": campaign_id} if campaign_id else None, order_by="created_at", desc=True, limit=20)
    return [{"id": r["id"], "created_at": r["created_at"], "input": r["input"], "totals": r["result"]["totals"], "ranges": r["result"]["ranges"]} for r in rows]


FEATURE = Feature(id="CS-19", summary="Channel/budget split via diminishing-returns curves and marginal-ROAS allocation, with p10–p90 ROAS ranges — labelled illustrative.", router=router)
