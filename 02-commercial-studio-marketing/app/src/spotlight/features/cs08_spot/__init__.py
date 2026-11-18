"""CS-08 Spot compositor / Video — keyframes + motion + VO + captions + music + end card; MP4 H.264/AAC via a VideoProvider.

Two render qualities: ``preview`` (the approved keyframes with camera moves — free, ~30 s) and ``cinematic`` (every keyframe becomes the first frame of an
AI-generated clip with real subject and camera motion, see ``spotlight.motion``; the compositor then edits the clips exactly like stills)."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from ...core.ai import pricing
from ...core.guardian_service import evaluate, subject_from_spot, summarize
from ...core.jobs import JobContext
from ...core.provenance import create_for_asset
from ...core.studio import Studio, campaign_lang
from ...deps import mutate_limit, spend_limit, svc
from ...domain.rights import RightsEntry, best_replacement_track
from ...domain.spot_builder import SpotBuildError, build_master_spec, music_spec, scenes_from_storyboard
from ...errors import AppError, NotFound, ProviderUnavailable, ValidationFailed
from ...i18n import has, t
from ...motion import plan as motion_plan
from ...motion.orchestrator import find_cached, generate_clips, motion_status
from ...registry import Feature
from ...roles import Actor, require
from ...util import new_id
from ...video.provider import get_provider
from ...video.spec import ASPECTS, RenderSpec
from ..common import studio
from ..jobs_util import submit_job

router = APIRouter(prefix="/api/campaigns/{campaign_id}/spot", tags=["CS-08 Spot compositor"])

# The compositor subprocess reports English progress lines; they are mapped to catalog keys so the job shows them in the viewer's language.
_RENDER_MESSAGES = {
    "Preparing keyframes": "job.msg.render.prepare",
    "Mixing voice-over + music, normalising loudness (EBU R128)": "job.msg.render.mix",
    "Verifying output (ffprobe, loudness)": "job.msg.render.verify",
    "Done": "job.state.done",
}
_FRAME_PROGRESS = re.compile(r"Rendering frame (\d+)/(\d+)$")


def _render_message(msg: str) -> tuple[str | None, dict[str, Any]]:
    if msg in _RENDER_MESSAGES:
        return _RENDER_MESSAGES[msg], {}
    m = _FRAME_PROGRESS.match(msg)
    return ("job.msg.render.frame", {"n": int(m.group(1)), "total": int(m.group(2))}) if m else (None, {})


async def render_spec_to_asset(s: Any, st: Studio, campaign: dict[str, Any], spec: RenderSpec, *, script_id: str | None, storyboard_id: str | None, voice_id: str | None, talent: list[dict[str, Any]], actor: Actor, job: JobContext | None, parent_id: str | None = None, lineage_kind: str = "master", variant: dict[str, Any] | None = None, status: str = "draft", markets: list[str] | None = None) -> dict[str, Any]:
    """Render a spec with the configured VideoProvider and persist video/SRT/poster assets + the ``spot`` artifact.

    A ``cinematic`` spec first gets its clips (cache / GPU worker / still fallback per shot, see ``spotlight.motion.orchestrator``); the compositor then plays them."""
    images: dict[str, bytes] = {}
    for sc in spec.scenes:
        if sc.asset_id and sc.asset_id not in images:
            images[sc.asset_id] = await st.asset_bytes(await st.asset(sc.asset_id, campaign["id"]))
    vo_audio: dict[str, bytes] = {}
    for ln in spec.vo:
        if ln.asset_id:
            vo_audio[ln.id] = await st.asset_bytes(await st.asset(ln.asset_id, campaign["id"]))
    provider = get_provider(s.settings.video_provider, s.settings.render_timeout_s, s.settings.work_dir or None)

    motion = None
    clips: dict[str, bytes] | None = None
    base, span = 0.1, 0.75
    if spec.quality == "cinematic":
        storyboard = None
        if storyboard_id:
            try:
                storyboard = await st.artifact(campaign["id"], storyboard_id, "storyboard")
            except NotFound:
                storyboard = None
        motion = await generate_clips(s, st, campaign, spec, storyboard=storyboard, images=images, job=job, actor=actor)
        motion.apply(spec)
        clips = motion.clips or None
        base, span = 0.58, 0.30
        if job:
            await job.progress(0.57, step="render", key="job.msg.spot.composite", params={"dur": round(spec.duration, 1), "aspect": spec.aspect})

    async def progress(p: float, msg: str) -> None:
        if job:
            key, params = _render_message(msg)
            if key:
                await job.progress(base + span * p, key=key, params=params)
            else:
                await job.progress(base + span * p, msg)

    out = await (provider.render(spec, images, vo_audio, progress, clips=clips) if clips else provider.render(spec, images, vo_audio, progress))
    rs = out.meta.get("render_seconds", 0.0)
    cost = pricing.render_cost(rs)
    await s.meter.record(kind="render", model=f"compositor-{provider.name}", units={"render_seconds": rs, "frames": out.meta.get("frames"), "aspect": spec.aspect}, cost_usd=cost)
    render_meta = {**out.meta, "motion": motion.report()} if motion else out.meta
    tag = [spec.aspect.replace(":", "x"), spec.lang, lineage_kind]
    suffix = f"{spec.aspect.replace(':', 'x')}-{spec.lang}" + (f"-{variant['cutdown_s']}s" if variant and variant.get("cutdown_s") else "")
    video = await st.put_asset(campaign_id=campaign["id"], name=f"spot-{suffix}.mp4", data=out.video, mime="video/mp4", kind="video", actor=actor, tags=["spot", *tag], description=spec.title, meta={"probe": out.probe, "loudness": out.loudness, "spec_id": spec.id, "aspect": spec.aspect, "lang": spec.lang}, parent_id=None)
    srt = await st.put_asset(campaign_id=campaign["id"], name=f"spot-{suffix}.srt", data=out.srt.encode(), mime="application/x-subrip", kind="subtitle", actor=actor, tags=["captions", *tag], index=False)
    poster = await st.put_asset(campaign_id=campaign["id"], name=f"spot-{suffix}-poster.jpg", data=out.poster, mime="image/jpeg", kind="image", actor=actor, tags=["poster", *tag], index=False, meta={"derived_from": video["id"]})
    art = await st.create_artifact(
        campaign["id"], "spot",
        {"title": spec.title, "spec": spec.model_dump(mode="json"), "assets": {"video": video["id"], "srt": srt["id"], "poster": poster["id"]}, "probe": out.probe, "loudness": out.loudness, "render": render_meta, "quality": spec.quality,
         "script_id": script_id, "storyboard_id": storyboard_id, "voice_id": voice_id, "lineage_kind": lineage_kind, "variant": variant or {"aspect": spec.aspect, "lang": spec.lang, "cutdown_s": None}, "talent": talent, "markets": markets or campaign.get("markets", []), "cost_usd": round(cost, 5), "needs_rerender": False},
        actor=actor, parent_id=parent_id, status=status,
    )
    video["spot_id"] = art["id"]
    await st.save_asset(video)
    if motion:
        rep = motion.report()
        await st.audit(campaign["id"], actor, "spot.motion_generated", {"artifact_id": art["id"]}, {"model": rep["model"], "mode": rep["mode"], "shots": rep["shots_generated"], "cached": rep["shots_cached"], "fallback": len(rep["shots_fallback"]), "gpu_seconds": rep["gpu_seconds"], "cost_usd": rep["cost_usd"]})
    return art


async def post_render(s: Any, st: Studio, campaign: dict[str, Any], art: dict[str, Any], actor: Actor) -> dict[str, Any]:
    """Guardian review of the finished spot + provenance manifest + audit entry."""
    report, _ = await evaluate(s, subject_from_spot(campaign, art, markets=art.get("markets")))
    art["guardian"] = summarize(report)
    await st.save_artifact(art)
    video = await st.asset(art["assets"]["video"], campaign["id"])
    await st.audit(campaign["id"], actor, "spot.rendered", {"artifact_id": art["id"], "asset_id": video["id"]}, {"aspect": art["spec"]["aspect"], "lang": art["spec"]["lang"], "duration": art["probe"]["duration"], "guardian": art["guardian"]["verdict"]})
    prov = await create_for_asset(s, video, campaign, art)
    art["provenance_id"] = prov["id"]
    await st.save_artifact(art)
    return art


class RenderIn(BaseModel):
    script_id: str | None = None
    storyboard_id: str | None = None
    voice_id: str | None = None
    aspect: str = Field(default="16:9", pattern="^(16:9|9:16|1:1|4:5)$")
    loudness_lufs: float = Field(default=-16.0, ge=-30, le=-10)
    grade_strength: float = Field(default=0.0, ge=0, le=0.6)
    quality: str = Field(default="preview", pattern="^(preview|cinematic)$")  # preview: keyframes + camera moves; cinematic: AI-generated clips (real motion, costs GPU time)


def _motion_summary(art: dict[str, Any]) -> dict[str, Any] | None:
    m = (art.get("render") or {}).get("motion")
    return {k: m[k] for k in ("mode", "model", "license", "shots_total", "shots_generated", "shots_cached", "shots_fallback", "gpu_seconds", "cost_usd")} if m else None


def _with_reason_text(art: dict[str, Any]) -> dict[str, Any]:
    """A spot artifact as served: each fallback shot gets ``reason_text`` in the viewer's language (the stored record keeps the stable ``reason`` code)."""
    motion = (art.get("render") or {}).get("motion")
    if not motion or not motion.get("shots_fallback"):
        return art
    rows = [{**f, "reason_text": t(f"motion.reason.{f.get('reason')}" if has(f"motion.reason.{f.get('reason')}") else "motion.reason.failed")} for f in motion["shots_fallback"]]
    return {**art, "render": {**art["render"], "motion": {**motion, "shots_fallback": rows}}}


