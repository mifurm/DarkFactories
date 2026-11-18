"""QueueMotionClient: Studio's side of the queue + blob protocol (wire contract v1), independent of where the bytes live.

The transport (Azure Queue + Blob Storage with Entra, or a local directory) only moves bytes; the protocol — idempotent job ids, polling, progress
relay, retry of a retryable failure, re-queueing a message that nobody picked up, timeouts — lives here, once, and is tested against both.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any, Protocol

from . import wire
from .models import (
    MotionBadRequest,
    MotionError,
    MotionFailed,
    MotionProgress,
    MotionRequest,
    MotionResult,
    MotionTimeout,
    MotionTransportError,
    ProgressCb,
    WorkerStatus,
)

log = logging.getLogger("spotlight.motion")

WARMUP_COOLDOWN_S = 90.0  # a second warm-up message is not sent while the first is still being served
STATUS_TTL_S = 2.0
MAX_POLL_ERRORS = 6  # consecutive storage errors tolerated while waiting for a job (a network blip is not a failure)


class MotionTransport(Protocol):
    """Bytes in / bytes out. ``get_output`` returns None when the blob does not exist; every other failure raises."""

    name: str

    async def put_input(self, job_id: str, name: str, data: bytes, content_type: str) -> None: ...
    async def get_output(self, job_id: str, name: str) -> bytes | None: ...
    async def delete_output(self, job_id: str, name: str) -> None: ...
    async def enqueue(self, message: dict[str, Any]) -> None: ...
    async def queue_depth(self) -> int: ...
    async def close(self) -> None: ...


class QueueMotionClient:
    def __init__(
        self,
        transport: MotionTransport,
        *,
        name: str,
        model: str,
        revision: str,
        license: str,
        host: str,
        poll_s: float = 3.0,
        requeue_after_s: float = wire.REQUEUE_AFTER_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.transport = transport
        self.name = name
        self.model = model
        self.revision = revision
        self.license = license
        self.host = host
        self.poll_s = poll_s
        self.requeue_after_s = requeue_after_s
        self._clock = clock
        self._status_cache: tuple[float, WorkerStatus] | None = None
        self._last_warmup = -1e9

    def capabilities(self) -> dict[str, Any]:
        return {"kind": "image-to-video", "transport": self.transport.name, "model": self.model, "min_frames": wire.MIN_FRAMES, "max_frames": wire.MAX_FRAMES, "fps": wire.FPS, "generative": True}

    # ------------------------------------------------------------------------------------------------ reading the worker

    async def _json(self, job_id: str, name: str) -> dict[str, Any] | None:
        data = await self.transport.get_output(job_id, name)
        if data is None:
            return None
        try:
            return wire.decode(data)
        except ValueError:
            log.warning("motion: unreadable %s/%s (a partial write?) — treated as absent", job_id, name)
            return None

    async def status(self) -> WorkerStatus:
        """cold | warming | ready: ``ready`` while the worker's heartbeat is fresh, ``warming`` while it loads or a message waits for it, else ``cold``."""
        now = self._clock()
        if self._status_cache and now - self._status_cache[0] < STATUS_TTL_S:
            return self._status_cache[1]
        try:
            ready = wire.WorkerReady.from_doc(await self._json("_worker", "ready.json"))
            depth = await self.transport.queue_depth()
        except Exception as exc:
            return WorkerStatus(state="cold", age_s=None, queue_depth=0, error=f"{type(exc).__name__}: {str(exc)[:160]}")
        state = "ready" if ready.state == "ready" else "warming" if (ready.state == "loading" or depth > 0) else "cold"
        out = WorkerStatus(state=state, age_s=ready.age_s, queue_depth=depth)
        self._status_cache = (now, out)
        return out

    async def warmup(self) -> WorkerStatus:
        """Wake the worker without a job (a ``warmup`` message). A no-op while it is ready / already warming, so it is safe to call repeatedly."""
        self._status_cache = None
        current = await self.status()
        if current.error or current.state != "cold" or self._clock() - self._last_warmup < WARMUP_COOLDOWN_S:
            return current
        try:
            await self.transport.enqueue(wire.queue_message("warmup", f"mw_{uuid.uuid4().hex}"))
        except Exception as exc:
            raise MotionTransportError(f"the motion queue is unreachable: {exc}", params={"detail": f"{type(exc).__name__}: {str(exc)[:160]}"}) from exc
        self._last_warmup = self._clock()
        self._status_cache = None
        return WorkerStatus(state="warming", age_s=current.age_s, queue_depth=current.queue_depth + 1, requested=True)

    # ------------------------------------------------------------------------------------------------ one clip

    async def generate(self, req: MotionRequest, on_progress: ProgressCb | None = None, timeout_s: float = 1500.0) -> MotionResult:
        req.validate()
        job_id = req.job_id
        started = self._clock()
        try:
            existing = await self._json(job_id, "result.json")
            if existing is not None:
                if existing.get("state") == "succeeded":
                    return await self._finish(req, existing, cached=True)
                if not (existing.get("error") or {}).get("retryable"):
                    raise self._failed(existing)
                await self._clear(job_id)  # a retryable failure of an earlier attempt: run it again
            await self.transport.put_input(job_id, "request.json", wire.encode(req.to_wire()), "application/json")
            await self.transport.put_input(job_id, wire.image_name(req.image_mime), req.image, req.image_mime)
            await self.transport.enqueue(wire.queue_message("generate", job_id))
        except MotionError:
            raise
        except Exception as exc:
            raise MotionTransportError(f"the motion queue is unreachable: {exc}", params={"detail": f"{type(exc).__name__}: {str(exc)[:160]}"}) from exc
        last_enqueue = self._clock()
        errors = 0
        worker_state: str | None = None
        worker_checked = -1e9
        while True:
            await asyncio.sleep(self.poll_s)
            now = self._clock()
            elapsed = now - started
            try:
                result = await self._json(job_id, "result.json")
                if result is not None:
                    if result.get("state") == "succeeded":
                        return await self._finish(req, result, cached=False)
                    raise self._failed(result, counted=True)
                status = await self._json(job_id, "status.json") or {}
                state = str(status.get("state") or "queued")
                if state == "queued" and now - worker_checked >= 3 * self.poll_s:
                    worker_checked = now
                    worker_state = (await self.status()).state
                    if worker_state == "cold" and now - last_enqueue >= self.requeue_after_s:  # nobody picked the message up: send it again
                        await self.transport.enqueue(wire.queue_message("generate", job_id))
                        last_enqueue = now
                errors = 0
            except MotionError:
                raise
            except Exception as exc:
                errors += 1
                if errors > MAX_POLL_ERRORS:
                    raise MotionTransportError(f"the motion storage stopped answering: {exc}", params={"detail": f"{type(exc).__name__}: {str(exc)[:160]}"}) from exc
                log.warning("motion: poll error %d/%d for %s: %s", errors, MAX_POLL_ERRORS, job_id, exc)
                continue
            if on_progress:
                await on_progress(
                    MotionProgress(
                        state="running" if state == "running" else "queued", progress=float(status.get("progress") or 0.0), step=status.get("step"), steps=status.get("steps"),
                        message=str(status.get("message") or ""), waited_s=elapsed, worker_state=worker_state if state == "queued" else "ready",
                    )
                )
            if elapsed >= timeout_s:
                raise MotionTimeout(f"the motion worker did not finish within {int(timeout_s)} s", params={"seconds": int(timeout_s)})

    async def _finish(self, req: MotionRequest, result: dict[str, Any], *, cached: bool) -> MotionResult:
        job_id = req.job_id
        clip = await self.transport.get_output(job_id, str(result.get("clip") or "clip.mp4"))
        if not clip:
            raise MotionTransportError("the motion result has no clip", params={"detail": "clip.mp4 missing next to result.json"})
        return MotionResult(
            clip=clip, job_id=job_id, model=str(result.get("model") or req.model), revision=str(result.get("model_revision") or req.revision), width=int(result.get("width") or req.width),
            height=int(result.get("height") or req.height), fps=int(result.get("fps") or req.fps), num_frames=int(result.get("num_frames") or req.num_frames), seed=int(result.get("seed", req.seed)),
            gpu_seconds=0.0 if cached else float(result.get("gpu_seconds") or 0.0), timings={k: float(v) for k, v in (result.get("timings") or {}).items() if isinstance(v, (int, float))},
            cached=cached, provider=self.name,
        )

    @staticmethod
    def _failed(result: dict[str, Any], *, counted: bool = False) -> MotionError:
        """The error for a ``state=failed`` result. ``counted``: the failure happened during THIS call, so its GPU seconds are ours to account for."""
        err = result.get("error") or {}
        code = str(err.get("code") or "internal")
        message = str(err.get("message") or "the worker reported a failure")[:300]
        if code == "bad_request":
            return MotionBadRequest(f"the motion worker rejected the request: {message}", params={"detail": message})
        gpu = float(result.get("gpu_seconds") or 0.0) if counted else 0.0
        return MotionFailed(f"the motion model failed ({code}): {message}", worker_code=code, retryable=bool(err.get("retryable")), gpu_seconds=gpu, params={"detail": f"{code}: {message}"})

    async def _clear(self, job_id: str) -> None:
        for name in ("result.json", "status.json"):
            await self.transport.delete_output(job_id, name)

    async def close(self) -> None:
        await self.transport.close()
