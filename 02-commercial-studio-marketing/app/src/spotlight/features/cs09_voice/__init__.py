"""CS-09 Voice & audio agent — VO in multiple voices/languages (tts-hd + Azure AI Speech neural), timing to script, SRT,
loudness normalisation (at render) and licensed-music selection from the Rights Registry."""

from __future__ import annotations

import asyncio
import io
import wave
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from ...core.ai.voices import default_voice
from ...core.jobs import JobContext
from ...core.studio import Studio
from ...deps import mutate_limit, spend_limit, svc
from ...domain.rights import RightsEntry, check_use, is_cleared
from ...domain.timing import fit_line
from ...errors import AppError, NotFound, ValidationFailed
from ...registry import Feature
from ...roles import Actor, require
from ...video import media
from ...video.music import generate_track
from ...video.spec import VoLine, make_captions, to_srt
from ..common import studio
from ..jobs_util import submit_job

camp_router = APIRouter(prefix="/api/campaigns/{campaign_id}/audio", tags=["CS-09 Voice & Audio"])
glob_router = APIRouter(prefix="/api/audio", tags=["CS-09 Voice & Audio"])
_PREVIEWS: dict[tuple[str, int], bytes] = {}


@glob_router.get("/voices")
async def voices(request: Request, lang: str | None = None) -> dict[str, Any]:
    vs = svc(request).speech.voices()
    return {"voices": [v.__dict__ for v in vs if not lang or v.lang in (lang, "*")], "default_by_lang": {code: default_voice(code) for code in ("en", "de", "fr", "es", "it", "pl", "pt", "nl")}}


class SampleIn(BaseModel):
    voice: str = Field(default="openai:nova", max_length=80)
    text: str = Field(default="Some mornings deserve a slower start.", min_length=2, max_length=120)
    lang: str = "en"


@glob_router.post("/voices/sample", dependencies=[Depends(spend_limit)])
async def voice_sample(request: Request, body: SampleIn, _: Actor = Depends(require("generate"))) -> Response:
    res = await svc(request).speech.synthesize(body.text, voice=body.voice, lang=body.lang)
    return Response(res.data, media_type=res.mime, headers={"Cache-Control": "private, max-age=3600"})


def _rights(rows: list[dict[str, Any]]) -> list[RightsEntry]:
    return [RightsEntry(**{k: v for k, v in r.items() if k in RightsEntry.model_fields}) for r in rows]


@glob_router.get("/music/{rights_id}/preview.wav")
async def music_preview(request: Request, rights_id: str, seconds: int = 10) -> Response:
    row = await studio(request).repo.get("rights", rights_id, pk="northwind")
    if not row or not row.get("library_track"):
        raise NotFound("no library track with that id", code="track_not_found")
    seconds = min(max(seconds, 3), 20)
    key = (rights_id, seconds)
    if key not in _PREVIEWS:
        lt = row["library_track"]
        audio = await asyncio.to_thread(generate_track, lt["mood"], lt["bpm"], lt["key"], lt["seed"], float(seconds))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(media.SR)
            wf.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        _PREVIEWS[key] = buf.getvalue()
    return Response(_PREVIEWS[key], media_type="audio/wav", headers={"Cache-Control": "public, max-age=86400"})


@camp_router.get("/music")
async def music_candidates(request: Request, campaign_id: str) -> dict[str, Any]:
    st = studio(request)
    camp = await st.campaign(campaign_id)
    rows = await st.repo.query("rights", {"kind": "music"}, pk=camp["brand_id"])
    script = await st.latest(campaign_id, "script")
    want = ((script or {}).get("music") or {}).get("mood")
    out = []
    for e in _rights(rows):
        verdicts = check_use(e, camp.get("markets", ["US"]), camp.get("channels", []), camp.get("air_start"), camp.get("air_end"))
        out.append({
            "rights_id": e.id, "title": e.title, "licensor": e.licensor, "status": e.status, "library_track": e.library_track,
            "cleared": is_cleared(verdicts), "verdicts": [v.model_dump() for v in verdicts if v.severity != "info"],
            "mood_match": bool(want and e.library_track and e.library_track.get("mood") == want),
            "preview_url": f"/api/audio/music/{e.id}/preview.wav" if e.library_track else None,
        })
    out.sort(key=lambda r: (not r["cleared"], not r["mood_match"], r["title"]))
    return {"candidates": out, "selected": camp.get("music_rights_id"), "wanted_mood": want}


