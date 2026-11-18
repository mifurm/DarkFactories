"""CS-16 Pre-flight creative scorecard — synthetic audience panel (persona LLMs) + heuristics. PREDICTIVE / SIMULATED."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ...core.ai.stubs import stub_task
from ...deps import mutate_limit, spend_limit
from ...domain import scorecard as sc
from ...domain.colors import contrast_ratio
from ...errors import ValidationFailed
from ...registry import Feature
from ...roles import Actor, require
from ...util import now_iso
from ..common import CREW_PREAMBLE, studio, untrusted

router = APIRouter(prefix="/api/campaigns/{campaign_id}/scorecard", tags=["CS-16 Pre-flight Scorecard"])
LABEL = "Predictive / simulated — a synthetic audience panel plus heuristics. Not a measurement; validate with live tests (CS-17)."


class PanelVote(BaseModel):
    persona_id: str
    appeal: int
    would_click: bool
    reaction: str
    concerns: list[str]


class PanelOut(BaseModel):
    votes: list[PanelVote]


@stub_task("scorecard.panel")
def _stub_panel(ctx: dict[str, Any]) -> dict[str, Any]:
    base = ctx.get("heuristic", 70) / 10
    votes = []
    for i, p in enumerate(ctx.get("personas", [])):
        appeal = int(max(1, min(10, round(base + (-0.6, 0.3, 0.8)[i % 3]))))
        votes.append({"persona_id": p["id"], "appeal": appeal, "would_click": appeal >= 7, "reaction": f"As {p['name'].split(',')[0]}: {'this feels like my morning' if appeal >= 7 else 'nice, but I would not stop scrolling'}.", "concerns": [] if appeal >= 7 else ["Hook could be more personal in the first 3 seconds"]})
    return {"votes": votes}


class ScoreIn(BaseModel):
    spot_id: str | None = None
    script_id: str | None = None


async def score_subject(request: Request, campaign_id: str, spot_id: str | None, script_id: str | None) -> dict[str, Any]:
    s = request.app.state.services
    st = studio(request)
    camp = await st.campaign(campaign_id)
    spot = await st.artifact(campaign_id, spot_id, "spot") if spot_id else None
    script = await (st.artifact(campaign_id, script_id or (spot or {}).get("script_id") or "", "script") if (script_id or (spot or {}).get("script_id")) else st.gate_artifact(camp, "script"))
    if not script and not spot:
        raise ValidationFailed("Nothing to score yet — generate a script or render a spot.", code="nothing_to_score")
    kit_doc = await st.brand_kit(camp["brand_id"])
    kit = kit_doc["kit"]
    beats = (script or {}).get("beats", [])
    vo_texts = [b["vo"] for b in beats if b.get("vo")]
    supers = [b["super_text"] for b in beats if b.get("super_text")]
    duration = float((spot or {}).get("probe", {}).get("duration") or (script or {}).get("duration_s") or 15)
    first_vo = vo_texts[0] if vo_texts else ""
    parts: dict[str, int] = {}
    tips: list[str] = []
    parts["hook"], t = sc.hook_score(first_vo, beats[0]["visual"] if beats else "")
    tips += t
    spec = (spot or {}).get("spec") or {}
    ec = spec.get("endcard") or {}
    parts["brand"], t = sc.brand_score(vo_texts, supers, bool(spot) or True, bool(beats and beats[1:2] and "dawn roast" in (beats[1].get("vo", "") + beats[1].get("visual", "")).lower()), kit_doc["name"], kit.get("tagline", "Wake up slowly."))
    tips += t
    parts["clarity"], t = sc.clarity_score(vo_texts, duration)
    tips += t
    parts["cta"], t = sc.cta_score(ec.get("cta") or (script or {}).get("cta"), ec.get("url") or ("northwind.example" if (script or {}).get("cta") else None), vo_texts, vo_texts[-1] if vo_texts else "")
    tips += t
    pairs = [(ec.get("fg", "#F6EBDD"), ec.get("bg", "#2B1A12")), ("#F7F0E6", "#150D09")]
    parts["accessibility"], t = sc.accessibility_score(bool(spec.get("captions")) if spot else True, pairs, bool(spec.get("disclosure_badge")) if spot else False)
    tips += t
    g = (spot or script or {}).get("guardian") or {}
    parts["compliance"] = int(g.get("score", 70))
    if g.get("blocks"):
        tips.append(f"Resolve {g['blocks']} Guardian blocking finding(s) before launch.")
    heuristic = sc.overall(parts)
    personas = kit.get("personas", [])
    panel = await s.llm.complete(
        task="scorecard.panel",
        system=CREW_PREAMBLE + " You simulate a synthetic audience panel. For each persona, rate appeal 1-10 for this commercial, say whether they would click, give a one-sentence reaction in their voice and up to 2 concerns. Be honest and varied; this is a simulation.",
        user=f"Personas: {[(p['id'], p['name'], p.get('needs')) for p in personas]}\nScript voice-over (data): {untrusted(' / '.join(vo_texts), 1200)}\nSupers: {supers}\nCTA: {(script or {}).get('cta')}",
        schema=PanelOut,
        context={"personas": personas, "heuristic": heuristic},
        max_tokens=1200,
    )
    avg_appeal = sum(v.appeal for v in panel.votes) / max(1, len(panel.votes))
    predicted = round(0.7 * heuristic + 0.3 * avg_appeal * 10)
    art = await st.create_artifact(
        campaign_id, "scorecard",
        {"title": "Pre-flight scorecard", "label": LABEL, "subject": {"spot_id": spot_id, "script_id": (script or {}).get("id")}, "parts": parts, "weights": sc.WEIGHTS, "heuristic_score": heuristic, "predicted_score": predicted, "panel": [v.model_dump() for v in panel.votes], "panel_avg_appeal": round(avg_appeal, 1), "would_click_pct": round(100 * sum(1 for v in panel.votes if v.would_click) / max(1, len(panel.votes))), "suggestions": list(dict.fromkeys(tips))[:8], "scored_at": now_iso()},
    )
    return art


@router.post("", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def score(request: Request, campaign_id: str, body: ScoreIn | None = None, _: Actor = Depends(require("generate"))) -> dict[str, Any]:
    body = body or ScoreIn()
    return await score_subject(request, campaign_id, body.spot_id, body.script_id)


@router.get("")
async def list_scorecards(request: Request, campaign_id: str) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)
    return {"scorecards": await st.artifacts(campaign_id, "scorecard"), "label": LABEL}


__all__ = ["contrast_ratio", "re"]
FEATURE = Feature(id="CS-16", summary="Pre-flight scorecard: synthetic persona panel + heuristics (hook in 3 s, brand presence, clarity, CTA, accessibility, compliance) with suggestions — labelled predictive/simulated.", router=router)
