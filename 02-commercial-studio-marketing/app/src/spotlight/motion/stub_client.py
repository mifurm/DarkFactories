"""StubMotionClient: the offline motion backend (default when Studio runs without Azure).

No model, no GPU: a deterministic procedural animator (see ``animator.py``) turns the opening frame into a clip that really moves, so the whole
cinematic path (plan, cache, budget, safety check, compositor clip scenes, provenance) runs and is testable end to end. Costs are SIMULATED with the same
calibrated GPU-seconds estimate as the real worker, exactly like the other offline stubs (the usage meter marks them simulated).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ..core.ai import pricing
from . import animator, wire
from .models import MotionProgress, MotionRequest, MotionResult, ProgressCb, WorkerStatus

STUB_MODEL = "spotlight-stub-animator"
STUB_LICENSE = "n/a (offline simulator, no generative model)"
STUB_HOST = "offline procedural simulator (no model, no GPU)"


class StubMotionClient:
    name = "stub"
    model = STUB_MODEL
    revision = "1"
    license = STUB_LICENSE
    host = STUB_HOST

    def __init__(self, settings: Any = None) -> None:
        self.settings = settings
        self.calls = 0

    def capabilities(self) -> dict[str, Any]:
        return {"kind": "image-to-video (procedural stub)", "generative": False, "min_frames": wire.MIN_FRAMES, "max_frames": wire.MAX_FRAMES, "fps": wire.FPS}

    async def status(self) -> WorkerStatus:
        return WorkerStatus(state="ready", age_s=0, queue_depth=0)

    async def warmup(self) -> WorkerStatus:
        return await self.status()

    async def generate(self, req: MotionRequest, on_progress: ProgressCb | None = None, timeout_s: float = 1500.0) -> MotionResult:
        req.validate()
        if on_progress:
            await on_progress(MotionProgress(state="running", progress=0.02, step=0, steps=req.steps, message="animating", worker_state="ready"))
        t0 = time.monotonic()
        clip = await asyncio.wait_for(asyncio.to_thread(animator.animate, req.image, req.width, req.height, req.num_frames, req.fps, req.seed), timeout_s)
        took = time.monotonic() - t0
        self.calls += 1
        if on_progress:
            await on_progress(MotionProgress(state="running", progress=1.0, step=req.steps, steps=req.steps, message="encoded", worker_state="ready"))
        gpu = round(pricing.motion_estimate(req.num_frames, req.width, req.height, req.steps), 2)  # simulated: what the A100 would have spent
        return MotionResult(
            clip=clip, job_id=req.job_id, model=self.model, revision=self.revision, width=req.width, height=req.height, fps=req.fps, num_frames=req.num_frames, seed=req.seed,
            gpu_seconds=gpu, timings={"queue_wait_s": 0.0, "generate_s": round(took, 2), "encode_s": 0.0}, cached=False, provider=self.name,
        )

    async def close(self) -> None:
        return None