class MusicSelect(BaseModel):
    rights_id: str


@camp_router.post("/music/select", dependencies=[Depends(mutate_limit)])
async def select_music(request: Request, campaign_id: str, body: MusicSelect, actor: Actor = Depends(require("campaign.write"))) -> dict[str, Any]:
    st = studio(request)
    camp = await st.campaign(campaign_id)
    row = await st.repo.get("rights", body.rights_id, pk=camp["brand_id"])
    if not row or row["kind"] != "music" or not row.get("library_track"):
        raise NotFound("not a library music track", code="track_not_found")
    verdicts = check_use(_rights([row])[0], camp.get("markets", ["US"]), camp.get("channels", []), camp.get("air_start"), camp.get("air_end"))
    if not is_cleared(verdicts):
        raise AppError("This track is not cleared for the campaign: " + "; ".join(v.message for v in verdicts if v.severity == "block"), code="rights_blocked", status=422)
    camp["music_rights_id"] = body.rights_id
    await st.save_campaign(camp)
    script = await st.latest(campaign_id, "script")
    if script:
        script["music"].update(rights_id=body.rights_id, title=row["title"], reference_title=row["title"], mood=row["library_track"]["mood"], library_track=row["library_track"])
        await st.save_artifact(script)
    await st.audit(campaign_id, actor, "audio.music_selected", {"rights_id": body.rights_id}, {"title": row["title"]})
    return {"selected": body.rights_id, "title": row["title"]}


class VoiceIn(BaseModel):
    script_id: str | None = None
    voice: str | None = Field(default=None, max_length=80)
    lang: str = Field(default="en", pattern="^(en|de|fr|es|it|pl|pt|nl)$")
    gender: str = Field(default="female", pattern="^(female|male)$")
    speed: float = Field(default=1.0, ge=0.7, le=1.3)


