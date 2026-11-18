"""Cinematic-motion orchestration: from a spot's scenes to AI clips the compositor can play.

For every scene: library-cache lookup (a longer cached clip satisfies a shorter request) -> budget authorisation (campaign + daily caps; a refusal spends
nothing) -> generation on the GPU worker, one clip at a time (the quota is one GPU) -> content-safety check of first / middle / last frame -> the clip is stored as
a library asset -> the usage meter records the GPU seconds. A shot that fails, times out, is refused by the budget guard or is flagged by Content Safety falls back
to the still-image (Ken-Burns) path and is reported; the spot always renders.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from ..core.ai import pricing
from ..core.jobs import JobCancelled, JobContext
from ..domain.guardian import GuardianSubject, SafetyObs
from ..errors import AppError, BudgetExceeded
from ..roles import Actor
from ..video import media
from ..video.renderer import cover_box
from ..video.spec import RenderSpec
from . import plan as planner
from . import wire
from .models import MotionError, MotionProgress, MotionRequest, MotionResult, ProgressCb
from .plan import MotionPlan, ShotPlan

log = logging.getLogger("spotlight.motion")

NEXT_SHOT_TIMEOUT_S = 600.0  # after the first clip (which may include the cold start) a single clip must not take longer than this
BREAKER_AFTER = 2  # consecutive timeouts / unreachable worker: stop asking, fall back for the rest
FLAG_FROM = SafetyObs().block_at  # Content Safety severity at which the Guardian blocks an image


@dataclass
class ShotOutcome:
    scene_id: str
    shot_id: str
    status: str  # generated | cached | fallback
    plan: ShotPlan
    reason: str | None = None  # fallback only, one of models.FALLBACK_REASONS: oom | timeout | safety | budget | worker_unavailable | bad_request | internal | disabled
    detail: str = ""
    asset_id: str | None = None
    clip: bytes | None = None
    gpu_seconds: float = 0.0  # spent by THIS render (0 for a cache hit)
    cost_usd: float = 0.0
    frames: int = 0
    transport_cached: bool = False  # generate() was answered by an earlier worker result (still no GPU time)
    safety_max: int | None = None
    model: str = ""  # what actually produced the clip (the worker reports it; a cache hit carries what the asset recorded)
    revision: str = ""

    @property
    def has_clip(self) -> bool:
        return self.status != "fallback"


def license_of(model: str, revision: str, default: str = "") -> str:
    """Licence of the model that made a clip. The worker's fake pipeline (revision ``fake``) is no generative model at all and never claims a licence."""
    if revision == "fake":
        return "n/a (fake pipeline, no generative model)"
    return wire.MODEL_LICENSES.get(model) or default


