"""Wire contract v1 between Studio and the GPU motion worker (queue + blobs, no ingress).

    motion-in/<job_id>/request.json + image.(jpg|png)     <- Studio writes, then enqueues {"v":1,"type":"generate","job_id":…}
    motion-out/<job_id>/status.json                       <- worker, rewritten every <= 3 s while running
    motion-out/<job_id>/result.json + clip.mp4            <- worker, written last (its presence means the job is over)
    motion-out/_worker/ready.json                         <- worker, every 60 s while alive

The authoritative schema lives in ``contracts/motion-v1.schema.json``; this module is Studio's side of it (job-id canonicalisation, JSON
builders / readers, constants). The deterministic job id makes the transport itself idempotent: the same inputs always map to the same prefix.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

WIRE_VERSION = 1
MODEL_ID = "wan2.2-ti2v-5b"
MODEL_REPO = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
MODEL_REVISION = "b8fff7315c768468a5333511427288870b2e9635"
MODEL_LICENSE = "Apache-2.0"
MODEL_LICENSES = {MODEL_ID: MODEL_LICENSE}
HOST_AZURE = "self-hosted · Azure Container Apps serverless GPU (tenant-local)"

FPS = 24
MIN_FRAMES, MAX_FRAMES = 25, 121  # 4n + 1
MIN_STEPS, MAX_STEPS = 8, 40
MIN_GUIDANCE, MAX_GUIDANCE = 1.0, 8.0

WORKER_READY_MAX_AGE_S = 150  # a ready.json older than this means the worker is gone (it rewrites it every 60 s)
REQUEUE_AFTER_S = 1200  # still queued after 20 minutes with no worker: the message is sent again

QUEUE_DIR = "queue"
IN_PREFIX = "motion-in"
OUT_PREFIX = "motion-out"
WORKER_READY_BLOB = "_worker/ready.json"

STATES = ("queued", "running", "succeeded", "failed")
TERMINAL = ("succeeded", "failed")


def canonical_text(value: str) -> str:
    """The two free-text fields are escaped so a ``|`` inside a prompt can never shift a field boundary: ``\\`` -> ``\\\\``, ``|`` -> ``\\|``."""
    return value.replace("\\", "\\\\").replace("|", "\\|")


def canonical_guidance(value: float) -> str:
    return format(float(value), ".6g")


def canonical_job_string(
    model: str, revision: str, prompt: str, negative: str, width: int, height: int, num_frames: int, fps: int, steps: int, guidance: float, seed: int, image_sha256: str
) -> str:
    """``model|revision|esc(prompt)|esc(negative)|width|height|num_frames|fps|steps|guidance(.6g)|seed|image_sha256`` (contracts/job-id-vectors.json)."""
    return "|".join([model, revision, canonical_text(prompt), canonical_text(negative), str(int(width)), str(int(height)), str(int(num_frames)), str(int(fps)), str(int(steps)), canonical_guidance(guidance), str(int(seed)), image_sha256.lower()])


def compute_job_id(
    model: str, revision: str, prompt: str, negative: str, width: int, height: int, num_frames: int, fps: int, steps: int, guidance: float, seed: int, image_sha256: str
) -> str:
    """``"mj_" + sha256(utf8(canonical))[:24]``: the same inputs always map to the same job (idempotent transport, free cache). Golden vectors: ``contracts/job-id-vectors.json``."""
    return "mj_" + hashlib.sha256(canonical_job_string(model, revision, prompt, negative, width, height, num_frames, fps, steps, guidance, seed, image_sha256).encode("utf-8")).hexdigest()[:24]


def utc_iso(when: datetime | None = None) -> str:
    return (when or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def queue_message(kind: str, job_id: str) -> dict[str, Any]:
    return {"v": WIRE_VERSION, "type": kind, "job_id": job_id}


def encode(doc: dict[str, Any]) -> bytes:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def decode(data: bytes | str) -> dict[str, Any]:
    doc = json.loads(data)
    if not isinstance(doc, dict):
        raise ValueError("motion JSON must be an object")
    return doc


def image_name(mime: str) -> str:
    return "image.png" if mime == "image/png" else "image.jpg"


@dataclass
class WorkerReady:
    """``motion-out/_worker/ready.json`` as Studio reads it."""

    state: str = "cold"
    age_s: int | None = None
    model: str = ""
    revision: str = ""
    replica: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_doc(cls, doc: dict[str, Any] | None, now: datetime | None = None) -> WorkerReady:
        """``ready`` / ``loading`` while the heartbeat is fresh, else ``cold`` (the worker is gone or has never started)."""
        if not doc:
            return cls()
        updated = parse_utc(doc.get("updated_at"))
        age = max(0, int(((now or datetime.now(UTC)) - updated).total_seconds())) if updated else None
        fresh = age is not None and age < WORKER_READY_MAX_AGE_S
        state = str(doc.get("state") or "cold") if fresh else "cold"
        return cls(state=state if state in {"ready", "loading"} else "cold", age_s=age, model=str(doc.get("model") or ""), revision=str(doc.get("model_revision") or ""), replica=str(doc.get("replica") or ""), raw=doc)