@router.post("/render", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def render(request: Request, campaign_id: str, body: RenderIn | None = None, wait: bool = False, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    body = body or RenderIn()
    st = studio(request)
    await st.campaign(campaign_id)
    cinematic = body.quality == "cinematic"
    if cinematic and svc(request).motion.name == "off":
        raise ProviderUnavailable("Cinematic motion is not available in this deployment.", code="motion_unavailable", hint="Use the Preview quality, or ask an Admin to enable the GPU motion worker (MOTION_MODE).")

    async def run(job: JobContext) -> dict[str, Any]:
        s = request.app.state.services
        camp = await st.campaign(campaign_id)
        brief = await st.latest(campaign_id, "brief")
        sb = await (st.artifact(campaign_id, body.storyboard_id, "storyboard") if body.storyboard_id else st.latest(campaign_id, "storyboard"))
        if not sb:
            raise ValidationFailed("A spot needs a storyboard with keyframes (CS-07).", code="inputs_missing", key="err.inputs_missing.storyboard")
        script_id = body.script_id or sb.get("script_id")
        script = await (st.artifact(campaign_id, script_id, "script") if script_id else st.latest(campaign_id, "script"))
        voices = [v for v in await st.artifacts(campaign_id, "voice") if script and v.get("script_id") == script["id"]]
        voice = await st.artifact(campaign_id, body.voice_id, "voice") if body.voice_id else (voices[0] if voices else None)
        if not script or not sb or not voice:
            raise ValidationFailed("A spot needs a script, storyboard keyframes and a voice-over (CS-06/07/09).", code="inputs_missing", key="err.inputs_missing.all")
        kit = (await st.brand_kit(camp["brand_id"]))["kit"]
        rows = await st.repo.query("rights", {"kind": "music"}, pk=camp["brand_id"])
        reg = [RightsEntry(**{k: v for k, v in r.items() if k in RightsEntry.model_fields}) for r in rows]
        chosen = next((e for e in reg if e.id == camp.get("music_rights_id")), None) or next((e for e in reg if e.id == (script.get("music") or {}).get("rights_id")), None)
        mood = (script.get("music") or {}).get("mood", "warm")
        ms = music_spec(chosen, (script.get("music") or {}).get("reference_title", ""), mood)
        try:
            spec = build_master_spec(spec_id=new_id("spec"), campaign=camp, script=script, storyboard=sb, voice=voice, kit={**kit, "name": (await st.brand(camp["brand_id"]))["name"]}, music=ms, brief_fields=(brief or {}).get("fields"), aspect=body.aspect, lang=voice.get("lang", "en"), loudness_lufs=body.loudness_lufs, grade_strength=body.grade_strength, quality=body.quality)
        except SpotBuildError as exc:
            raise ValidationFailed(str(exc), code="inputs_missing", key=exc.key, params=exc.params or {"detail": str(exc)}) from exc
        if not cinematic:  # a cinematic render reports its own progress first (motion phase), then the composite
            await job.progress(0.08, step="render", key="job.msg.spot.composite", params={"dur": round(spec.duration, 1), "aspect": spec.aspect})
        art = await render_spec_to_asset(s, st, camp, spec, script_id=script["id"], storyboard_id=sb["id"], voice_id=voice["id"], talent=script.get("talent", []), actor=actor, job=job)
        await job.progress(0.9, step="guardian", key="job.msg.spot.guardian")
        art = await post_render(s, st, camp, art, actor)
        await st.set_stage(campaign_id, "production")
        await _settle_motion_flags(st, campaign_id, sb["id"], art)
        result = {"artifact_id": art["id"], "video_asset_id": art["assets"]["video"], "duration": art["probe"]["duration"], "loudness_lufs": art["loudness"]["integrated_lufs"], "guardian": art["guardian"], "render_seconds": art["render"]["render_seconds"]}
        return {**result, "quality": art["quality"], "motion": _motion_summary(art)} if cinematic else result

    return await submit_job(request, "spot.render", run, campaign_id, "job.title.render.cinematic" if cinematic else "job.title.render", "CS-08", wait, timeout=178, title_params={"aspect": body.aspect}, lane="motion" if cinematic else None)


async def _settle_motion_flags(st: Studio, campaign_id: str, storyboard_id: str, art: dict[str, Any]) -> None:
    """After a cinematic render the shots whose clip matches their current motion prompt are no longer ``motion_stale`` (re-read first: the user may have edited the storyboard meanwhile)."""
    m = (art.get("render") or {}).get("motion")
    if not m:
        return
    done = {x["shot_id"]: x.get("prompt_sha256") for x in m.get("shots", []) if x.get("status") in {"generated", "cached"}}
    try:
        sb = await st.artifact(campaign_id, storyboard_id, "storyboard")
    except NotFound:
        return
    changed = False
    for sh in sb.get("shots", []):
        if sh.get("motion_stale") and sh["id"] in done and motion_plan.shot_prompt_sha(sh, sb) == done[sh["id"]]:
            sh["motion_stale"], changed = False, True
    if changed:
        await st.save_artifact(sb)


@router.post("/{spot_id}/rerender", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def rerender(request: Request, campaign_id: str, spot_id: str, wait: bool = False, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    """Render again from the (possibly auto-revised) spec stored on the artifact. A cinematic spot finds its clips in the library again: no GPU call, no cost."""
    st = studio(request)
    source = await st.artifact(campaign_id, spot_id, "spot")
    cinematic = (source.get("spec") or {}).get("quality") == "cinematic"

    async def run(job: JobContext) -> dict[str, Any]:
        s = request.app.state.services
        camp = await st.campaign(campaign_id)
        src = await st.artifact(campaign_id, spot_id, "spot")
        spec = RenderSpec.model_validate(src["spec"])
        art = await render_spec_to_asset(s, st, camp, spec, script_id=src.get("script_id"), storyboard_id=src.get("storyboard_id"), voice_id=src.get("voice_id"), talent=src.get("talent", []), actor=actor, job=job, parent_id=spot_id, lineage_kind=src.get("lineage_kind", "master"), variant=src.get("variant"), markets=src.get("markets"))
        art = await post_render(s, st, camp, art, actor)
        result = {"artifact_id": art["id"], "video_asset_id": art["assets"]["video"], "guardian": art["guardian"]}
        return {**result, "quality": art["quality"], "motion": _motion_summary(art)} if cinematic else result

    return await submit_job(request, "spot.rerender", run, campaign_id, "job.title.rerender", "CS-08", wait, timeout=178, lane="motion" if cinematic else None)


@router.get("")
async def list_spots(request: Request, campaign_id: str) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)
    arts = await st.artifacts(campaign_id, "spot")
    slim = [{k: a.get(k) for k in ("id", "version", "status", "title", "created_at", "assets", "probe", "loudness", "guardian", "variant", "lineage_kind", "parent_id", "provenance_id", "needs_rerender", "markets")} | {"duration": a["spec"]["scenes"] and a["probe"]["duration"], "lang": a["spec"]["lang"], "aspect": a["spec"]["aspect"], "music": a["spec"].get("music"), "quality": a.get("quality") or a["spec"].get("quality", "preview"), "render": _with_reason_text(a).get("render")} for a in arts]
    return {"spots": slim, "provider": get_provider(svc(request).settings.video_provider).capabilities(), "aspects": list(ASPECTS)}


@router.get("/estimate")
async def estimate(
    request: Request,
    campaign_id: str,
    quality: str = Query(default="cinematic", pattern="^(preview|cinematic)$"),
    aspect: str = Query(default="16:9", pattern="^(16:9|9:16|1:1|4:5)$"),
    storyboard_id: str | None = None,
) -> dict[str, Any]:
    """What a render would cost and how long it would take: per shot (seconds, frames, already cached?), the GPU cold start when the worker is asleep, and whether the budget allows it."""
    s = svc(request)
    st = studio(request)
    camp = await st.campaign(campaign_id)
    caps = await s.guard.caps(campaign_id)
    daily_left, camp_left = float(caps["daily_remaining_usd"]), float(caps.get("campaign_remaining_usd", caps["daily_remaining_usd"]))
    body: dict[str, Any] = {"quality": quality, "aspect": aspect, "shots": [], "cached_shots": 0, "est_gpu_seconds": 0.0, "est_cost_usd": 0.0, "est_wall_seconds": 30.0, "cold_start_seconds": 0, "budget": {"allowed": True, "daily_remaining_usd": daily_left, "campaign_remaining_usd": camp_left, "reason": None}}
    if quality == "preview":
        return body
    sb = await (st.artifact(campaign_id, storyboard_id, "storyboard") if storyboard_id else st.latest(campaign_id, "storyboard"))
    if not sb:
        raise ValidationFailed("A spot needs a storyboard with keyframes (CS-07).", code="inputs_missing", key="err.inputs_missing.storyboard")
    script = await (st.artifact(campaign_id, sb["script_id"], "script") if sb.get("script_id") else st.latest(campaign_id, "script"))
    if not script:
        raise ValidationFailed("A spot needs a script, storyboard keyframes and a voice-over (CS-06/07/09).", code="inputs_missing", key="err.inputs_missing.all")
    status = await motion_status(s)
    cfg = s.settings
    scenes = scenes_from_storyboard(script, sb, campaign_lang(camp), strict=False)
    spec = RenderSpec(id="estimate", campaign_id=campaign_id, aspect=aspect, scenes=scenes)  # type: ignore[arg-type]
    shas: dict[str, str] = {}
    for sc in scenes:
        try:
            shas[sc.asset_id or ""] = (await st.asset(sc.asset_id or "", campaign_id))["sha256"]
        except NotFound:
            continue  # a keyframe that is not generated yet: nothing cached for it
    plan = motion_plan.plan_motion(spec, sb, cfg, model=status["model"], revision=status["revision"], license_name=status["license"], keyframe_sha=shas, campaign_id=campaign_id)
    cached = {sp.scene_id: await find_cached(st, campaign_id, sp) is not None for sp in plan.shots}
    todo = [sp for sp in plan.shots if not cached[sp.scene_id]]
    state = status["worker"]["state"]
    cold_wall = cfg.motion_cold_start_s if (todo and status["available"] and state != "ready") else 0
    cold_billed = cfg.motion_cold_start_s if (todo and status["available"] and state == "cold") else 0
    est_gpu = round(sum(sp.est_gpu_seconds for sp in todo) + cold_billed, 2)
    est_cost = round(pricing.motion_cost(est_gpu, cfg.motion_price_per_gpu_second), 5)
    reason: str | None = None
    if not status["available"]:
        reason = t("motion.estimate.unavailable")
    elif est_cost > daily_left + 1e-9:
        reason = t("motion.estimate.daily", est=est_cost, remaining=daily_left)
    elif est_cost > camp_left + 1e-9:
        reason = t("motion.estimate.campaign", est=est_cost, remaining=camp_left)
    body.update(
        shots=[{"shot_id": sp.shot_id, "seconds": sp.seconds, "frames": sp.frames, "cached": cached[sp.scene_id], "est_gpu_seconds": 0.0 if cached[sp.scene_id] else sp.est_gpu_seconds, "est_cost_usd": 0.0 if cached[sp.scene_id] else sp.est_cost_usd} for sp in plan.shots],
        cached_shots=sum(cached.values()), est_gpu_seconds=est_gpu, est_cost_usd=est_cost, est_wall_seconds=motion_plan.wall_seconds(todo, cold_wall), cold_start_seconds=cold_wall,
        cold_start_cost_usd=round(pricing.motion_cost(cold_billed, cfg.motion_price_per_gpu_second), 5), available=status["available"], mode=status["mode"], model=status["model"], license=status["license"],
        budget={"allowed": reason is None, "daily_remaining_usd": daily_left, "campaign_remaining_usd": camp_left, "reason": reason},
    )
    return body


@router.get("/{spot_id}")
async def get_spot(request: Request, campaign_id: str, spot_id: str) -> dict[str, Any]:
    a = await studio(request).artifact(campaign_id, spot_id, "spot")
    return _with_reason_text(a)


@router.get("/providers/info", include_in_schema=True)
async def providers(request: Request, campaign_id: str) -> dict[str, Any]:
    return {"active": svc(request).settings.video_provider, "compositor": get_provider("compositor").capabilities(), "external": get_provider("external").capabilities()}


__all__ = ["AppError", "NotFound", "best_replacement_track"]
FEATURE = Feature(
    id="CS-08",
    summary="ffmpeg-based spot compositor behind a VideoProvider interface: motion on keyframes or real AI-generated clips (cinematic quality, CS-25), dissolves, VO, burned-in captions + SRT, music bed, end card, EBU R128, H.264/AAC MP4.",
    router=router,
)