@dataclass
class MotionOutcome:
    plan: MotionPlan
    mode: str
    host: str
    shots: list[ShotOutcome] = field(default_factory=list)
    cold_start_usd: float = 0.0
    cold_start_s: float = 0.0

    @property
    def clips(self) -> dict[str, bytes]:
        """scene id -> mp4 for the compositor (only the scenes that have a clip; the others render the Ken-Burns still)."""
        return {o.scene_id: o.clip for o in self.shots if o.clip is not None and o.has_clip}

    def apply(self, spec: RenderSpec) -> None:
        """Write the result onto the spec: which scene plays which clip, and the recipe that reproduces it."""
        by_scene = {o.scene_id: o for o in self.shots}
        for sc in spec.scenes:
            o = by_scene.get(sc.id)
            if o is not None and o.has_clip and o.asset_id:
                sc.clip_asset_id, sc.clip = o.asset_id, o.plan.clip_spec(o.frames or None)
            else:
                sc.clip_asset_id, sc.clip = None, None
        spec.quality = "cinematic"
        spec.motion = self.plan.recipe(self.mode)

    def report(self) -> dict[str, Any]:
        """``render.motion`` of the spot artifact. ``shots_generated`` counts every shot that carries AI motion in the final video (fresh or from the cache),
        ``shots_cached`` those of them that came from the cache, so ``shots_generated + len(shots_fallback) == shots_total``. ``model`` / ``revision`` are what actually
        made the clips (as reported by the worker), not what was configured."""
        carry = [o for o in self.shots if o.has_clip]
        used = {(o.model or self.plan.model, o.revision or self.plan.revision) for o in carry}
        model, revision = next(iter(used)) if len(used) == 1 else (self.plan.model, self.plan.revision)
        gpu = round(sum(o.gpu_seconds for o in self.shots), 2)
        return {
            "mode": self.mode,
            "model": model,
            "revision": revision,
            "license": license_of(model, revision, self.plan.license),
            "host": self.host,
            "steps": self.plan.steps,
            "guidance": self.plan.guidance,
            "shots_total": len(self.shots),
            "shots_generated": len(carry),
            "shots_cached": sum(1 for o in carry if o.status == "cached"),
            "shots_fallback": [{"shot_id": o.shot_id, "reason": o.reason or "internal", "detail": o.detail[:240]} for o in self.shots if not o.has_clip],
            "gpu_seconds": gpu,
            "cost_usd": round(sum(o.cost_usd for o in self.shots) + self.cold_start_usd, 6),
            "cold_start_s": self.cold_start_s,
            "cold_start_usd": round(self.cold_start_usd, 6),
            "seed_base": self.plan.seed_base,
            "shots": [
                {
                    "shot_id": o.shot_id, "scene_id": o.scene_id, "status": o.status, "reason": o.reason, "seed": o.plan.seed, "prompt_sha256": planner.prompt_sha256(o.plan.prompt, o.plan.negative),
                    "frames": o.frames or o.plan.frames, "width": o.plan.width, "height": o.plan.height, "gpu_seconds": round(o.gpu_seconds, 2), "cost_usd": round(o.cost_usd, 6), "asset_id": o.asset_id,
                    "safety_max": o.safety_max,
                }
                for o in self.shots
            ],
        }


# ------------------------------------------------------------------------------------------------ helpers


def crop_keyframe(image: bytes, width: int, height: int, focal: tuple[float, float]) -> bytes:
    """The opening frame, framed here and not left to the worker's blind centre-crop: the keyframe (3:2) is cover-cropped to the clip's aspect AROUND THE SHOT'S FOCAL POINT
    — the very window the compositor uses for the still (``renderer.cover_box`` at zoom 1.0), so the subject stays in view in every aspect — and Lanczos-resized to exactly
    ``width`` x ``height``. These JPEG bytes are what is uploaded as ``image.jpg``; the job id's ``image_sha256`` is their hash. The worker's own centre-crop then has nothing to do."""
    im = Image.open(io.BytesIO(image)).convert("RGB")
    box = cover_box(im.width, im.height, width, height, 1.0, min(1.0, max(0.0, focal[0])), min(1.0, max(0.0, focal[1])))
    out = im.resize((width, height), Image.Resampling.LANCZOS, box=box)
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=95, subsampling=0)
    return buf.getvalue()


def inspect_clip(data: bytes, work_dir: str | None) -> tuple[dict[str, Any], dict[str, bytes]]:
    """ffprobe the clip and pull its first / middle / last frame (JPEG) for the content-safety check. Raises MediaError for anything that is not a playable video."""
    with tempfile.TemporaryDirectory(prefix="clip-", dir=work_dir or None) as td:
        path = Path(td) / "clip.mp4"
        path.write_bytes(data)
        info = media.probe(path)
        if not info.get("video") or float(info.get("duration") or 0) < 0.3:
            raise media.MediaError("the generated clip has no playable video stream")
        dur = float(info["duration"])
        return info, {name: media.extract_frame(path, max(0.0, (dur - 0.05) * frac)) for name, frac in (("first", 0.0), ("middle", 0.5), ("last", 1.0))}


async def find_cached(st: Any, campaign_id: str, shot: ShotPlan) -> dict[str, Any] | None:
    """A clip asset of this campaign made from the same keyframe, prompt, seed and settings that is at least as long as needed (the shortest such clip wins)."""
    rows = await st.repo.query("assets", {"kind": "video", "meta.motion_key": shot.cache_key}, pk=campaign_id)
    ok = [r for r in rows if int((r.get("meta") or {}).get("frames", 0)) >= shot.frames]
    return min(ok, key=lambda r: int(r["meta"]["frames"])) if ok else None


def client_license(client: Any, default_model: str = "") -> str:
    """The licence of the model behind a motion client (an ``off`` client has no model of its own: the configured one)."""
    return client.license or wire.MODEL_LICENSES.get(client.model or default_model, "")


