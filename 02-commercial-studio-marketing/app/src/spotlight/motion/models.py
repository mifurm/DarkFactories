"""Data model of the cinematic-motion layer: requests, results, progress and the errors a motion backend can raise."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..errors import ProviderUnavailable
from . import wire

NEGATIVE_PROMPT = (
    "text, watermark, logo, subtitles, captions, letters, low quality, blurry, jittery, flickering, distorted hands, extra fingers, deformed, "
    "morphing or warping packaging, cartoon, static image, overexposed, split screen, collage"
)

# Why a shot played its still instead of an AI clip (``render.motion.shots_fallback[].reason``); every code has a ``motion.reason.<code>`` catalog entry.
FALLBACK_REASONS = ("oom", "timeout", "safety", "budget", "worker_unavailable", "bad_request", "internal", "disabled")


class MotionError(ProviderUnavailable):
    """Base of the motion backend errors. ``reason`` is the stable code stored on a shot that fell back to the still-image path."""

    code = "motion_failed"
    reason = "internal"


class MotionUnavailable(MotionError):
    code = "motion_unavailable"
    reason = "worker_unavailable"


class MotionDisabled(MotionUnavailable):
    """Cinematic motion is not configured in this deployment (``MOTION_MODE=off``)."""

    reason = "disabled"


class MotionTimeout(MotionError):
    code = "motion_timeout"
    reason = "timeout"


class MotionTransportError(MotionError):
    code = "motion_transport"
    reason = "worker_unavailable"


class MotionBadRequest(MotionError):
    status = 422
    code = "motion_bad_request"
    reason = "bad_request"


class MotionFailed(MotionError):
    """The worker finished the job with ``state=failed`` (``oom`` | ``bad_request`` | ``timeout`` | ``internal``). ``gpu_seconds`` is what the failed attempt still cost."""

    code = "motion_failed"

    def __init__(self, message: str, *, worker_code: str = "internal", retryable: bool = False, gpu_seconds: float = 0.0, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.worker_code = worker_code
        self.retryable = retryable
        self.gpu_seconds = gpu_seconds
        self.reason = worker_code if worker_code in {"oom", "bad_request", "timeout"} else "internal"


@dataclass(frozen=True)
class MotionRequest:
    """One image-to-video job: the (already cropped) opening frame, the prompt and every parameter that determines the output."""

    prompt: str
    image: bytes
    width: int
    height: int
    num_frames: int
    seed: int
    negative_prompt: str = NEGATIVE_PROMPT
    fps: int = wire.FPS
    steps: int = 20
    guidance_scale: float = 4.0
    model: str = wire.MODEL_ID
    revision: str = wire.MODEL_REVISION
    image_mime: str = "image/jpeg"
    campaign_id: str | None = None
    shot_id: str | None = None

    @property
    def image_sha256(self) -> str:
        return hashlib.sha256(self.image).hexdigest()

    @property
    def job_id(self) -> str:
        return wire.compute_job_id(self.model, self.revision, self.prompt, self.negative_prompt, self.width, self.height, self.num_frames, self.fps, self.steps, self.guidance_scale, self.seed, self.image_sha256)

    def validate(self) -> None:
        """The worker's input rules (wire contract v1, contracts/motion-v1.schema.json); a violation is a bug in the caller, caught before anything is queued."""
        problems = []
        if self.width % 32 or self.height % 32 or not (256 <= self.width <= 1280 and 256 <= self.height <= 1280) or self.width * self.height > 1280 * 704:
            problems.append(f"size {self.width}x{self.height} must be multiples of 32, 256..1280 per side and at most 1280x704 pixels")
        if self.num_frames % 4 != 1 or not (wire.MIN_FRAMES <= self.num_frames <= wire.MAX_FRAMES):
            problems.append(f"num_frames {self.num_frames} must be 4n+1 within {wire.MIN_FRAMES}..{wire.MAX_FRAMES}")
        if self.fps != wire.FPS:
            problems.append(f"fps must be {wire.FPS}")
        if not (wire.MIN_STEPS <= self.steps <= wire.MAX_STEPS):
            problems.append(f"steps {self.steps} must be within {wire.MIN_STEPS}..{wire.MAX_STEPS}")
        if not (wire.MIN_GUIDANCE <= self.guidance_scale <= wire.MAX_GUIDANCE):
            problems.append(f"guidance {self.guidance_scale} must be within {wire.MIN_GUIDANCE}..{wire.MAX_GUIDANCE}")
        if not (0 <= self.seed <= 2**32 - 1):
            problems.append("seed must be within 0..4294967295")
        if not self.image:
            problems.append("image is empty")
        if not self.prompt.strip() or len(self.prompt) > 4000 or len(self.negative_prompt) > 4000:
            problems.append("prompt must be 1..4000 characters (negative prompt at most 4000)")
        if problems:
            raise MotionBadRequest("invalid motion request: " + "; ".join(problems), params={"detail": "; ".join(problems)})

    def to_wire(self, created_at: str | None = None) -> dict[str, Any]:
        """``motion-in/<job_id>/request.json`` (``model_revision`` + ``image_sha256`` let the worker verify the job id and the uploaded bytes)."""
        doc = {
            "v": wire.WIRE_VERSION,
            "job_id": self.job_id,
            "model": self.model,
            "model_revision": self.revision,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "width": self.width,
            "height": self.height,
            "num_frames": self.num_frames,
            "fps": self.fps,
            "steps": self.steps,
            "guidance_scale": self.guidance_scale,
            "seed": self.seed,
            "image": wire.image_name(self.image_mime),
            "image_sha256": self.image_sha256,
            "campaign_id": self.campaign_id,
            "shot_id": self.shot_id,
            "created_at": created_at or wire.utc_iso(),
        }
        return {k: v for k, v in doc.items() if v is not None}  # optional labels that are not set are left out (the schema has no nulls there)


@dataclass
class MotionResult:
    clip: bytes
    job_id: str
    model: str
    revision: str
    width: int
    height: int
    fps: int
    num_frames: int
    seed: int
    gpu_seconds: float
    timings: dict[str, float] = field(default_factory=dict)
    cached: bool = False  # the clip already existed (transport-level cache): this call used no GPU time
    provider: str = ""


@dataclass
class MotionProgress:
    """What a backend reports while a job is queued / running (relayed to the Studio job as a progress message)."""

    state: str = "queued"  # queued | running
    progress: float = 0.0
    step: int | None = None
    steps: int | None = None
    message: str = ""
    waited_s: float = 0.0
    worker_state: str | None = None  # cold | warming | ready, when the backend knows


ProgressCb = Callable[[MotionProgress], Awaitable[None]]


@dataclass
class WorkerStatus:
    state: str = "cold"  # cold | warming | ready
    age_s: int | None = None
    queue_depth: int = 0
    error: str | None = None
    requested: bool = False  # warmup() only: this very call queued a wake-up message (the GPU will start billing)
