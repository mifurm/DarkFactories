"""Wire contract v1 (``contracts/motion-v1.schema.json``): job ids, request validation, document builders.

Pure Python, no third-party imports. The Studio re-implements ``compute_job_id`` (see contracts/README.md,
which carries golden vectors that the tests of both sides must reproduce).
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .errors import BadRequest

CONTRACT_VERSION = 1

GENERATE = "generate"
WARMUP = "warmup"

# Always used with .fullmatch(): Python's "$" would also accept a trailing newline.
JOB_ID_RE = re.compile(r"mj_[0-9a-f]{24}")
WARMUP_ID_RE = re.compile(r"mw_[0-9a-f]{8}(?:-?[0-9a-f]{4}){3}-?[0-9a-f]{12}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
MODEL_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
REVISION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
IMAGE_NAME_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,100}\.(?:jpg|jpeg|png|webp)")

# Limits (README "Request rules"). Frames are 4n+1; sizes are multiples of 32 (Wan 2.2 TI2V VAE 16 x patch 2).
FPS = 24
MIN_FRAMES, MAX_FRAMES = 25, 121
MIN_STEPS, MAX_STEPS = 8, 40
MIN_GUIDANCE, MAX_GUIDANCE = 1.0, 8.0
MIN_DIM, MAX_DIM = 256, 1280
MAX_PIXELS = 1280 * 704
MAX_SEED = 2**32 - 1
MAX_PROMPT_CHARS = 4000
MAX_LABEL_CHARS = 128
MAX_REQUEST_BYTES = 256 * 1024


@dataclass(frozen=True)
class ModelSpec:
    repo: str
    revision: str


# Pinned default revision per served model id. A request that omits ``model_revision`` is treated as if it
# carried this value (for the job-id check and in the README's canonicalisation).
MODELS: dict[str, ModelSpec] = {
    "wan2.2-ti2v-5b": ModelSpec(
        repo="Wan-AI/Wan2.2-TI2V-5B-Diffusers",
        revision="b8fff7315c768468a5333511427288870b2e9635",
    ),
}
DEFAULT_MODEL_ID = "wan2.2-ti2v-5b"


# --------------------------------------------------------------------------------------------------
# Deterministic job id
# --------------------------------------------------------------------------------------------------


def canonical_text(value: str) -> str:
    """Escape the two free-text fields so '|' can never shift a field boundary: ``\\`` -> ``\\\\``, ``|`` -> ``\\|``."""
    return value.replace("\\", "\\\\").replace("|", "\\|")


def canonical_guidance(value: float) -> str:
    return format(float(value), ".6g")


def compute_job_id(
    *,
    model: str,
    revision: str,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    num_frames: int,
    fps: int,
    steps: int,
    guidance_scale: float,
    seed: int,
    image_sha256: str,
) -> str:
    """``"mj_" + sha256(canonical)[:24]`` where canonical is the '|'-joined field list below, UTF-8 encoded."""
    canonical = "|".join(
        (
            model,
            revision,
            canonical_text(prompt),
            canonical_text(negative_prompt),
            str(int(width)),
            str(int(height)),
            str(int(num_frames)),
            str(int(fps)),
            str(int(steps)),
            canonical_guidance(guidance_scale),
            str(int(seed)),
            image_sha256.lower(),
        )
    )
    return "mj_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def new_warmup_id() -> str:
    return "mw_" + uuid.uuid4().hex


# --------------------------------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------------------------------


def utc_now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp (naive values are taken as UTC); None when unparseable."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# --------------------------------------------------------------------------------------------------
# Queue message
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class QueueJob:
    type: str
    job_id: str


def parse_queue_message(body: str | bytes) -> QueueJob:
    """Parse the message text (plain JSON; base64-wrapped JSON is tolerated). Raises BadRequest."""
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    doc: Any = None
    try:
        doc = json.loads(text)
    except ValueError:
        try:
            # binascii.Error and UnicodeDecodeError are ValueErrors too
            doc = json.loads(base64.b64decode(text, validate=True).decode("utf-8"))
        except ValueError:
            raise BadRequest("queue message is not valid JSON") from None
    if not isinstance(doc, dict):
        raise BadRequest("queue message must be a JSON object")
    if doc.get("v") != CONTRACT_VERSION:
        raise BadRequest(f"unsupported contract version: {doc.get('v')!r}")
    kind, job_id = doc.get("type"), doc.get("job_id")
    if kind == GENERATE and isinstance(job_id, str) and JOB_ID_RE.fullmatch(job_id):
        return QueueJob(GENERATE, job_id)
    if kind == WARMUP and isinstance(job_id, str) and WARMUP_ID_RE.fullmatch(job_id):
        return QueueJob(WARMUP, job_id)
    raise BadRequest(f"invalid queue message type/job_id: {kind!r}/{job_id!r}")


def build_queue_message(job_id: str) -> str:
    kind = WARMUP if job_id.startswith("mw_") else GENERATE
    return json.dumps({"v": CONTRACT_VERSION, "type": kind, "job_id": job_id}, separators=(",", ":"))


# --------------------------------------------------------------------------------------------------
# Request
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MotionRequest:
    job_id: str
    model: str
    prompt: str
    negative_prompt: str
    width: int
    height: int
    num_frames: int
    fps: int
    steps: int
    guidance_scale: float
    seed: int
    image: str
    model_revision: str | None = None
    image_sha256: str | None = None
    campaign_id: str | None = None
    shot_id: str | None = None
    created_at: str | None = None

    def expected_job_id(self, *, image_sha256: str, default_revision: str) -> str:
        return compute_job_id(
            model=self.model,
            revision=self.model_revision or default_revision,
            prompt=self.prompt,
            negative_prompt=self.negative_prompt,
            width=self.width,
            height=self.height,
            num_frames=self.num_frames,
            fps=self.fps,
            steps=self.steps,
            guidance_scale=self.guidance_scale,
            seed=self.seed,
            image_sha256=image_sha256,
        )


def _int_field(doc: Mapping[str, Any], key: str, lo: int, hi: int) -> int:
    value = doc.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BadRequest(f"{key} must be an integer")
    if isinstance(value, float):
        if not value.is_integer():
            raise BadRequest(f"{key} must be an integer")
        value = int(value)
    if not lo <= value <= hi:
        raise BadRequest(f"{key} must be between {lo} and {hi} (got {value})")
    return value


def _text_field(doc: Mapping[str, Any], key: str, *, required: bool, max_len: int) -> str | None:
    value = doc.get(key)
    if value is None:
        if required:
            raise BadRequest(f"{key} is required")
        return None
    if not isinstance(value, str):
        raise BadRequest(f"{key} must be a string")
    if len(value) > max_len:
        raise BadRequest(f"{key} is too long ({len(value)} > {max_len} characters)")
    return value


def parse_request(doc: Any) -> MotionRequest:
    """Validate ``motion-in/<job_id>/request.json`` (contract rules). Raises BadRequest with the first problem."""
    if not isinstance(doc, dict):
        raise BadRequest("request.json must be a JSON object")
    if doc.get("v") != CONTRACT_VERSION:
        raise BadRequest(f"unsupported contract version: {doc.get('v')!r}")
    job_id = doc.get("job_id")
    if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
        raise BadRequest("job_id must match mj_<24 hex>")
    model = _text_field(doc, "model", required=True, max_len=64)
    if not model or not MODEL_RE.fullmatch(model):
        raise BadRequest("model must be a lowercase model id such as wan2.2-ti2v-5b")
    prompt = _text_field(doc, "prompt", required=True, max_len=MAX_PROMPT_CHARS)
    if not prompt or not prompt.strip():
        raise BadRequest("prompt must not be empty")
    negative = _text_field(doc, "negative_prompt", required=False, max_len=MAX_PROMPT_CHARS) or ""

    width = _int_field(doc, "width", MIN_DIM, MAX_DIM)
    height = _int_field(doc, "height", MIN_DIM, MAX_DIM)
    if width % 32 or height % 32:
        raise BadRequest(f"width and height must be multiples of 32 (got {width}x{height})")
    if width * height > MAX_PIXELS:
        raise BadRequest(f"{width}x{height} exceeds the {MAX_PIXELS}-pixel budget (1280x704)")
    num_frames = _int_field(doc, "num_frames", MIN_FRAMES, MAX_FRAMES)
    if (num_frames - 1) % 4:
        raise BadRequest(f"num_frames must be 4n+1 (got {num_frames})")
    fps = _int_field(doc, "fps", FPS, FPS)
    steps = _int_field(doc, "steps", MIN_STEPS, MAX_STEPS)
    seed = _int_field(doc, "seed", 0, MAX_SEED)

    guidance = doc.get("guidance_scale")
    if isinstance(guidance, bool) or not isinstance(guidance, int | float) or not math.isfinite(guidance):
        raise BadRequest("guidance_scale must be a number")
    if not MIN_GUIDANCE <= guidance <= MAX_GUIDANCE:
        raise BadRequest(f"guidance_scale must be between {MIN_GUIDANCE:g} and {MAX_GUIDANCE:g} (got {guidance})")

    image = doc.get("image")
    if not isinstance(image, str) or not IMAGE_NAME_RE.fullmatch(image):
        raise BadRequest("image must be a plain blob name inside the job prefix (jpg/jpeg/png/webp)")

    revision = _text_field(doc, "model_revision", required=False, max_len=64)
    if revision is not None and not REVISION_RE.fullmatch(revision):
        raise BadRequest("model_revision has an invalid format")
    sha = _text_field(doc, "image_sha256", required=False, max_len=64)
    if sha is not None and not SHA256_RE.fullmatch(sha):
        raise BadRequest("image_sha256 must be 64 lowercase hex characters")
    created_at = _text_field(doc, "created_at", required=False, max_len=40)
    if created_at is not None and parse_iso(created_at) is None:
        raise BadRequest("created_at must be an ISO-8601 timestamp")

    return MotionRequest(
        job_id=job_id,
        model=model,
        prompt=prompt,
        negative_prompt=negative,
        width=width,
        height=height,
        num_frames=num_frames,
        fps=fps,
        steps=steps,
        guidance_scale=float(guidance),
        seed=seed,
        image=image,
        model_revision=revision,
        image_sha256=sha,
        campaign_id=_text_field(doc, "campaign_id", required=False, max_len=MAX_LABEL_CHARS),
        shot_id=_text_field(doc, "shot_id", required=False, max_len=MAX_LABEL_CHARS),
        created_at=created_at,
    )


def build_request(
    *,
    prompt: str,
    image_name: str,
    image_bytes: bytes,
    width: int,
    height: int,
    num_frames: int,
    seed: int,
    negative_prompt: str = "",
    steps: int = 20,
    guidance_scale: float = 4.0,
    fps: int = FPS,
    model: str = DEFAULT_MODEL_ID,
    revision: str | None = None,
    campaign_id: str | None = None,
    shot_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Producer-side reference: the request.json a client (Studio, tools/tests) writes for an image."""
    revision = revision or MODELS[model].revision
    sha = hashlib.sha256(image_bytes).hexdigest()
    job_id = compute_job_id(
        model=model,
        revision=revision,
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        num_frames=num_frames,
        fps=fps,
        steps=steps,
        guidance_scale=guidance_scale,
        seed=seed,
        image_sha256=sha,
    )
    doc: dict[str, Any] = {
        "v": CONTRACT_VERSION,
        "job_id": job_id,
        "model": model,
        "model_revision": revision,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "fps": fps,
        "steps": steps,
        "guidance_scale": guidance_scale,
        "seed": seed,
        "image": image_name,
        "image_sha256": sha,
        "created_at": utc_now_iso(now),
    }
    if campaign_id is not None:
        doc["campaign_id"] = campaign_id
    if shot_id is not None:
        doc["shot_id"] = shot_id
    return doc