async def motion_status(s: Any) -> dict[str, Any]:
    """The ``GET /api/motion/status`` body. Never raises: a storage problem is reported as ``available: false`` with a reason."""
    client, cfg = s.motion, s.settings
    st = await client.status()
    reason = "off" if client.name == "off" else ("unreachable" if st.error else None)
    model = client.model or cfg.motion_model
    return {
        "mode": client.name,
        "available": client.name != "off" and not st.error,
        "model": model,
        "license": client_license(client, cfg.motion_model),
        "worker": {"state": st.state, "age_s": st.age_s, "queue_depth": st.queue_depth},
        "price_per_gpu_second": cfg.motion_price_per_gpu_second,
        "est_cold_start_s": cfg.motion_cold_start_s,
        "max_clip_s": planner.MAX_CLIP_S,
        "revision": client.revision,
        "host": client.host,
        "steps": cfg.motion_steps,
        "high": bool(cfg.motion_high),
        "reason": reason,
    }


async def request_warmup(s: Any) -> dict[str, Any]:
    """Wake the GPU worker if it is asleep and account for the cold start (estimated GPU seconds, against the daily / campaign caps — fails closed).

    Returns ``{"status": WorkerStatus, "requested": bool, "cost_usd": float, "seconds": float}``; a worker that is ready / warming costs nothing extra."""
    client, cfg = s.motion, s.settings
    before = await client.status()
    if client.name == "off" or before.error or before.state != "cold":
        return {"status": before, "requested": False, "cost_usd": 0.0, "seconds": 0.0}
    seconds = float(cfg.motion_cold_start_s)
    cost = pricing.motion_cost(seconds, cfg.motion_price_per_gpu_second)
    await s.guard.authorize(cost, kind="motion", model=client.model)
    after = await client.warmup()
    if not after.requested:  # somebody else woke it in the meantime
        return {"status": after, "requested": False, "cost_usd": 0.0, "seconds": 0.0}
    await s.meter.record(kind="motion", model=client.model, units={"gpu_seconds": seconds, "warmup": True, "estimated": True, "shots": 0}, cost_usd=cost)
    return {"status": after, "requested": True, "cost_usd": cost, "seconds": seconds}


# ------------------------------------------------------------------------------------------------ the motion phase of a render


