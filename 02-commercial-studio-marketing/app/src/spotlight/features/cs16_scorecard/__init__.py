"""CS-16 Pre-flight creative scorecard — synthetic audience panel (persona LLMs) + heuristics. PREDICTIVE / SIMULATED."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ...core.ai.stubs import stub_task
from ...core.studio import campaign_lang
from ...deps import mutate_limit, spend_limit
from ...domain import scorecard as sc
from ...domain.colors import contrast_ratio
from ...domain.kit import localized_kit
from ...errors import ValidationFailed
from ...i18n import t
from ...i18n.directive import lang_directive
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
    pl = ctx.get("lang") == "pl"
    votes = []
    for i, p in enumerate(ctx.get("personas", [])):
        appeal = int(max(1, min(10, round(base + (-0.6, 0.3, 0.8)[i % 3]))))
        first = p["name"].split(",")[0]
        if pl:  # gender-neutral phrasing: the panel speaks for Maja, Darek and Lena alike
            reaction = f"{first}: {'tak wygląda mój poranek' if appeal >= 7 else 'ładnie, ale przewijam dalej'}."
            concerns = [] if appeal >= 7 else ["Hook mógłby być bardziej osobisty już w pierwszych 3 sekundach"]
        else:
            reaction = f"As {first}: {'this feels like my morning' if appeal >= 7 else 'nice, but I would not stop scrolling'}."
            concerns = [] if appeal >= 7 else ["Hook could be more personal in the first 3 seconds"]
        votes.append({"persona_id": p["id"], "appeal": appeal, "would_click": appeal >= 7, "reaction": reaction, "concerns": concerns})
    return {"votes": votes}


class ScoreIn(BaseModel):
    spot_id: str | None = None
    script_id: str | None = None


def localize_card(card: dict[str, Any]) -> dict[str, Any]:
    """A scorecard with its label and advice rendered in the viewer's language (the advice is stored as code + params)."""
    out = {**card, "label": t("score.label")}
    if card.get("tips"):
        out["suggestions"] = sc.render_tips(card["tips"])[:8]
    return out


async def score_subject(request: Request, campaign_id: str, spot_id: str | None, script_id: str | None) -> dict[str, Any]:
    s = request.app.state.services
    st = studio(request)
    camp = await st.campaign(campaign_id)
    lang = campaign_lang(camp)
    spot = await st.artifact(campaign_id, spot_id, "spot") if spot_id else None
    script = await (st.artifact(campaign_id, script_id or (spot or {}).get("script_id") or "", "script") if (script_id or (spot or {}).get("script_id")) else st.gate_artifact(camp, "script"))
    if not script and not spot:
        raise ValidationFailed("Nothing to score yet — generate a script or render a spot.", code="nothing_to_score")
    kit_doc = await st.brand_kit(camp["brand_id"])
    kit = localized_kit(kit_doc["kit"], lang)
    beats = (script or {}).get("beats", [])
    vo_texts = [b["vo"] for b in beats if b.get("vo")]
    supers = [b["super_text"] for b in beats if b.get("super_text")]
    duration = float((spot or {}).get("probe", {}).get("duration") or (script or {}).get("duration_s") or 15)
    first_vo = vo_texts[0] if vo_texts else ""
    parts: dict[str, int] = {}
    tips: list[sc.Tip] = []
    first_visual = (beats[0].get("visual_en") or beats[0]["visual"]) if beats else ""
    parts["hook"], tp = sc.hook_score(first_vo, first_visual, lang)
    tips += tp
    spec = (spot or {}).get("spec") or {}
    ec = spec.get("endcard") or {}
    product_early = bool(beats and beats[1:2] and "dawn roast" in (beats[1].get("vo", "") + beats[1].get("visual", "")).lower())
    parts["brand"], tp = sc.brand_score(vo_texts, supers, bool(spot) or True, product_early, kit_doc["name"], kit.get("tagline") or ("Obudź się powoli." if lang == "pl" else "Wake up slowly."))
    tips += tp
    parts["clarity"], tp = sc.clarity_score(vo_texts, duration, lang)
    tips += tp
    parts["cta"], tp = sc.cta_score(ec.get("cta") or (script or {}).get("cta"), ec.get("url") or ("northwind.example" if (script or {}).get("cta") else None), vo_texts, vo_texts[-1] if vo_texts else "", lang)
    tips += tp
    pairs = [(ec.get("fg", "#F6EBDD"), ec.get("bg", "#2B1A12")), ("#F7F0E6", "#150D09")]
    parts["accessibility"], tp = sc.accessibility_score(bool(spec.get("captions")) if spot else True, pairs, bool(spec.get("disclosure_badge")) if spot else False)
    tips += tp
    g = (spot or script or {}).get("guardian") or {}
    parts["compliance"] = int(g.get("score", 70))
    if g.get("blocks"):
        tips.append(sc.tip("guardian_blocks", count=int(g["blocks"])))
    heuristic = sc.overall(parts)
    personas = kit.get("personas", [])
    panel = await s.llm.complete(
        task="scorecard.panel",
        system=CREW_PREAMBLE + " You simulate a synthetic audience panel. For each persona, rate appeal 1-10 for this commercial, say whether they would click, give a one-sentence reaction in their voice and up to 2 concerns. Be honest and varied; this is a simulation." + lang_directive(lang),
        user=f"Personas: {[(p['id'], p['name'], p.get('needs')) for p in personas]}\nScript voice-over (data): {untrusted(' / '.join(vo_texts), 1200)}\nSupers: {supers}\nCTA: {(script or {}).get('cta')}",
        schema=PanelOut,
        context={"personas": personas, "heuristic": heuristic, "lang": lang},
        max_tokens=1200 if lang == "en" else 1800,
    )
    avg_appeal = sum(v.appeal for v in panel.votes) / max(1, len(panel.votes))
    predicted = round(0.7 * heuristic + 0.3 * avg_appeal * 10)
    art = await st.create_artifact(
        campaign_id, "scorecard",
        {"title": t("artifact.title.scorecard", lang), "lang": lang, "label": t("score.label"), "subject": {"spot_id": spot_id, "script_id": (script or {}).get("id")}, "parts": parts, "weights": sc.WEIGHTS, "heuristic_score": heuristic, "predicted_score": predicted, "panel": [v.model_dump() for v in panel.votes], "panel_avg_appeal": round(avg_appeal, 1), "would_click_pct": round(100 * sum(1 for v in panel.votes if v.would_click) / max(1, len(panel.votes))), "tips": tips, "suggestions": sc.render_tips(tips)[:8], "scored_at": now_iso()},
    )
    return art


@router.post("", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def score(request: Request, campaign_id: str, body: ScoreIn | None = None, _: Actor = Depends(require("generate"))) -> dict[str, Any]:
    body = body or ScoreIn()
    return localize_card(await score_subject(request, campaign_id, body.spot_id, body.script_id))


@router.get("")
async def list_scorecards(request: Request, campaign_id: str) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)
    return {"scorecards": [localize_card(a) for a in await st.artifacts(campaign_id, "scorecard")], "label": t("score.label")}


__all__ = ["LABEL", "contrast_ratio", "re"]
FEATURE = Feature(id="CS-16", summary="Pre-flight scorecard: synthetic persona panel + heuristics (hook in 3 s, brand presence, clarity, CTA, accessibility, compliance) with suggestions — labelled predictive/simulated.", router=router)
