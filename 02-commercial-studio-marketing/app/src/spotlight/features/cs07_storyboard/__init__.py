"""CS-07 Storyboard & Art Direction agent — shot list, style bible and consistent keyframes via image generation."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...core.ai.stubs import stub_task
from ...core.guardian_service import evaluate, subject_from_storyboard, summarize
from ...core.jobs import JobContext
from ...deps import mutate_limit, spend_limit
from ...errors import AppError, NotFound, ValidationFailed
from ...registry import Feature
from ...roles import Actor, require
from ..common import CREW_PREAMBLE, studio
from ..jobs_util import submit_job

router = APIRouter(prefix="/api/campaigns/{campaign_id}/storyboard", tags=["CS-07 Storyboard"])
MOVES = {"hook": "zoom_in", "product": "pan_right", "proof": "parallax", "cta": "pan_left", "brand": "zoom_out"}
FRAMING = {"hook": "wide establishing shot", "product": "medium close-up", "proof": "macro close-up with shallow depth of field", "cta": "medium shot", "brand": "centered hero shot, calm negative space"}
FOCAL = {"hook": (0.5, 0.58), "product": (0.45, 0.52), "proof": (0.5, 0.55), "cta": (0.55, 0.55), "brand": (0.5, 0.58)}


class StyleBible(BaseModel):
    look: str
    lighting: str
    lens: str
    product_description: str
    character_description: str
    palette_notes: str


class ShotOut(BaseModel):
    beat_index: int
    description: str
    framing: str
    movement: str
    image_prompt: str
    focal_x: float
    focal_y: float
    super_text: str


class StoryboardOut(BaseModel):
    style_bible: StyleBible
    shots: list[ShotOut]


@stub_task("storyboard.shots")
def _stub_storyboard(ctx: dict[str, Any]) -> dict[str, Any]:
    pal = ctx.get("palette_names", "espresso brown, dawn amber, cream, roast red and sage")
    bible = {
        "look": "Warm, low-contrast editorial photography; real textures (steam, ceramic, kraft paper); gentle film grain.",
        "lighting": "Low, warm sunrise light with long soft shadows; backlit steam.",
        "lens": "35mm and 85mm prime look, shallow depth of field on close-ups.",
        "product_description": "A 12 oz kraft-paper coffee bag with a small amber sun mark and the word NORTHWIND (no other text), matte finish.",
        "character_description": "Maya, mid-30s, short dark hair, soft knit sweater, calm expression, early-morning light on her face.",
        "palette_notes": f"Palette: {pal}.",
    }
    shots = []
    for i, b in enumerate(ctx.get("beats", []), start=1):
        role = b.get("role", "proof")
        fx, fy = FOCAL.get(role, (0.5, 0.55))
        shots.append({"beat_index": i, "description": b["visual"], "framing": FRAMING.get(role, "medium shot"), "movement": MOVES.get(role, "zoom_in"), "image_prompt": b["visual"], "focal_x": fx, "focal_y": fy, "super_text": b.get("super_text") or ""})
    return {"style_bible": bible, "shots": shots}


def compose_image_prompt(shot: dict[str, Any], bible: dict[str, Any], palette_hex: list[str]) -> str:
    """Consistency by construction: every frame carries the same style bible, product/character descriptions and palette."""
    return (
        f"{shot['description']} Framing: {shot['framing']}. "
        f"Lighting: {bible['lighting']} Look: {bible['look']} Lens: {bible['lens']} "
        f"Product (when visible): {bible['product_description']} Person (when visible): {bible['character_description']} "
        f"{bible['palette_notes']} Brand colours as hex: {', '.join(palette_hex)}. "
        "Photographic, cinematic 3:2 composition with calm negative space in the lower third for captions. "
        "No text, no logos, no letters, no captions, no watermark, no UI."
    )


class GenIn(BaseModel):
    script_id: str | None = None


@router.post("/generate", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def generate_shots(request: Request, campaign_id: str, body: GenIn | None = None, wait: bool = False, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)

    async def run(job: JobContext) -> dict[str, Any]:
        s = request.app.state.services
        camp = await st.campaign(campaign_id)
        script = await (st.artifact(campaign_id, body.script_id, "script") if body and body.script_id else st.latest(campaign_id, "script"))
        if not script:
            raise ValidationFailed("Generate a script first (CS-06).", code="script_missing")
        kit = (await st.brand_kit(camp["brand_id"]))["kit"]
        palette = [p["hex"] for p in kit["palette"]]
        names = ", ".join(f"{p['name'].lower()} {p['hex']}" for p in kit["palette"])
        await job.progress(0.2, "Art Director is building the shot list", step="shots")
        beats = script["beats"]
        out = await s.llm.complete(
            task="storyboard.shots",
            system=CREW_PREAMBLE + " You are the Art Director. Produce a style bible (look, lighting, lens, product and character descriptions that stay IDENTICAL across all frames, palette notes) and exactly one shot per script beat, in order. Each shot has a concrete description, framing, camera movement (zoom_in|zoom_out|pan_left|pan_right|pan_up|pan_down|parallax), an image prompt for a text-free photographic keyframe, and a focal point (0..1) where the subject sits so reframing to 9:16/1:1 keeps it in view.",
            user=f"Brand palette: {names}\nBrand look: warm sunrise light, real textures, product = kraft bag with amber sun mark.\nScript ({script['duration_s']}s) beats:\n" + "\n".join(f"{i + 1}. [{b['role']} {b['t_start']}-{b['t_end']}s] visual: {b['visual']} | super: {b.get('super_text') or '-'}" for i, b in enumerate(beats)),
            schema=StoryboardOut,
            context={"beats": beats, "palette_names": names},
            max_tokens=3500,
            effort="low",
        )
        bible = out.style_bible.model_dump()
        shots = []
        for i, b in enumerate(beats):
            raw = out.shots[i] if i < len(out.shots) else None
            role = b.get("role", "proof")
            fx, fy = FOCAL.get(role, (0.5, 0.55))
            sh = {
                "id": f"s{i + 1}",
                "idx": i + 1,
                "beat_id": b["id"],
                "role": role,
                "duration": round(b["t_end"] - b["t_start"], 2),
                "description": (raw.description if raw else b["visual"]),
                "framing": (raw.framing if raw else FRAMING.get(role, "medium shot")),
                "movement": (raw.movement if raw and raw.movement in {"zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "parallax"} else MOVES.get(role, "zoom_in")),
                "focal": [min(1, max(0, raw.focal_x)) if raw else fx, min(1, max(0, raw.focal_y)) if raw else fy],
                "super_text": (raw.super_text if raw else b.get("super_text") or "") or None,
                "asset_id": None,
                "image_status": "pending",
            }
            sh["image_prompt"] = compose_image_prompt(sh, bible, palette)
            shots.append(sh)
        art = await st.create_artifact(campaign_id, "storyboard", {"title": f"Storyboard — {script['duration_s']}s", "script_id": script["id"], "duration_s": script["duration_s"], "style_bible": bible, "shots": shots}, actor=actor)
        camp["selected_script_id"] = script["id"]
        await st.save_campaign(camp)
        await st.set_stage(campaign_id, "storyboard")
        await st.audit(campaign_id, actor, "storyboard.shots_generated", {"artifact_id": art["id"]}, {"shots": len(shots)})
        return {"artifact_id": art["id"], "shots": len(shots)}

    return await submit_job(request, "storyboard.shots", run, campaign_id, "Art Director: shot list & style bible", "CS-07", wait)


@router.get("")
async def get_storyboard(request: Request, campaign_id: str) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)
    arts = await st.artifacts(campaign_id, "storyboard")
    return {"latest": arts[0] if arts else None, "versions": [{"id": a["id"], "version": a["version"], "created_at": a["created_at"], "status": a["status"], "script_id": a.get("script_id")} for a in arts]}


class FramesIn(BaseModel):
    quality: str = Field(default="low", pattern="^(low|medium|high)$")
    shots: list[str] | None = None
    model: str = Field(default="image", pattern="^(image|image_draft)$")
    anchor: bool = False


async def _frames(request: Request, campaign_id: str, sb_id: str, body: FramesIn, actor: Actor, job: JobContext) -> dict[str, Any]:
    s = request.app.state.services
    st = studio(request)
    camp = await st.campaign(campaign_id)
    sb = await st.artifact(campaign_id, sb_id, "storyboard")
    kit = (await st.brand_kit(camp["brand_id"]))["kit"]
    palette = [p["hex"] for p in kit["palette"]]
    todo = [sh for sh in sb["shots"] if not body.shots or sh["id"] in body.shots]
    done = 0
    cost = 0.0
    errors: list[str] = []
    sem = asyncio.Semaphore(3)
    anchor_bytes: list[bytes] | None = None

    async def one(sh: dict[str, Any], refs: list[bytes] | None) -> None:
        nonlocal done, cost
        async with sem:
            try:
                res = await s.image.generate(sh["image_prompt"], size="1536x1024", quality=body.quality, model_role=body.model, references=refs, palette=palette, seed=int(hashlib.sha256(sh["id"].encode()).hexdigest()[:6], 16))
            except AppError as exc:
                if exc.code in {"daily_budget_exceeded", "campaign_budget_exceeded", "premium_requires_approval"}:
                    raise
                sh["image_status"], sh["image_error"] = "failed", exc.message
                errors.append(f"{sh['id']}: {exc.message}")
                return
            except Exception as exc:
                sh["image_status"], sh["image_error"] = "failed", f"{type(exc).__name__}: {str(exc)[:160]}"
                errors.append(f"{sh['id']}: {type(exc).__name__}")
                return
            asset = await st.put_asset(
                campaign_id=campaign_id, name=f"{sb['id']}-{sh['id']}.{'png' if res.mime == 'image/png' else 'jpg'}", data=res.data, mime=res.mime, kind="image", actor=actor,
                tags=["storyboard", sh["role"], "ai-generated"], description=sh["description"], meta={"prompt": sh["image_prompt"], "shot_id": sh["id"], "model": res.model, "quality": res.quality, "size": res.size, "cached": res.cached, "cost_usd": res.cost_usd, "storyboard_id": sb["id"]},
            )
            sh.update(asset_id=asset["id"], image_status="ready", image_error=None, image_model=res.model, image_quality=res.quality, cost_usd=res.cost_usd)
            cost += res.cost_usd
            done += 1
            await job.progress(0.1 + 0.7 * done / len(todo), f"Keyframe {done}/{len(todo)} ready", step=f"frame-{sh['id']}")

    await job.progress(0.05, f"Generating {len(todo)} keyframes ({body.model}, {body.quality})", step="frames")
    if body.anchor and len(todo) > 1:
        await one(todo[0], None)
        if todo[0].get("asset_id"):
            anchor_bytes = [await st.asset_bytes(await st.asset(todo[0]["asset_id"], campaign_id))]
        await asyncio.gather(*(one(sh, anchor_bytes) for sh in todo[1:]))
    else:
        await asyncio.gather(*(one(sh, None) for sh in todo))
    sb["frames_quality"] = body.quality
    await st.save_artifact(sb)
    await job.progress(0.85, "Brand Guardian is checking palette, safety and rights", step="guardian")
    subject, images = await subject_from_storyboard(st, camp, sb)
    report, _ = await evaluate(s, subject, image_bytes=images)
    sb["guardian"] = summarize(report)
    sb["status"] = "draft"
    await st.save_artifact(sb)
    await st.audit(campaign_id, actor, "storyboard.frames_generated", {"artifact_id": sb["id"]}, {"frames": done, "cost_usd": round(cost, 4), "quality": body.quality})
    if done == 0 and errors:
        raise AppError("No keyframes could be generated: " + "; ".join(errors[:2]), code="image_failed", status=502)
    return {"artifact_id": sb["id"], "frames": done, "failed": len(errors), "cost_usd": round(cost, 4), "guardian": sb["guardian"]}


@router.post("/{sb_id}/frames", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def generate_frames(request: Request, campaign_id: str, sb_id: str, body: FramesIn | None = None, wait: bool = False, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    body = body or FramesIn()
    await studio(request).artifact(campaign_id, sb_id, "storyboard")

    async def run(job: JobContext) -> dict[str, Any]:
        return await _frames(request, campaign_id, sb_id, body, actor, job)

    return await submit_job(request, "storyboard.frames", run, campaign_id, f"Art Director: keyframes ({body.quality})", "CS-07", wait, timeout=175)


class ShotPatch(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    movement: str | None = Field(default=None, pattern="^(zoom_in|zoom_out|pan_left|pan_right|pan_up|pan_down|parallax)$")
    focal: list[float] | None = Field(default=None, min_length=2, max_length=2)
    super_text: str | None = Field(default=None, max_length=80)
    prompt_tweak: str | None = Field(default=None, max_length=300)


@router.patch("/{sb_id}/shots/{shot_id}", dependencies=[Depends(mutate_limit)])
async def patch_shot(request: Request, campaign_id: str, sb_id: str, shot_id: str, body: ShotPatch, actor: Actor = Depends(require("campaign.write"))) -> dict[str, Any]:
    st = studio(request)
    sb = await st.artifact(campaign_id, sb_id, "storyboard")
    sh = next((x for x in sb["shots"] if x["id"] == shot_id), None)
    if sh is None:
        raise NotFound("shot not found", code="shot_not_found")
    camp = await st.campaign(campaign_id)
    kit = (await st.brand_kit(camp["brand_id"]))["kit"]
    if body.description is not None:
        sh["description"] = body.description
    if body.movement:
        sh["movement"] = body.movement
    if body.focal:
        sh["focal"] = [min(1, max(0, v)) for v in body.focal]
    if body.super_text is not None:
        sh["super_text"] = body.super_text or None
    sh["image_prompt"] = compose_image_prompt(sh, sb["style_bible"], [p["hex"] for p in kit["palette"]]) + (f" Art direction note: {body.prompt_tweak}" if body.prompt_tweak else "")
    if body.description is not None or body.prompt_tweak:
        sh["image_status"] = "stale"
    sb["status"] = "draft"
    await st.save_artifact(sb)
    await st.audit(campaign_id, actor, "storyboard.shot_edited", {"artifact_id": sb_id, "shot": shot_id})
    return sh


FEATURE = Feature(id="CS-07", summary="Shot list + style bible and storyboard keyframes via gpt-image with consistency by construction (style bible, palette conditioning, optional reference anchor).", router=router)
