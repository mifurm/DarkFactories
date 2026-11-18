"""Motion plan: for every scene of a spot, the clip to generate — size, frame count, retiming, deterministic seed, cache key and a cost estimate.

Pure functions (no I/O): the estimate endpoint, the orchestrator and the tests all use the same maths.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..core.ai import pricing
from ..video.spec import ClipSpec, MotionShot, MotionSpec, RenderSpec
from . import wire
from .models import NEGATIVE_PROMPT
from .prompts import build_motion_prompt

RESOLUTIONS: dict[str, tuple[int, int]] = {"16:9": (1024, 576), "9:16": (576, 1024), "1:1": (768, 768), "4:5": (640, 800)}
HIGH_RESOLUTIONS: dict[str, tuple[int, int]] = {"16:9": (1280, 704)}
DISSOLVE_S = 0.42  # TD of the compositor: the clip must also cover half a dissolve on each side of its scene
MARGIN_S = 0.15
MAX_SLOWMO = 1.35
MAX_CLIP_S = 5.0  # what the UI says: the longest clip the model produces
GENERATE_OVERHEAD_S = 6.0  # blob upload/download, queue pick-up and the 3 s polling around one generation
COMPOSITE_S = 45.0  # the ffmpeg compositor pass after the clips are in


def resolution_for(aspect: str, high: bool = False) -> tuple[int, int]:
    """Native clip size per aspect (multiples of 32, as the model requires); ``MOTION_HIGH=1`` raises 16:9 to 1280x704."""
    if high and aspect in HIGH_RESOLUTIONS:
        return HIGH_RESOLUTIONS[aspect]
    return RESOLUTIONS.get(aspect, RESOLUTIONS["16:9"])


def frames_for(needed_s: float, fps: int = wire.FPS) -> int:
    """Frames covering ``needed_s``: rounded up to 4n+1 (the model's frame grid) and clamped to 25..121."""
    raw = max(1, math.ceil(needed_s * fps - 1e-9))
    frames = 4 * math.ceil((raw - 1) / 4) + 1
    return max(wire.MIN_FRAMES, min(wire.MAX_FRAMES, frames))


@dataclass(frozen=True)
class Timing:
    needed_s: float
    frames: int
    speed: float  # playback speed: 1.0 = real time, 1/1.35 = the slowest slow motion
    hold_tail: bool  # the clip, even slowed down, ends before the scene: hold its last frame and keep a gentle push going


def timing_for(scene_duration_s: float, fps: int = wire.FPS) -> Timing:
    """Frames + retiming for a scene: duration + one dissolve + a small safety margin; beyond 5 s the clip is slowed down (up to 1.35x) and then held."""
    needed = scene_duration_s + DISSOLVE_S + MARGIN_S
    frames = frames_for(needed, fps)
    available = frames / fps
    if available + 1e-9 >= needed:
        return Timing(round(needed, 3), frames, 1.0, False)
    speed = max(1.0 / MAX_SLOWMO, available / needed)
    return Timing(round(needed, 3), frames, round(speed, 4), needed > available / speed + 0.02)


def shot_seed(campaign_id: str | None, shot_id: str, prompt: str) -> int:
    """Deterministic 24-bit seed: the same shot of the same campaign with the same prompt always renders the same clip."""
    return int(hashlib.sha256(f"{campaign_id or ''}|{shot_id}|{prompt}".encode()).hexdigest()[:6], 16)


def seed_base(campaign_id: str | None) -> int:
    return int(hashlib.sha256((campaign_id or "").encode()).hexdigest()[:6], 16)


def prompt_sha256(prompt: str, negative: str = "") -> str:
    return hashlib.sha256(f"{prompt}\n{negative}".encode()).hexdigest()


def shot_prompt_sha(shot: Mapping[str, Any], storyboard: Mapping[str, Any]) -> str:
    """The prompt hash a storyboard shot would be generated with right now (compared with the hash of the clip that was made, to clear ``motion_stale``)."""
    bible = storyboard.get("style_bible_en") or storyboard.get("style_bible")
    return prompt_sha256(build_motion_prompt(dict(shot), bible, shot.get("role"), shot.get("movement")), NEGATIVE_PROMPT)


def cache_key(model: str, revision: str, prompt: str, negative: str, keyframe_sha: str, width: int, height: int, focal: tuple[float, float], seed: int, steps: int, guidance: float, fps: int = wire.FPS) -> str:
    """Library-cache key of a clip: everything that determines its pixels EXCEPT the length, so a longer cached clip satisfies a shorter request."""
    parts = [model, revision, prompt, negative, keyframe_sha, str(width), str(height), f"{focal[0]:.3f}", f"{focal[1]:.3f}", str(seed), str(steps), format(float(guidance), "g"), str(fps)]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


@dataclass(frozen=True)
class ShotPlan:
    scene_id: str
    shot_id: str
    role: str
    asset_id: str  # the approved keyframe (the opening frame of the clip)
    seconds: float  # the scene's duration on the timeline
    needed_s: float
    frames: int
    width: int
    height: int
    seed: int
    prompt: str
    negative: str
    steps: int
    guidance: float
    focal: tuple[float, float]
    speed: float
    hold_tail: bool
    cache_key: str
    est_gpu_seconds: float
    est_cost_usd: float
    fps: int = wire.FPS

    def clip_spec(self, frames: int | None = None) -> ClipSpec:
        """How the compositor plays this clip; ``frames`` is the real length when a longer cached clip is used."""
        return ClipSpec(fps=self.fps, frames=frames or self.frames, offset=0.0, speed=self.speed, hold_tail=self.hold_tail)

    def recipe(self) -> MotionShot:
        return MotionShot(scene_id=self.scene_id, shot_id=self.shot_id, prompt=self.prompt, negative=self.negative, seed=self.seed)


@dataclass
class MotionPlan:
    model: str
    revision: str
    license: str
    steps: int
    guidance: float
    high: bool
    seed_base: int
    price_per_gpu_second: float
    shots: list[ShotPlan] = field(default_factory=list)

    @property
    def est_gpu_seconds(self) -> float:
        return sum(s.est_gpu_seconds for s in self.shots)

    @property
    def est_cost_usd(self) -> float:
        return sum(s.est_cost_usd for s in self.shots)

    def recipe(self, mode: str = "") -> MotionSpec:
        return MotionSpec(mode=mode, model=self.model, revision=self.revision, license=self.license, steps=self.steps, guidance=self.guidance, fps=wire.FPS, high=self.high, seed_base=self.seed_base, shots=[s.recipe() for s in self.shots])


def wall_seconds(uncached: list[ShotPlan], cold_start_s: float = 0.0) -> float:
    """Expected duration of a cinematic render: cold start (when the GPU worker is asleep) + generation + the compositor pass."""
    return round(cold_start_s + sum(s.est_gpu_seconds + GENERATE_OVERHEAD_S for s in uncached) + COMPOSITE_S, 1)


def plan_motion(
    spec: RenderSpec,
    storyboard: Mapping[str, Any] | None,
    settings: Any,
    *,
    model: str,
    revision: str,
    license_name: str = "",
    keyframe_sha: Mapping[str, str] | None = None,
    campaign_id: str | None = None,
) -> MotionPlan:
    """The motion plan of ``spec``: one entry per scene that has a keyframe.

    A recipe already stored on the spec (``spec.motion``: a re-render, a reframed format, a localized version) wins over the storyboard, so the same
    spot always asks for the same clips. Otherwise the prompt is built from the storyboard shot (older storyboards without motion text still work)."""
    recipe = spec.motion
    recipes = {s.scene_id: s for s in recipe.shots} if recipe else {}
    steps = recipe.steps if recipe else int(settings.motion_steps)
    guidance = recipe.guidance if recipe else float(settings.motion_guidance)
    high = recipe.high if recipe else bool(settings.motion_high)
    cid = campaign_id or spec.campaign_id
    shots_by_id = {s["id"]: s for s in (storyboard or {}).get("shots", [])}
    bible = (storyboard or {}).get("style_bible_en") or (storyboard or {}).get("style_bible")
    width, height = resolution_for(spec.aspect, high)
    price = float(settings.motion_price_per_gpu_second)
    plan = MotionPlan(model=model, revision=revision, license=license_name, steps=steps, guidance=guidance, high=high, seed_base=seed_base(cid), price_per_gpu_second=price)
    for sc in spec.scenes:
        if not sc.asset_id:
            continue
        shot = shots_by_id.get(sc.shot_id or "", {})
        shot_id = sc.shot_id or sc.id
        known = recipes.get(sc.id)
        prompt = known.prompt if known else build_motion_prompt(shot, bible, sc.role, sc.motion)
        negative = (known.negative if known else "") or NEGATIVE_PROMPT
        seed = known.seed if known else shot_seed(cid, shot_id, prompt)
        timing = timing_for(sc.duration)
        est = pricing.motion_estimate(timing.frames, width, height, steps)
        key = cache_key(model, revision, prompt, negative, (keyframe_sha or {}).get(sc.asset_id, ""), width, height, (float(sc.focal[0]), float(sc.focal[1])), seed, steps, guidance)
        plan.shots.append(
            ShotPlan(
                scene_id=sc.id, shot_id=shot_id, role=sc.role, asset_id=sc.asset_id, seconds=sc.duration, needed_s=timing.needed_s, frames=timing.frames, width=width, height=height, seed=seed,
                prompt=prompt, negative=negative, steps=steps, guidance=guidance, focal=(float(sc.focal[0]), float(sc.focal[1])), speed=timing.speed, hold_tail=timing.hold_tail, cache_key=key,
                est_gpu_seconds=round(est, 2), est_cost_usd=round(pricing.motion_cost(est, price), 5),
            )
        )
    return plan
