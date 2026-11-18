"""CS-06 Script & Copy agent — 6/15/30/60 s scripts (beats, VO, supers, CTA), channel copy, tone variants; claim-aware."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...core.ai.stubs import stub_task
from ...core.guardian_service import evaluate, subject_from_copy, subject_from_script, summarize
from ...core.jobs import JobContext
from ...deps import mutate_limit, spend_limit
from ...domain import script as sc
from ...domain.brief import quoted
from ...domain.claims import ClaimRule
from ...errors import NotFound, ValidationFailed
from ...registry import Feature
from ...roles import Actor, require
from ..common import CREW_PREAMBLE, studio, untrusted
from ..jobs_util import submit_job

router = APIRouter(prefix="/api/campaigns/{campaign_id}", tags=["CS-06 Script & Copy"])
TONES = ["warm", "playful", "premium", "minimal"]


class BeatOut(BaseModel):
    role: str
    t_start: float
    t_end: float
    visual: str
    vo: str
    super_text: str


class MusicCue(BaseModel):
    mood: str
    reference_title: str
    notes: str


class ScriptOut(BaseModel):
    title: str
    logline: str
    beats: list[BeatOut]
    cta: str
    music: MusicCue
    talent: list[str]


class CopyItem(BaseModel):
    channel: str
    kind: str
    text: str


class CopyOut(BaseModel):
    items: list[CopyItem]


_BEATS = {
    6: [("hook", "Pre-dawn kitchen, blue-grey light turning amber; a hand reaches for a ceramic mug beside the kraft Dawn Roast bag.", "Some mornings deserve a slower start.", "A slower start."), ("brand", "Cup and bag on a sunlit windowsill, the amber sun mark glowing.", "Dawn Roast. Wake up slowly.", "Dawn Roast")],
    15: [
        ("hook", "Pre-dawn kitchen, blue-grey light turning amber; a hand reaches for a ceramic mug beside a kraft bag with the amber sun mark.", "Some mornings deserve a slower start.", "A slower start."),
        ("product", "Close on the Dawn Roast bag being opened; steam and the scent of caramel and orange peel rise in soft backlight.", "Dawn Roast. Medium roast, roasted in small batches.", "Dawn Roast"),
        ("proof", "Slow pour into a ceramic cup; golden light crosses the counter; a quiet, private smile.", "Caramel, orange peel and cocoa. Poured without hurry.", ""),
        ("brand", "Cup and bag on a sunlit windowsill, the amber sun mark glowing; the end card rises.", "Wake up slowly.", "Wake up slowly."),
    ],
    30: [
        ("hook", "4:45 a.m. A dark street, one lit bakery window; a baker ties her apron.", "For the people who start before the sun.", "Before the sun."),
        ("product", "Kitchen counter, kraft Dawn Roast bag, the amber sun mark catching the first light.", "Dawn Roast. A medium roast, roasted in small batches.", "Dawn Roast"),
        ("proof", "Beans tumbling, then a slow pour; steam curling through a sunbeam.", "Caramel, orange peel and cocoa notes.", ""),
        ("proof", "A nurse sits on a stoop, hands around a warm cup, the street waking behind her.", "A quiet ten minutes before the day begins.", "Ten quiet minutes"),
        ("cta", "A commuter dad on the porch with a mug; kids' laughter behind the door.", "Find Dawn Roast near you.", "Find Dawn Roast near you"),
        ("brand", "Cup and bag on a sunlit windowsill; the end card rises.", "Wake up slowly.", "Wake up slowly."),
    ],
    60: [
        ("hook", "A city before sunrise: streetlights, a delivery van, a single lit window.", "There is an hour that belongs to you.", "An hour of your own."),
        ("product", "A kitchen. Kraft bag with the amber sun mark on the counter.", "Dawn Roast. Medium roast. Roasted in small batches.", "Dawn Roast"),
        ("proof", "Beans in the roaster window, turning from green to gold.", "We taste every batch, because the first cup matters most.", ""),
        ("proof", "Pour-over in slow motion; blooming coffee, steam in backlight.", "Caramel. Orange peel. Cocoa.", ""),
        ("proof", "A baker, a nurse and a dad each in their own quiet corner of the morning.", "Different mornings. The same slow start.", "Different mornings"),
        ("proof", "Sunlight crossing a table; a notebook, a cup, a deep breath.", "No rush. Nothing else has to happen yet.", ""),
        ("cta", "Shelf of Dawn Roast bags in a neighbourhood store.", "Find Dawn Roast near you.", "Find Dawn Roast near you"),
        ("cta", "The amber sun mark rising over the bag.", "Roasted in small batches. Poured without hurry.", ""),
        ("brand", "Cup and bag on a sunlit windowsill; the end card rises.", "Wake up slowly.", "Wake up slowly."),
    ],
}
_PLAYFUL = "Mornings called. We let it ring."


@stub_task("script.write")
def _stub_script(ctx: dict[str, Any]) -> dict[str, Any]:
    d = int(ctx.get("duration", 15))
    rows = _BEATS.get(d, _BEATS[15])
    struct = sc.structure_for(d if d in _BEATS else 15)
    beats = []
    for (role, vis, vo, sup), (_, t0, t1) in zip(rows, struct, strict=False):
        if ctx.get("tone") == "playful" and role == "hook":
            vo = _PLAYFUL
        beats.append({"role": role, "t_start": t0, "t_end": t1, "visual": vis, "vo": vo, "super_text": sup})
    return {
        "title": f"{ctx.get('product', 'Dawn Roast')} — {d}s ({ctx.get('territory', 'The Slow Hour')})",
        "logline": "A quiet hour that belongs to you.",
        "beats": beats,
        "cta": "Find Dawn Roast near you",
        "music": {"mood": ctx.get("mood", "warm"), "reference_title": ctx.get("music_reference", ""), "notes": "Warm, unhurried bed that ducks under the voice-over."},
        "talent": ctx.get("talent", []),
    }


@stub_task("copy.channel")
def _stub_copy(ctx: dict[str, Any]) -> dict[str, Any]:
    p = ctx.get("product", "Dawn Roast")
    out: list[dict[str, str]] = []
    for ch in ctx.get("channels", ["youtube", "meta"]):
        if ch == "youtube":
            out += [{"channel": ch, "kind": "headline", "text": "Some mornings deserve a slower start."}, {"channel": ch, "kind": "caption", "text": f"{p}: medium roast, roasted in small batches. Wake up slowly."}]
        elif ch == "meta":
            out += [{"channel": ch, "kind": "headline", "text": "Pour slowly. Nothing else has to happen yet."}, {"channel": ch, "kind": "caption", "text": f"Caramel, orange peel and cocoa. {p} is here. Wake up slowly."}]
        elif ch == "tiktok":
            out += [{"channel": ch, "kind": "caption", "text": f"POV: it is 5 a.m. and the only sound is the pour. {p} #wakeupslowly"}]
        elif ch == "linkedin":
            out += [{"channel": ch, "kind": "caption", "text": f"For the people who start before the sun: {p}, roasted in small batches."}]
        elif ch == "email":
            out += [{"channel": ch, "kind": "email_subject", "text": "Your slower morning starts here"}, {"channel": ch, "kind": "email_body", "text": f"Meet {p}: caramel, orange peel and cocoa, roasted in small batches. Wake up slowly."}]
        elif ch == "ctv":
            out += [{"channel": ch, "kind": "headline", "text": f"{p}. Wake up slowly."}]
        else:
            out += [{"channel": ch, "kind": "headline", "text": f"{p} — wake up slowly."}]
    return {"items": out}


async def _one_script(request: Request, camp: dict[str, Any], brief: dict[str, Any], strategy: dict[str, Any] | None, duration: int, tone: str, variation: int, rules: list[ClaimRule]) -> dict[str, Any]:
    s = request.app.state.services
    st = studio(request)
    f = brief["fields"]
    terr = None
    if strategy:
        terr = next((t for t in strategy["territories"] if t["id"] == strategy.get("selected_territory_id")), strategy["territories"][0])
    ctx = await st.brand_context(camp["brand_id"], f"script voice tone {terr['name'] if terr else ''} {f.get('product', '')}", k=3)
    tagline = ctx["brand"].get("tagline") or "Wake up slowly."
    struct = sc.structure_for(duration)
    budget = sc.word_budget(duration)
    approved = [c["text"] for c in await st.repo.query("claims", {"type": "approved"}, pk=camp["brand_id"])]
    out = await s.llm.complete(
        task="script.write",
        system=CREW_PREAMBLE + f" You are the Script & Copy agent. Write a {duration}-second spot with exactly {len(struct)} beats following these roles/time windows: {[(r, a, b) for r, a, b in struct]}. "
        f"Voice-over budget: at most {budget} spoken words in total (~2.5 words/second). Lead with a human moment in the hook. Supers are short on-screen messages (≤ 5 words) or empty. The last beat is the brand beat and ends on the tagline “{tagline}”. "
        "Visual descriptions must be concrete and shootable. Never make health/medical claims. Suggest a music mood (calm|warm|uplifting|reflective). Include brief mandatory lines VERBATIM where they fit.",
        user=(
            f"Brand voice: {ctx['voice'].get('tone')}; forbidden words: {ctx['voice'].get('forbidden_words')}\nTerritory: {terr['name'] + ' — ' + terr['big_idea'] if terr else 'free choice'}\n"
            f"Product: {f.get('product')}\nKey message: {f.get('key_message')}\nCTA: {f.get('cta')}\nTone requested: {tone}\n"
            f"Mandatories (data supplied by the client — include verbatim quoted lines): {untrusted(' | '.join(f.get('mandatories', [])), 800)}\n"
            f"Approved claims available: {approved}\nMusic reference from the client: {f.get('music_reference') or 'none'}\nTalent: {f.get('talent')}\nVariation seed: {variation}"
        ),
        schema=ScriptOut,
        context={"duration": duration, "tone": tone, "product": f.get("product") or "Dawn Roast", "territory": terr["name"] if terr else "The Slow Hour", "music_reference": f.get("music_reference", ""), "talent": [t.split("(")[0].strip() for t in f.get("talent", [])], "mood": "warm"},
        max_tokens=3000,
        effort="low",
        fresh=variation > 0,
    )
    beats = sc.normalize_beats([b.model_dump() for b in out.beats], duration)
    added = sc.ensure_mandatories(beats, f.get("mandatories", []), tagline)
    texts = [b["vo"] for b in beats] + [b.get("super_text") or "" for b in beats]
    legal = sc.claim_aware_legal(texts, rules, camp.get("markets", ["US"]), camp.get("category", "beverage"))
    total_words = sum(len(b["vo"].split()) for b in beats)
    return {
        "title": out.title,
        "logline": out.logline,
        "duration_s": duration,
        "tone": tone,
        "territory_id": terr["id"] if terr else None,
        "beats": beats,
        "cta": out.cta,
        "legal": legal,
        "music": {"mood": out.music.mood, "reference_title": out.music.reference_title or f.get("music_reference", ""), "title": out.music.reference_title or f.get("music_reference", ""), "notes": out.music.notes, "rights_id": None},
        "talent": [{"name": t.split("(")[0].strip(), "usage": "voice", "ai_synthesis": False} for t in f.get("talent", []) if t.strip()],
        "mandatories_inserted": added,
        "word_count": total_words,
        "word_budget": budget,
        "over_budget": total_words > budget * 1.15,
        "tagline": tagline,
    }


class ScriptGenIn(BaseModel):
    durations: list[int] = Field(default_factory=lambda: [15], min_length=1, max_length=4)
    tone: str = Field(default="warm", pattern="^(warm|playful|premium|minimal)$")
    variation: int = Field(default=0, ge=0, le=20)


@router.post("/script/generate", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def generate(request: Request, campaign_id: str, body: ScriptGenIn | None = None, wait: bool = False, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    body = body or ScriptGenIn()
    bad = [d for d in body.durations if d not in (6, 15, 30, 60)]
    if bad:
        raise ValidationFailed(f"unsupported durations {bad}; use 6, 15, 30 or 60", code="bad_duration")
    await studio(request).campaign(campaign_id)

    async def run(job: JobContext) -> dict[str, Any]:
        s = request.app.state.services
        st = studio(request)
        camp = await st.campaign(campaign_id)
        brief = await st.latest(campaign_id, "brief")
        if not brief:
            raise ValidationFailed("Finalize the brief first (CS-04).", code="brief_missing")
        strategy = await st.latest(campaign_id, "strategy")
        gctx = await st.guardian_context(camp["brand_id"])
        await job.progress(0.1, "Script agent is writing", step="write")
        results = await asyncio.gather(*(_one_script(request, camp, brief, strategy, d, body.tone, body.variation, gctx.claims) for d in body.durations))
        ids = []
        for n, data in enumerate(results):
            art = await st.create_artifact(campaign_id, "script", {**data, "brief_id": brief["id"], "strategy_id": strategy["id"] if strategy else None}, actor=actor)
            await job.progress(0.5 + 0.4 * (n + 1) / len(results), f"Guardian reviewing {data['duration_s']}s script", step=f"guardian-{data['duration_s']}")
            report, _ = await evaluate(s, subject_from_script(camp, art))
            art["guardian"] = summarize(report)
            await st.save_artifact(art)
            ids.append({"artifact_id": art["id"], "duration_s": data["duration_s"], "guardian": art["guardian"]})
        await st.set_stage(campaign_id, "script")
        await st.audit(campaign_id, actor, "script.generated", {"campaign_id": campaign_id}, {"scripts": ids})
        return {"scripts": ids}

    return await submit_job(request, "script.generate", run, campaign_id, f"Script agent: {'/'.join(str(d) for d in body.durations)} s", "CS-06", wait)


@router.get("/script")
async def list_scripts(request: Request, campaign_id: str) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)
    arts = await st.artifacts(campaign_id, "script")
    return {"scripts": arts, "tones": TONES}


@router.get("/script/{script_id}")
async def get_script(request: Request, campaign_id: str, script_id: str) -> dict[str, Any]:
    return await studio(request).artifact(campaign_id, script_id, "script")


class BeatPatch(BaseModel):
    id: str
    vo: str | None = Field(default=None, max_length=400)
    super_text: str | None = Field(default=None, max_length=80)


class ScriptPatch(BaseModel):
    beats: list[BeatPatch] = Field(default_factory=list)
    cta: str | None = Field(default=None, max_length=80)
    legal: list[str] | None = None


@router.patch("/script/{script_id}", dependencies=[Depends(mutate_limit)])
async def edit_script(request: Request, campaign_id: str, script_id: str, body: ScriptPatch, actor: Actor = Depends(require("campaign.write"))) -> dict[str, Any]:
    """Human edit: updates the text, invalidates prior approval and re-runs the Guardian."""
    s = request.app.state.services
    st = studio(request)
    camp = await st.campaign(campaign_id)
    art = await st.artifact(campaign_id, script_id, "script")
    by_id = {b["id"]: b for b in art["beats"]}
    for p in body.beats:
        if p.id not in by_id:
            raise NotFound(f"beat {p.id} not found", code="beat_not_found")
        if p.vo is not None:
            by_id[p.id]["vo"] = p.vo.strip()
        if p.super_text is not None:
            by_id[p.id]["super_text"] = p.super_text.strip() or None
    if body.cta is not None:
        art["cta"] = body.cta
    if body.legal is not None:
        art["legal"] = [x for x in body.legal if x.strip()]
    art["status"] = "draft"
    report, _ = await evaluate(s, subject_from_script(camp, art))
    art["guardian"] = summarize(report)
    await st.save_artifact(art)
    await st.audit(campaign_id, actor, "script.edited", {"artifact_id": script_id}, {"guardian": art["guardian"]["verdict"]})
    return art


class ToneVariantIn(BaseModel):
    tone: str = Field(pattern="^(warm|playful|premium|minimal)$")


@router.post("/script/{script_id}/tone-variant", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def tone_variant(request: Request, campaign_id: str, script_id: str, body: ToneVariantIn, wait: bool = False, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    st = studio(request)
    src = await st.artifact(campaign_id, script_id, "script")

    async def run(job: JobContext) -> dict[str, Any]:
        s = request.app.state.services
        camp = await st.campaign(campaign_id)
        brief = await st.latest(campaign_id, "brief")
        strategy = await st.latest(campaign_id, "strategy")
        gctx = await st.guardian_context(camp["brand_id"])
        await job.progress(0.2, f"Writing {body.tone} variant", step="write")
        data = await _one_script(request, camp, brief, strategy, src["duration_s"], body.tone, 1, gctx.claims)
        art = await st.create_artifact(campaign_id, "script", {**data, "brief_id": brief["id"]}, actor=actor, parent_id=script_id)
        report, _ = await evaluate(s, subject_from_script(camp, art))
        art["guardian"] = summarize(report)
        await st.save_artifact(art)
        return {"artifact_id": art["id"], "tone": body.tone, "guardian": art["guardian"]}

    return await submit_job(request, "script.tone", run, campaign_id, f"Script tone variant: {body.tone}", "CS-06", wait)


class CopyGenIn(BaseModel):
    channels: list[str] = Field(default_factory=lambda: ["youtube", "meta", "tiktok", "email"], min_length=1, max_length=8)


@router.post("/copy/generate", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def generate_copy(request: Request, campaign_id: str, body: CopyGenIn | None = None, wait: bool = False, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    body = body or CopyGenIn()
    st = studio(request)
    await st.campaign(campaign_id)

    async def run(job: JobContext) -> dict[str, Any]:
        s = request.app.state.services
        camp = await st.campaign(campaign_id)
        brief = await st.latest(campaign_id, "brief")
        if not brief:
            raise ValidationFailed("Finalize the brief first (CS-04).", code="brief_missing")
        f = brief["fields"]
        ctx = await st.brand_context(camp["brand_id"], "copy tone headline caption", k=3)
        await job.progress(0.2, "Copywriter is writing channel copy", step="write")
        out = await s.llm.complete(
            task="copy.channel",
            system=CREW_PREAMBLE + " You are the Copywriter. Write channel-specific copy: headlines ≤ 40 characters, social captions ≤ 125 characters, email subject ≤ 50 characters + a 2-sentence body. Warm, unhurried voice; at most one exclamation mark overall; no health claims.",
            user=f"Channels: {body.channels}\nProduct: {f.get('product')}\nKey message: {f.get('key_message')}\nVoice: {ctx['voice'].get('tone')}; forbidden: {ctx['voice'].get('forbidden_words')}\nCTA: {f.get('cta')}",
            schema=CopyOut,
            context={"channels": body.channels, "product": f.get("product") or "Dawn Roast"},
            max_tokens=1600,
        )
        items = [{"id": f"cp{i + 1}", **it.model_dump()} for i, it in enumerate(out.items)]
        art = await st.create_artifact(campaign_id, "copy", {"title": "Channel copy", "items": items, "channels": body.channels}, actor=actor)
        report, _ = await evaluate(s, subject_from_copy(camp, art))
        art["guardian"] = summarize(report)
        await st.save_artifact(art)
        return {"artifact_id": art["id"], "items": len(items), "guardian": art["guardian"]}

    return await submit_job(request, "copy.generate", run, campaign_id, "Copywriter: channel copy", "CS-06", wait)


@router.get("/copy")
async def list_copy(request: Request, campaign_id: str) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)
    return {"copy": await st.artifacts(campaign_id, "copy")}


__all__ = ["quoted"]
FEATURE = Feature(id="CS-06", summary="Scripts for 6/15/30/60 s with beats, VO, supers, CTA; channel copy; tone variants; claim-aware (disclaimers, verbatim mandatories).", router=router)