async def generate_clips(
    s: Any,
    st: Any,
    campaign: dict[str, Any],
    spec: RenderSpec,
    *,
    storyboard: Mapping[str, Any] | None,
    images: Mapping[str, bytes],
    job: JobContext | None = None,
    actor: Actor | None = None,
    progress_from: float = 0.06,
    progress_to: float = 0.55,
) -> MotionOutcome:
    """Resolve a clip for every scene of ``spec``: cached, generated now, or (reported) fallback to the still. See the module docstring for the order of the checks."""
    client, cfg = s.motion, s.settings
    cid = campaign["id"]
    keyframe_sha = {aid: hashlib.sha256(data).hexdigest() for aid, data in images.items()}
    plan = planner.plan_motion(spec, storyboard, cfg, model=client.model, revision=client.revision, license_name=client.license, keyframe_sha=keyframe_sha, campaign_id=cid)
    out = MotionOutcome(plan=plan, mode=client.name, host=client.host)
    total = len(plan.shots)
    if total == 0:
        return out

    async def say(frac: float, key: str, **params: Any) -> None:
        if job is not None:
            await job.progress(progress_from + (progress_to - progress_from) * min(1.0, max(0.0, frac)), key=key, params=params)

    cached: dict[str, dict[str, Any]] = {}
    for sp in plan.shots:
        asset = await find_cached(st, cid, sp)
        if asset is not None:
            cached[sp.scene_id] = asset
    todo = [sp for sp in plan.shots if sp.scene_id not in cached]
    est = sum(sp.est_cost_usd for sp in todo)
    await say(0.0, "job.msg.motion.estimate", shots=total, cached=len(cached), cost=round(est, 4))

    if todo:  # one authorisation for everything that will be generated: a refusal here has spent nothing
        status = await client.status()
        cold_usd = pricing.motion_cost(cfg.motion_cold_start_s, cfg.motion_price_per_gpu_second) if (client.name != "off" and status.state == "cold" and not status.error) else 0.0
        await s.guard.authorize(est + cold_usd, kind="motion", model=client.model)
        if status.state != "ready":
            await say(0.01, "job.msg.motion.warming", s=0)
        try:
            warm = await request_warmup(s)
            out.cold_start_usd, out.cold_start_s = warm["cost_usd"], warm["seconds"]
        except BudgetExceeded:
            raise
        except Exception as exc:  # warm-up is best effort: the first generate() call wakes the worker too
            log.warning("motion warm-up failed: %s", exc)

    started = time.monotonic()
    infra_failures = 0
    breaker: tuple[str, str] | None = None
    for n, sp in enumerate(plan.shots, start=1):
        frac_done = (n - 1) / total
        hit = cached.get(sp.scene_id)
        if hit is not None:
            try:
                clip = await st.asset_bytes(hit)
            except Exception:  # the blob behind the cache entry is gone: generate it again
                hit, clip = None, b""
            if hit is not None:
                out.shots.append(
                    ShotOutcome(
                        scene_id=sp.scene_id, shot_id=sp.shot_id, status="cached", plan=sp, asset_id=hit["id"], clip=clip, frames=int(hit["meta"].get("frames", sp.frames)),
                        model=str(hit["meta"].get("model") or plan.model), revision=str(hit["meta"].get("revision") or plan.revision), safety_max=hit["meta"].get("safety_max"),
                    )
                )
                await s.meter.record(kind="motion", model=plan.model, units={"gpu_seconds": 0.0, "frames": sp.frames, "shots": 1, "w": sp.width, "h": sp.height}, cost_usd=0.0, cached=True)
                await say(frac_done + 0.5 / total, "job.msg.motion.cached", n=n)
                continue
        if breaker is not None:
            out.shots.append(ShotOutcome(scene_id=sp.scene_id, shot_id=sp.shot_id, status="fallback", plan=sp, reason=breaker[0], detail=breaker[1]))
            await say(frac_done + 0.5 / total, "job.msg.motion.fallback", n=n)
            continue
        remaining = cfg.motion_timeout_s - (time.monotonic() - started)
        if remaining < 5:
            out.shots.append(ShotOutcome(scene_id=sp.scene_id, shot_id=sp.shot_id, status="fallback", plan=sp, reason="timeout", detail="the motion time budget of this render is used up"))
            await say(frac_done + 0.5 / total, "job.msg.motion.fallback", n=n)
            continue

        async def relay(p: MotionProgress, n: int = n, frac_done: float = frac_done) -> None:
            if p.state == "running":
                await say(frac_done + max(p.progress, 0.0) / total, "job.msg.motion.shot", n=n, total=total, pct=round(min(1.0, p.progress), 3))
            elif p.worker_state in {"cold", "warming"} and n == 1:
                await say(frac_done, "job.msg.motion.warming", s=int(p.waited_s))
            else:
                await say(frac_done, "job.msg.motion.shot", n=n, total=total, pct=0.0)

        outcome = await _one_shot(s, st, cid, plan, sp, images, relay, timeout_s=remaining if n == 1 else min(remaining, NEXT_SHOT_TIMEOUT_S), actor=actor)
        out.shots.append(outcome)
        if outcome.status == "fallback":
            await say(frac_done + 1.0 / total, "job.msg.motion.fallback", n=n)
            infra_failures = infra_failures + 1 if outcome.reason in {"timeout", "worker_unavailable"} else 0
            if infra_failures >= BREAKER_AFTER:
                breaker = (outcome.reason or "worker_unavailable", "skipped: the motion worker did not respond to the previous shots")
        else:
            infra_failures = 0
    return out


