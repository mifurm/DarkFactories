"""CS-03 Rights & Consent Registry — talent likeness/voice consent, licensed music/stock, windows, territories, channels."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...deps import mutate_limit
from ...domain.rights import RightsEntry, check_use, expiring, find_entry, is_cleared
from ...errors import NotFound
from ...registry import Feature
from ...roles import Actor, require
from ...util import new_id
from ..common import studio

router = APIRouter(prefix="/api/rights", tags=["CS-03 Rights & Consent"])
BRAND = "northwind"


class RightsIn(BaseModel):
    kind: str = Field(pattern="^(music|talent|stock|font|other)$")
    title: str = Field(min_length=2, max_length=160)
    licensor: str | None = Field(default=None, max_length=160)
    status: str = Field(default="active", pattern="^(active|pending|revoked)$")
    territories: list[str] = Field(default_factory=lambda: ["WW"])
    channels: list[str] = Field(default_factory=list)
    valid_from: str | None = None
    valid_to: str | None = None
    ai_voice_consent: bool = False
    ai_likeness_consent: bool = False
    usage_notes: str = Field(default="", max_length=500)
    aliases: list[str] = Field(default_factory=list)


async def _registry(request: Request) -> list[RightsEntry]:
    rows = await studio(request).repo.query("rights", pk=BRAND)
    return [RightsEntry(**{k: v for k, v in r.items() if k in RightsEntry.model_fields}) for r in rows]


@router.get("")
async def list_rights(request: Request, kind: str | None = None, status: str | None = None) -> dict[str, Any]:
    reg = await _registry(request)
    rows = await studio(request).repo.query("rights", pk=BRAND)
    rows = [r for r in rows if (not kind or r["kind"] == kind) and (not status or r["status"] == status)]
    rows.sort(key=lambda r: (r["kind"], r["title"]))
    exp = {e["id"]: e for e in expiring(reg, 45)}
    for r in rows:
        r["expiry"] = exp.get(r["id"])
    return {"entries": rows, "alerts": list(exp.values()), "counts": {k: sum(1 for r in rows if r["kind"] == k) for k in ("music", "talent", "stock", "font", "other")}}


@router.post("", dependencies=[Depends(mutate_limit)])
async def create_entry(request: Request, body: RightsIn, actor: Actor = Depends(require("rights.write"))) -> dict[str, Any]:
    st = studio(request)
    doc = await st.repo.upsert("rights", {**body.model_dump(), "id": new_id("rts"), "brand_id": BRAND, "pk": BRAND})
    await st.audit(None, actor, "rights.created", {"rights_id": doc["id"]}, {"kind": body.kind, "title": body.title})
    return doc


@router.put("/{rights_id}", dependencies=[Depends(mutate_limit)])
async def update_entry(request: Request, rights_id: str, body: RightsIn, actor: Actor = Depends(require("rights.write"))) -> dict[str, Any]:
    st = studio(request)
    cur = await st.repo.get("rights", rights_id, pk=BRAND)
    if not cur:
        raise NotFound("rights entry not found", code="rights_not_found")
    doc = await st.repo.upsert("rights", {**cur, **body.model_dump()})
    await st.audit(None, actor, "rights.updated", {"rights_id": rights_id})
    return doc


@router.post("/{rights_id}/revoke", dependencies=[Depends(mutate_limit)])
async def revoke(request: Request, rights_id: str, actor: Actor = Depends(require("rights.write"))) -> dict[str, Any]:
    st = studio(request)
    cur = await st.repo.get("rights", rights_id, pk=BRAND)
    if not cur:
        raise NotFound("rights entry not found", code="rights_not_found")
    cur["status"] = "revoked"
    await st.repo.upsert("rights", cur)
    await st.audit(None, actor, "rights.revoked", {"rights_id": rights_id}, {"title": cur["title"]})
    await request.app.state.services.notifier.emit("rights.revoked", {"rights_id": rights_id, "title": cur["title"]})
    return cur


class UseIn(BaseModel):
    kind: str = Field(pattern="^(music|talent|stock|font|other)$")
    title: str | None = None
    rights_id: str | None = None
    markets: list[str] = Field(default_factory=lambda: ["US"])
    channels: list[str] = Field(default_factory=list)
    air_start: str | None = None
    air_end: str | None = None
    ai_synthesis: bool = False
    usage: str = "voice"


@router.post("/check")
async def check_use_endpoint(request: Request, body: UseIn) -> dict[str, Any]:
    """Would this use be cleared? Blocks assets/uses outside rights (territory, window, channel, AI consent)."""
    reg = await _registry(request)
    e = find_entry(reg, body.kind, body.title, body.rights_id)
    if e is None:
        return {"cleared": False, "entry": None, "verdicts": [{"ok": False, "code": "rights.unlicensed", "severity": "block", "message": f"No {body.kind} record for “{body.title or body.rights_id}” in the registry"}]}
    verdicts = check_use(e, body.markets, body.channels, body.air_start, body.air_end, ai_synthesis=body.ai_synthesis, usage=body.usage)
    return {"cleared": is_cleared(verdicts), "entry": e.model_dump(), "verdicts": [v.model_dump() for v in verdicts]}


@router.get("/alerts")
async def alerts(request: Request, days: int = 30) -> dict[str, Any]:
    return {"within_days": days, "alerts": expiring(await _registry(request), min(max(days, 1), 365))}


@router.post("/alerts/notify", dependencies=[Depends(mutate_limit)])
async def notify_alerts(request: Request, days: int = 30, actor: Actor = Depends(require("rights.write"))) -> dict[str, Any]:
    al = expiring(await _registry(request), days)
    for a in al:
        await request.app.state.services.notifier.emit("rights.expiring", a)
    return {"notified": len(al)}


FEATURE = Feature(id="CS-03", summary="Talent likeness/voice consent, licensed music/stock, windows, territories, channel limits; expiry alerts; blocks out-of-rights use.", router=router)
