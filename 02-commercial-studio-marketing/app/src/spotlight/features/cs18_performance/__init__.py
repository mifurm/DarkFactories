"""CS-18 Performance ingestion & insights — CSV upload + simulated ad-platform connectors (Google/Meta/TikTok/LinkedIn interface),
impressions/CTR/VTR/CVR/CPA/ROAS, insight generation written back to the Brand Brain."""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, Field

from ...deps import mutate_limit
from ...domain import perfsim as ps
from ...domain.perfsim import localize_learning
from ...errors import PayloadTooLarge, ValidationFailed
from ...i18n import current_locale, t
from ...registry import Feature
from ...roles import Actor, require
from ...util import new_id, now_iso
from ..common import studio
from ..cs01_brand_brain import add_learning

router = APIRouter(prefix="/api/performance", tags=["CS-18 Performance & Insights"])
HISTORY_VARIANTS = [
    {"id": f"mb-{i}", "attrs": {"hook": h, "cta": c, "visual": v}}
    for i, (h, c, v) in enumerate([("Human moment first", "Find it near you", "Warm kitchen"), ("Product first", "Find it near you", "Warm kitchen"), ("Question hook", "Try it today", "Street at dawn"), ("Sensory close-up", "Try it today", "Macro pour"), ("Human moment first", "Try it today", "Street at dawn"), ("Product first", "Learn more", "Street at dawn")], start=1)
]


class AdPlatformConnector(Protocol):
    """Interface every platform connector implements (Google Ads, Meta, TikTok, LinkedIn…). Production connectors run in Azure Functions."""

    platform: str

    def fetch(self, campaign_id: str, variants: list[dict[str, Any]], days: int, seed: int) -> list[dict[str, Any]]: ...


class SimulatedConnector:
    """Deterministic simulator behind the connector interface — the real connectors would call the platform reporting APIs."""

    def __init__(self, platform: str) -> None:
        self.platform = platform

    def fetch(self, campaign_id: str, variants: list[dict[str, Any]], days: int, seed: int) -> list[dict[str, Any]]:
        return ps.generate_history(variants, days, [self.platform], seed + hash(self.platform) % 1000, impressions_per_day=4000)


CONNECTORS = {p: SimulatedConnector(p) for p in ["google", "meta", "tiktok", "linkedin", "youtube"]}


@router.get("/connectors")
async def connectors() -> dict[str, Any]:
    return {"connectors": [{"platform": p, "mode": "simulated", "interface": "AdPlatformConnector.fetch(campaign_id, variants, days, seed)", "production": t("perf.connector.production")} for p in CONNECTORS], "csv_columns": ["date", "platform", "variant_id", "impressions", "clicks", "views", "completes", "conversions", "spend", "revenue"]}


async def _variants_for(st: Any, campaign_id: str) -> list[dict[str, Any]]:
    exps = await st.repo.query("experiments", {"campaign_id": campaign_id}, pk=campaign_id, order_by="created_at", desc=True, limit=1)
    if exps:
        return [{"id": v["id"], "attrs": v["attrs"]} for v in exps[0]["variants"]]
    return HISTORY_VARIANTS


async def _store(st: Any, campaign_id: str, rows: list[dict[str, Any]], source: str, attrs_by_id: dict[str, dict[str, Any]] | None = None) -> int:
    docs = []
    for r in rows:
        r = {**r}
        if attrs_by_id and not r.get("attrs"):
            r["attrs"] = attrs_by_id.get(r["variant_id"], {})
        docs.append({**r, "id": new_id("prf"), "pk": campaign_id, "campaign_id": campaign_id, "source": source})
    return await st.repo.upsert_many("performance", docs)


async def _rows(st: Any, campaign_id: str | None) -> list[dict[str, Any]]:
    return await st.repo.query("performance", {"campaign_id": campaign_id} if campaign_id else None, pk=campaign_id, limit=20000)


@router.get("")
async def metrics(request: Request, campaign_id: str | None = None, group_by: str | None = None) -> dict[str, Any]:
    st = studio(request)
    rows = await _rows(st, campaign_id)
    allowed = {None, "variant_id", "platform", "date", "source", "hook", "cta", "visual", "segment"}
    if group_by not in allowed:
        raise ValidationFailed(f"group_by must be one of {sorted(x for x in allowed if x)}", code="bad_group", params={"allowed": ", ".join(sorted(x for x in allowed if x))})
    total = ps.aggregate(rows, None)
    return {"campaign_id": campaign_id, "rows": len(rows), "totals": total[0] if total else None, "groups": ps.aggregate(rows, group_by or "platform"), "group_by": group_by or "platform", "by_day": sorted(ps.aggregate(rows, "date"), key=lambda r: r["key"]), "sources": sorted({r.get("source", "?") for r in rows}), "simulated": True}


@router.post("/ingest/csv", dependencies=[Depends(mutate_limit)])
async def ingest_csv(request: Request, campaign_id: str = Form(...), file: UploadFile = File(...), actor: Actor = Depends(require("performance.write"))) -> dict[str, Any]:
    s = request.app.state.services
    st = studio(request)
    await st.campaign(campaign_id)
    data = await file.read(s.settings.max_upload_bytes + 1)
    if len(data) > s.settings.max_upload_bytes:
        raise PayloadTooLarge("CSV exceeds the upload limit", key="err.payload_too_large.csv")
    rows, errors = ps.parse_csv(data.decode("utf-8-sig", errors="replace"))
    if not rows:
        raise ValidationFailed("No valid rows: " + "; ".join(errors[:3]), code="bad_csv", details={"errors": errors}, params={"errors": "; ".join(errors[:3])})
    attrs = {v["id"]: v["attrs"] for v in await _variants_for(st, campaign_id)}
    n = await _store(st, campaign_id, rows, "csv", attrs)
    await st.audit(campaign_id, actor, "performance.csv_ingested", {"campaign_id": campaign_id}, {"rows": n, "errors": len(errors)})
    return {"ingested": n, "errors": errors, "totals": ps.aggregate(rows, None)[0]}