# --------------------------------------------------------------------------------------------------
# Documents written by the worker (key order follows the spec examples)
# --------------------------------------------------------------------------------------------------


def build_status(
    *,
    job_id: str,
    state: str,
    progress: float,
    step: int,
    steps: int,
    message: str,
    replica: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    return {
        "v": CONTRACT_VERSION,
        "job_id": job_id,
        "state": state,
        "progress": round(min(1.0, max(0.0, progress)), 3),
        "step": int(step),
        "steps": int(steps),
        "message": message,
        "replica": replica,
        "updated_at": utc_now_iso(now),
    }


def build_result(
    *,
    job_id: str,
    request: MotionRequest | None,
    model: str,
    model_revision: str,
    gpu_seconds: float,
    queue_wait_s: float,
    generate_s: float,
    encode_s: float,
    clip: str | None = None,
    width: int | None = None,
    height: int | None = None,
    num_frames: int | None = None,
    error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """result.json. ``error`` set => state failed (clip null); otherwise succeeded."""
    failed = error is not None
    return {
        "v": CONTRACT_VERSION,
        "job_id": job_id,
        "state": "failed" if failed else "succeeded",
        "clip": None if failed else clip,
        "width": width if width is not None else (request.width if request else None),
        "height": height if height is not None else (request.height if request else None),
        "fps": request.fps if request else None,
        "num_frames": num_frames if num_frames is not None else (request.num_frames if request else None),
        "seed": request.seed if request else None,
        "model": model,
        "model_revision": model_revision,
        "gpu_seconds": round(max(0.0, gpu_seconds), 1),
        "timings": {
            "queue_wait_s": round(max(0.0, queue_wait_s), 1),
            "generate_s": round(max(0.0, generate_s), 1),
            "encode_s": round(max(0.0, encode_s), 1),
        },
        "error": dict(error) if failed and error is not None else None,
    }


def build_ready(
    *,
    state: str,
    replica: str,
    model: str,
    model_revision: str,
    vram_gib: float,
    started_at: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    return {
        "v": CONTRACT_VERSION,
        "state": state,
        "replica": replica,
        "model": model,
        "model_revision": model_revision,
        "vram_gib": round(vram_gib, 1),
        "started_at": started_at,
        "updated_at": utc_now_iso(now),
    }
