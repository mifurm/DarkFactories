"""CS-08 Spot compositor / Video — keyframes + motion + VO + captions + music + end card; MP4 H.264/AAC via a VideoProvider."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...core.ai import pricing
from ...core.guardian_service import evaluate, subject_from_spot, summarize
from ...core.jobs import JobContext
from ...core.provenance import create_for_asset
from ...core.studio import Studio
from ...deps import mutate_limit, spend_limit, svc
from ...domain.rights import RightsEntry, best_replacement_track
from ...domain.spot_builder import SpotBuildError, build_master_spec, music_spec
from ...errors import AppError, NotFound, ValidationFailed
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
    """Render a spec with the configured VideoProvider and persist video/SRT/poster assets + the ``spot`` artifact."""
    images: dict[str, bytes] = {}
    for sc in spec.scenes:
        if sc.asset_id and sc.asset_id not in images:
            images[sc.asset_id] = await st.asset_bytes(await st.asset(sc.asset_id, campaign["id"]))
    vo_audio: dict[str, bytes] = {}
    for ln in spec.vo:
        if ln.asset_id:
            vo_audio[ln.id] = await st.asset_bytes(await st.asset(ln.asset_id, campaign["id"]))
    provider = get_provider(s.settings.video_provider, s.settings.render_timeout_s, s.settings.work_dir or None)

    async def progress(p: float, msg: str) -> None:
        if job:
            key, params = _render_message(msg)
            if key:
                await job.progress(0.1 + 0.75 * p, key=key, params=params)
            else:
                await job.progress(0.1 + 0.75 * p, msg)

    out = await provider.render(spec, images, vo_audio, progress)
    rs = out.meta.get("render_seconds", 0.0)
    cost = pricing.render_cost(rs)
    await s.meter.record(kind="render", model=f"compositor-{provider.name}", units={"render_seconds": rs, "frames": out.meta.get("frames"), "aspect": spec.aspect}, cost_usd=cost)
    tag = [spec.aspect.replace(":", "x"), spec.lang, lineage_kind]
    suffix = f"{spec.aspect.replace(':', 'x')}-{spec.lang}" + (f"-{variant['cutdown_s']}s" if variant and variant.get("cutdown_s") else "")
    video = await st.put_asset(campaign_id=campaign["id"], name=f"spot-{suffix}.mp4", data=out.video, mime="video/mp4", kind="video", actor=actor, tags=["spot", *tag], description=spec.title, meta={"probe": out.probe, "loudness": out.loudness, "spec_id": spec.id, "aspect": spec.aspect, "lang": spec.lang}, parent_id=None)
    srt = await st.put_asset(campaign_id=campaign["id"], name=f"spot-{suffix}.srt", data=out.srt.encode(), mime="application/x-subrip", kind="subtitle", actor=actor, tags=["captions", *tag], index=False)
    poster = await st.put_asset(campaign_id=campaign["id"], name=f"spot-{suffix}-poster.jpg", data=out.poster, mime="image/jpeg", kind="image", actor=actor, tags=["poster", *tag], index=False, meta={"derived_from": video["id"]})
    art = await st.create_artifact(
        campaign["id"], "spot",
        {"title": spec.title, "spec": spec.model_dump(mode="json"), "assets": {"video": video["id"], "srt": srt["id"], "poster": poster["id"]}, "probe": out.probe, "loudness": out.loudness, "render": out.meta,
         "script_id": script_id, "storyboard_id": storyboard_id, "voice_id": voice_id, "lineage_kind": lineage_kind, "variant": variant or {"aspect": spec.aspect, "lang": spec.lang, "cutdown_s": None}, "talent": talent, "markets": markets or campaign.get("markets", []), "cost_usd": round(cost, 5), "needs_rerender": False},
        actor=actor, parent_id=parent_id, status=status,
    )
    video["spot_id"] = art["id"]
    await st.save_asset(video)
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


@router.post("/render", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def render(request: Request, campaign_id: str, body: RenderIn | None = None, wait: bool = False, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    body = body or RenderIn()
    st = studio(request)
    await st.campaign(campaign_id)

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
            spec = build_master_spec(spec_id=new_id("spec"), campaign=camp, script=script, storyboard=sb, voice=voice, kit={**kit, "name": (await st.brand(camp["brand_id"]))["name"]}, music=ms, brief_fields=(brief or {}).get("fields"), aspect=body.aspect, lang=voice.get("lang", "en"), loudness_lufs=body.loudness_lufs, grade_strength=body.grade_strength)
        except SpotBuildError as exc:
            raise ValidationFailed(str(exc), code="inputs_missing", key=exc.key, params=exc.params or {"detail": str(exc)}) from exc
        await job.progress(0.08, step="render", key="job.msg.spot.composite", params={"dur": round(spec.duration, 1), "aspect": spec.aspect})
        art = await render_spec_to_asset(s, st, camp, spec, script_id=script["id"], storyboard_id=sb["id"], voice_id=voice["id"], talent=script.get("talent", []), actor=actor, job=job)
        await job.progress(0.9, step="guardian", key="job.msg.spot.guardian")
        art = await post_render(s, st, camp, art, actor)
        await st.set_stage(campaign_id, "production")
        return {"artifact_id": art["id"], "video_asset_id": art["assets"]["video"], "duration": art["probe"]["duration"], "loudness_lufs": art["loudness"]["integrated_lufs"], "guardian": art["guardian"], "render_seconds": art["render"]["render_seconds"]}

    return await submit_job(request, "spot.render", run, campaign_id, "job.title.render", "CS-08", wait, timeout=178, title_params={"aspect": body.aspect})


@router.post("/{spot_id}/rerender", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def rerender(request: Request, campaign_id: str, spot_id: str, wait: bool = False, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    """Render again from the (possibly auto-revised) spec stored on the artifact."""
    st = studio(request)
    await st.artifact(campaign_id, spot_id, "spot")

    async def run(job: JobContext) -> dict[str, Any]:
        s = request.app.state.services
        camp = await st.campaign(campaign_id)
        src = await st.artifact(campaign_id, spot_id, "spot")
        spec = RenderSpec.model_validate(src["spec"])
        art = await render_spec_to_asset(s, st, camp, spec, script_id=src.get("script_id"), storyboard_id=src.get("storyboard_id"), voice_id=src.get("voice_id"), talent=src.get("talent", []), actor=actor, job=job, parent_id=spot_id, lineage_kind=src.get("lineage_kind", "master"), variant=src.get("variant"), markets=src.get("markets"))
        art = await post_render(s, st, camp, art, actor)
        return {"artifact_id": art["id"], "video_asset_id": art["assets"]["video"], "guardian": art["guardian"]}

    return await submit_job(request, "spot.rerender", run, campaign_id, "job.title.rerender", "CS-08", wait, timeout=178)


@router.get("")
async def list_spots(request: Request, campaign_id: str) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)
    arts = await st.artifacts(campaign_id, "spot")
    slim = [{k: a.get(k) for k in ("id", "version", "status", "title", "created_at", "assets", "probe", "loudness", "guardian", "variant", "lineage_kind", "parent_id", "provenance_id", "needs_rerender", "markets")} | {"duration": a["spec"]["scenes"] and a["probe"]["duration"], "lang": a["spec"]["lang"], "aspect": a["spec"]["aspect"], "music": a["spec"].get("music")} for a in arts]
    return {"spots": slim, "provider": get_provider(svc(request).settings.video_provider).capabilities(), "aspects": list(ASPECTS)}


@router.get("/{spot_id}")
async def get_spot(request: Request, campaign_id: str, spot_id: str) -> dict[str, Any]:
    a = await studio(request).artifact(campaign_id, spot_id, "spot")
    return a


@router.get("/providers/info", include_in_schema=True)
async def providers(request: Request, campaign_id: str) -> dict[str, Any]:
    return {"active": svc(request).settings.video_provider, "compositor": get_provider("compositor").capabilities(), "external": get_provider("external").capabilities()}


__all__ = ["AppError", "NotFound", "best_replacement_track"]
FEATURE = Feature(id="CS-08", summary="ffmpeg-based spot compositor behind a VideoProvider interface: motion on keyframes, dissolves, VO, burned-in captions + SRT, music bed, end card, EBU R128, H.264/AAC MP4.", router=router)