class SyncIn(BaseModel):
    campaign_id: str
    days: int = Field(default=7, ge=1, le=60)
    seed: int = Field(default=11, ge=1, le=10_000)


@router.post("/connectors/{platform}/sync", dependencies=[Depends(mutate_limit)])
async def sync(request: Request, platform: str, body: SyncIn, actor: Actor = Depends(require("performance.write"))) -> dict[str, Any]:
    conn = CONNECTORS.get(platform)
    if not conn:
        raise ValidationFailed(f"unknown connector {platform!r}", code="bad_connector", params={"platform": repr(platform)})
    st = studio(request)
    await st.campaign(body.campaign_id)
    variants = await _variants_for(st, body.campaign_id)
    rows = conn.fetch(body.campaign_id, variants, body.days, body.seed)
    n = await _store(st, body.campaign_id, rows, f"connector:{platform}")
    await st.audit(body.campaign_id, actor, "performance.connector_synced", {"platform": platform}, {"rows": n, "days": body.days})
    return {"platform": platform, "mode": "simulated", "ingested": n, "totals": ps.aggregate(rows, None)[0]}


class InsightIn(BaseModel):
    campaign_id: str | None = None
    min_impressions: int = Field(default=20000, ge=1000)


@router.post("/insights/generate", dependencies=[Depends(mutate_limit)])
async def generate_insights(request: Request, body: InsightIn | None = None, actor: Actor = Depends(require("performance.write"))) -> dict[str, Any]:
    """Statistical 'what works' analysis; each significant finding is written to the Brand Brain as a learning."""
    body = body or InsightIn()
    s = request.app.state.services
    st = studio(request)
    rows = await _rows(st, body.campaign_id)
    if not rows:
        raise ValidationFailed("No performance data yet — upload a CSV or sync a connector first.", code="no_data")
    ins = ps.insights_from_rows(rows, min_impressions=body.min_impressions)
    existing = {x["statement"] for x in await st.repo.query("learnings", pk="northwind")}
    written = []
    for i in ins[:8]:
        if i["statement"] in existing:
            continue
        doc = await add_learning(s, "northwind", i["statement"], {"dimension": i["dimension"], "winner": i["winner"], "metric": i["metric"], "lift_pct": i["lift_pct"], "p_value": i["p_value"], "n": i["n"]}, i["confidence"], "performance", body.campaign_id)
        written.append(doc["id"])
    await st.audit(body.campaign_id, actor, "performance.insights_generated", {"campaign_id": body.campaign_id}, {"insights": len(ins), "written_to_brand_brain": len(written)})
    lang = current_locale()
    return {"insights": [{**i, "statement": ps.render_statement(i, lang) or i["statement"], "statement_en": i["statement"]} if lang != "en" else i for i in ins], "written_to_brand_brain": len(written), "rows_analysed": len(rows)}


@router.get("/insights")
async def list_insights(request: Request, campaign_id: str | None = None) -> dict[str, Any]:
    rows = await studio(request).repo.query("learnings", {"source": "performance", **({"campaign_id": campaign_id} if campaign_id else {})}, pk="northwind", order_by="created_at", desc=True, limit=50)
    return {"insights": [localize_learning(r, current_locale()) for r in rows]}


async def seed_history(s: Any) -> None:
    """Synthetic history for the 'Midnight Blend' campaign + the learnings it produced (idempotent)."""
    if await s.repo.get("settings", "perf_seed", pk="tenant"):
        return
    if not await s.repo.get("campaigns", "midnight-blend-winter", pk="midnight-blend-winter"):
        return
    rows = ps.generate_history(HISTORY_VARIANTS, 21, ["meta", "tiktok", "youtube"], seed=2026)
    attrs = {v["id"]: v["attrs"] for v in HISTORY_VARIANTS}
    await s.repo.upsert_many("performance", [{**r, "id": new_id("prf"), "pk": "midnight-blend-winter", "campaign_id": "midnight-blend-winter", "source": "seed-history", "attrs": attrs[r["variant_id"]]} for r in rows])
    existing = {x["statement"] for x in await s.repo.query("learnings", pk="northwind")}
    for i in ps.insights_from_rows(rows, ["hook", "cta", "visual", "platform"])[:4]:
        if i["statement"] not in existing:
            await add_learning(s, "northwind", i["statement"], {k: i[k] for k in ("dimension", "winner", "metric", "lift_pct", "p_value", "n")} | {"synthetic_history": True}, i["confidence"], "performance", "midnight-blend-winter")
    await s.repo.upsert("settings", {"id": "perf_seed", "pk": "tenant", "at": now_iso(), "rows": len(rows)})


__all__ = ["np"]
FEATURE = Feature(id="CS-18", summary="CSV upload + simulated ad-platform connectors; impressions, CTR, VTR, CVR, CPA, ROAS by variant/platform/day; statistical insights written back to the Brand Brain.", router=router, extra={"startup": seed_history})