@camp_router.post("/generate", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def generate(request: Request, campaign_id: str, body: VoiceIn | None = None, wait: bool = False, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    body = body or VoiceIn()
    st = studio(request)
    await st.campaign(campaign_id)

    async def run(job: JobContext) -> dict[str, Any]:
        return await build_voice(request.app.state.services, campaign_id, body.script_id, body.lang, body.voice, body.gender, body.speed, actor, job)

    return await submit_job(request, "audio.voice", run, campaign_id, "Sound Designer: voice-over", "CS-09", wait, timeout=175)


async def build_voice(s: Any, campaign_id: str, script_id: str | None, lang: str, voice: str | None, gender: str, speed: float, actor: Actor, job: JobContext, script_override: dict[str, Any] | None = None, label: str = "voice") -> dict[str, Any]:
    """Synthesize every VO line, fit it into its beat window, write SRT, persist assets + the ``voice`` artifact."""
    st = Studio(s)
    script = script_override or await (st.artifact(campaign_id, script_id, "script") if script_id else st.latest(campaign_id, "script"))
    if not script:
        raise ValidationFailed("Generate a script first (CS-06).", code="script_missing")
    voice = voice or default_voice(lang, gender)
    beats = [b for b in script["beats"] if (b.get("vo") or "").strip()]
    if not beats:
        raise ValidationFailed("The script has no voice-over lines.", code="no_vo")
    sem = asyncio.Semaphore(3)
    lines: list[dict[str, Any]] = [{}] * len(beats)
    done = 0

    async def one(i: int, b: dict[str, Any]) -> None:
        nonlocal done
        async with sem:
            text = b["vo"].strip()
            res = await s.speech.synthesize(text, voice=voice, lang=lang, speed=speed)
            nat = await asyncio.to_thread(media.audio_duration, res.data)
            fit = fit_line(b["t_start"], b["t_end"], nat)
            if fit["speed"] > 1.03:
                res = await s.speech.synthesize(text, voice=voice, lang=lang, speed=min(1.6, speed * fit["speed"]))
                nat2 = await asyncio.to_thread(media.audio_duration, res.data)
            else:
                nat2 = nat
            asset = await st.put_asset(campaign_id=campaign_id, name=f"{label}-{lang}-{b['id']}.{'wav' if res.mime == 'audio/wav' else 'mp3'}", data=res.data, mime=res.mime, kind="audio", actor=actor, tags=["voice-over", lang, "ai-generated"], description=text, meta={"voice": res.voice, "lang": lang, "chars": res.chars, "cached": res.cached, "cost_usd": res.cost_usd}, index=False)
            lines[i] = {"id": f"v{i + 1}", "beat_id": b["id"], "text": text, "start": fit["start"], "duration": round(nat2, 3), "speed": fit["speed"], "natural_duration": round(nat, 3), "asset_id": asset["id"], "overflow": fit["overflow"], "voice": res.voice, "cost_usd": res.cost_usd}
            done += 1
            await job.progress(0.1 + 0.75 * done / len(beats), f"Line {done}/{len(beats)} voiced", step=f"line-{i + 1}")

    await job.progress(0.05, f"Voicing {len(beats)} lines with {voice}", step="tts")
    await asyncio.gather(*(one(i, b) for i, b in enumerate(beats)))
    vo = [VoLine(id=ln["id"], text=ln["text"], start=ln["start"], duration=ln["duration"], asset_id=ln["asset_id"], speed=ln["speed"], beat_id=ln["beat_id"]) for ln in lines]
    cues = make_captions(vo)
    srt = to_srt(cues)
    srt_asset = await st.put_asset(campaign_id=campaign_id, name=f"captions-{lang}.srt", data=srt.encode("utf-8"), mime="application/x-subrip", kind="subtitle", actor=actor, tags=["captions", lang], index=False)
    art = await st.create_artifact(
        campaign_id, "voice",
        {"title": f"Voice-over ({lang})", "script_id": script["id"], "lang": lang, "voice": voice, "speed": speed, "lines": lines, "captions": [c.model_dump() for c in cues], "srt_asset_id": srt_asset["id"],
         "total_vo_seconds": round(sum(ln["duration"] for ln in lines), 2), "overflow_lines": [ln["id"] for ln in lines if ln["overflow"]], "cost_usd": round(sum(ln["cost_usd"] for ln in lines), 5)},
        actor=actor,
    )
    await st.audit(campaign_id, actor, "audio.voice_generated", {"artifact_id": art["id"]}, {"voice": voice, "lang": lang, "lines": len(lines)})
    return {"artifact_id": art["id"], "lines": len(lines), "voice": voice, "overflow": art["overflow_lines"]}


@camp_router.get("")
async def get_audio(request: Request, campaign_id: str) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)
    arts = await st.artifacts(campaign_id, "voice")
    return {"latest": arts[0] if arts else None, "versions": [{"id": a["id"], "lang": a["lang"], "voice": a["voice"], "created_at": a["created_at"], "total_vo_seconds": a["total_vo_seconds"]} for a in arts]}


FEATURE = Feature(
    id="CS-09",
    summary="Voice-over via tts-hd or Azure AI Speech neural voices in 8 languages, fitted to script beats, SRT, licensed-music selection from the Rights Registry, EBU R128 normalisation.",
    router=APIRouter(),
)
FEATURE.router.include_router(camp_router)  # type: ignore[union-attr]
FEATURE.router.include_router(glob_router)  # type: ignore[union-attr]