async def _one_shot(s: Any, st: Any, cid: str, plan: MotionPlan, sp: ShotPlan, images: Mapping[str, bytes], relay: ProgressCb, *, timeout_s: float, actor: Actor | None) -> ShotOutcome:
    client, cfg = s.motion, s.settings

    def fallback(reason: str, detail: str, **kw: Any) -> ShotOutcome:
        return ShotOutcome(scene_id=sp.scene_id, shot_id=sp.shot_id, status="fallback", plan=sp, reason=reason, detail=detail, **kw)

    try:
        await s.guard.authorize(sp.est_cost_usd, kind="motion", model=client.model)  # the up-front check covered the render; this one covers spend by other jobs in the meantime
        request = MotionRequest(
            prompt=sp.prompt, negative_prompt=sp.negative, image=crop_keyframe(images[sp.asset_id], sp.width, sp.height, sp.focal), width=sp.width, height=sp.height, num_frames=sp.frames,
            seed=sp.seed, fps=sp.fps, steps=sp.steps, guidance_scale=sp.guidance, model=client.model, revision=client.revision, campaign_id=cid, shot_id=sp.shot_id,
        )
        res: MotionResult = await client.generate(request, relay, timeout_s)
    except JobCancelled:
        raise
    except BudgetExceeded as exc:
        return fallback("budget", exc.message)
    except MotionError as exc:
        log.warning("motion shot %s fell back to the still path: %s", sp.shot_id, exc.message)
        wasted = float(getattr(exc, "gpu_seconds", 0.0) or 0.0)  # a failed attempt still ran on the GPU
        wasted_usd = pricing.motion_cost(wasted, cfg.motion_price_per_gpu_second)
        if wasted > 0:
            await s.meter.record(kind="motion", model=client.model, units={"gpu_seconds": wasted, "frames": sp.frames, "shots": 0, "failed": True, "w": sp.width, "h": sp.height}, cost_usd=wasted_usd)
        return fallback(exc.reason, exc.message, gpu_seconds=wasted, cost_usd=wasted_usd)
    except AppError as exc:
        return fallback("internal", exc.message)
    except Exception as exc:
        log.exception("motion shot %s failed", sp.shot_id)
        return fallback("internal", f"{type(exc).__name__}: {str(exc)[:160]}")

    cost = 0.0 if res.cached else pricing.motion_cost(res.gpu_seconds, cfg.motion_price_per_gpu_second)
    await s.meter.record(
        kind="motion", model=res.model, units={"gpu_seconds": 0.0 if res.cached else res.gpu_seconds, "frames": res.num_frames, "shots": 1, "w": res.width, "h": res.height}, cost_usd=cost, cached=res.cached,
    )
    spent: dict[str, Any] = {"gpu_seconds": 0.0 if res.cached else res.gpu_seconds, "cost_usd": cost, "transport_cached": res.cached}
    try:
        info, frames = await asyncio.to_thread(inspect_clip, res.clip, cfg.work_dir or None)
    except media.MediaError as exc:
        log.warning("motion shot %s: the clip is not a playable video: %s", sp.shot_id, str(exc)[:300])
        return fallback("internal", "the generated clip could not be read as a video", **spent)  # the worker returned something that is not a playable video (the ffprobe output stays in the log)
    obs = await st.gather_safety(GuardianSubject(), image_bytes={f"{sp.shot_id}:{k}": v for k, v in frames.items()})
    worst = max((int(v.get("max", 0)) for v in obs.images.values()), default=0)
    if worst >= FLAG_FROM:
        return fallback("safety", f"Content Safety flagged the clip (severity {worst})", safety_max=worst, **spent)
    meta = {
        "motion_key": sp.cache_key, "model": res.model, "revision": res.revision, "seed": sp.seed, "prompt": sp.prompt, "prompt_sha256": planner.prompt_sha256(sp.prompt, sp.negative), "frames": res.num_frames,
        "fps": res.fps, "width": res.width, "height": res.height, "steps": sp.steps, "guidance": sp.guidance, "gpu_seconds": res.gpu_seconds, "job_id": res.job_id, "shot_id": sp.shot_id,
        "scene_id": sp.scene_id, "mode": client.name, "duration": round(float(info.get("duration") or 0), 3), "safety_max": worst,
    }
    asset = await st.put_asset(
        campaign_id=cid, name=f"motion-{sp.shot_id}-{res.width}x{res.height}.mp4", data=res.clip, mime="video/mp4", kind="video", actor=actor, tags=["motion-clip", sp.shot_id], index=False,
        description=f"AI motion clip · {sp.shot_id} · {res.width}x{res.height}, {res.num_frames} frames", meta=meta,
    )
    return ShotOutcome(scene_id=sp.scene_id, shot_id=sp.shot_id, status="generated", plan=sp, asset_id=asset["id"], clip=res.clip, frames=res.num_frames, safety_max=worst, model=res.model, revision=res.revision, **spent)
