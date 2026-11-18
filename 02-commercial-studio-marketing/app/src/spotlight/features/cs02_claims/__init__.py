"""CS-02 Claims & Compliance Library — approved / prohibited / needs-substantiation claims per market & category."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...deps import mutate_limit
from ...domain.claims import ClaimRule, find_hits, market_matches, unsatisfied_disclaimers
from ...errors import NotFound, ValidationFailed
from ...registry import Feature
from ...roles import Actor, require
from ...util import new_id
from ..common import studio

router = APIRouter(prefix="/api/claims", tags=["CS-02 Claims & Compliance"])
BRAND = "northwind"


class ClaimIn(BaseModel):
    text: str = Field(min_length=3, max_length=300)
    type: str = Field(pattern="^(approved|prohibited|needs_substantiation)$")
    markets: list[str] = Field(default_factory=lambda: ["*"])
    categories: list[str] = Field(default_factory=lambda: ["*"])
    patterns: list[str] = Field(default_factory=list, max_length=20)
    required_disclaimer: str | None = Field(default=None, max_length=300)
    substantiation_url: str | None = Field(default=None, max_length=300)
    alternative: str | None = Field(default=None, max_length=300)
    severity: str = Field(default="block", pattern="^(block|warn)$")
    notes: str = Field(default="", max_length=500)
    rule_pack: str | None = None


def _check_patterns(patterns: list[str]) -> None:
    import re

    for p in patterns:
        if p.startswith("re:"):
            if len(p) > 400:
                raise ValidationFailed("regex too long", code="bad_pattern")
            try:
                re.compile(p[3:])
            except re.error as exc:
                raise ValidationFailed(f"invalid regex: {exc}", code="bad_pattern") from exc


@router.get("")
async def list_claims(request: Request, type: str | None = None, market: str | None = None, category: str | None = None, q: str | None = None) -> dict[str, Any]:
    rows = await studio(request).repo.query("claims", pk=BRAND)
    out = []
    for r in rows:
        if type and r["type"] != type:
            continue
        if market and not market_matches(r["markets"], [market.upper()]):
            continue
        if category and "*" not in r["categories"] and category.lower() not in [c.lower() for c in r["categories"]]:
            continue
        if q and q.lower() not in (r["text"] + " " + r.get("notes", "")).lower():
            continue
        out.append(r)
    out.sort(key=lambda r: (r["type"], r["text"]))
    counts = {t: sum(1 for r in rows if r["type"] == t) for t in ("approved", "prohibited", "needs_substantiation")}
    return {"claims": out, "counts": counts, "categories": sorted({c for r in rows for c in r["categories"]}), "packs": sorted({r["rule_pack"] for r in rows if r.get("rule_pack")})}


@router.post("", dependencies=[Depends(mutate_limit)])
async def create_claim(request: Request, body: ClaimIn, actor: Actor = Depends(require("claims.write"))) -> dict[str, Any]:
    _check_patterns(body.patterns)
    st = studio(request)
    doc = {**body.model_dump(), "id": new_id("clm"), "brand_id": BRAND, "pk": BRAND}
    doc = await st.repo.upsert("claims", doc)
    await st.audit(None, actor, "claims.created", {"claim_id": doc["id"]}, {"type": body.type, "text": body.text})
    return doc


@router.put("/{claim_id}", dependencies=[Depends(mutate_limit)])
async def update_claim(request: Request, claim_id: str, body: ClaimIn, actor: Actor = Depends(require("claims.write"))) -> dict[str, Any]:
    _check_patterns(body.patterns)
    st = studio(request)
    cur = await st.repo.get("claims", claim_id, pk=BRAND)
    if not cur:
        raise NotFound("claim not found", code="claim_not_found")
    doc = await st.repo.upsert("claims", {**cur, **body.model_dump()})
    await st.audit(None, actor, "claims.updated", {"claim_id": claim_id}, {"type": body.type})
    return doc


@router.delete("/{claim_id}", dependencies=[Depends(mutate_limit)])
async def delete_claim(request: Request, claim_id: str, actor: Actor = Depends(require("claims.write"))) -> dict[str, Any]:
    st = studio(request)
    if not await st.repo.delete("claims", claim_id, pk=BRAND):
        raise NotFound("claim not found", code="claim_not_found")
    await st.audit(None, actor, "claims.deleted", {"claim_id": claim_id})
    return {"deleted": claim_id}


class CheckIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    market: list[str] = Field(default_factory=lambda: ["US"])
    category: str = "beverage"
    supporting_text: str = Field(default="", max_length=2000)


@router.post("/check")
async def check_text(request: Request, body: CheckIn) -> dict[str, Any]:
    """Run the claims engine on arbitrary text (what the Brand Guardian uses for the claims + regulated checks)."""
    rules = [ClaimRule(**{k: v for k, v in r.items() if k in ClaimRule.model_fields}) for r in await studio(request).repo.query("claims", pk=BRAND)]
    hits = find_hits(body.text, rules, body.market, body.category)
    missing = unsatisfied_disclaimers(hits, f"{body.text} {body.supporting_text}")
    return {
        "hits": [{"claim_id": h.rule.id, "type": h.rule.type, "span": h.span, "claim": h.rule.text, "severity": h.rule.severity, "alternative": h.rule.alternative, "required_disclaimer": h.rule.required_disclaimer, "pack": h.rule.rule_pack} for h in hits],
        "missing_disclaimers": [h.rule.required_disclaimer for h in missing],
        "verdict": "block" if any(h.rule.type != "approved" and h.rule.severity == "block" for h in hits) or missing else ("warn" if any(h.rule.type != "approved" for h in hits) else "pass"),
    }


FEATURE = Feature(id="CS-02", summary="Approved / prohibited / needs-substantiation claims per market & category, required disclaimers, regulated-category rule packs.", router=router)
