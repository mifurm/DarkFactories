"""The worker: one job at a time, driven by the queue.

Semantics (see contracts/README.md): visibility timeout renewed while a job runs, idempotent (an existing
``result.json`` short-circuits), poison guard (``dequeue_count`` > MAX), ``result.json`` is written last and
the message is deleted only after it, graceful SIGTERM (finish the job if the grace period allows, otherwise
release the message so the next replica takes it), and a watchdog that restarts a replica whose GPU call hung.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import contract
from .config import Config
from .errors import (
    BadRequest,
    InternalError,
    JobAborted,
    JobTimeout,
    MessageLost,
    MotionError,
    ShutdownRequested,
    classify_exception,
)
from .imaging import MAX_IMAGE_BYTES, decode_image, fit_image
from .logs import event, exception_event
from .pipeline import Clip, LoadInfo, Pipeline
from .transport import IN, OUT, ReceivedMessage, Transport
from .weights import WeightsManager, WeightsResult

READY_BLOB = "_worker/ready.json"
CLIP_NAME = "clip.mp4"
EXIT_STUCK = 70


def _dump(doc: dict[str, Any]) -> bytes:
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class PeriodicTask:
    """Runs ``fn`` every ``interval_s`` on a daemon thread. Exceptions are logged, never raised."""

    def __init__(self, name: str, interval_s: float, fn: Callable[[], None], *, immediate: bool = True) -> None:
        self.name = name
        self.interval_s = interval_s
        self.fn = fn
        self.immediate = immediate
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)

    def start(self) -> PeriodicTask:
        self._thread.start()
        return self

    def _run(self) -> None:
        if not self.immediate and self._stop.wait(self.interval_s):
            return
        while True:
            try:
                self.fn()
            except Exception as exc:  # noqa: BLE001 - a failing heartbeat must never kill the job
                event("task_error", logging.WARNING, task=self.name, error=f"{type(exc).__name__}: {exc}")
            if self._stop.wait(self.interval_s):
                return

    def stop(self, timeout: float = 15.0) -> None:
        self._stop.set()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout)


class JobProgress:
    """Thread-safe, monotonic progress shared by the pipeline callback (writer) and the status task (reader)."""

    # denoising covers 0.05..0.85 (after the last step the pipeline VAE-decodes: "decoding frames"), then these phases
    PHASES = {
        "encoding": (0.93, "encoding video"),
        "uploading": (0.97, "uploading clip"),
    }

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.progress = 0.0
        self.step = 0
        self.steps = 0
        self.message = "starting"

    def update(
        self,
        *,
        progress: float | None = None,
        step: int | None = None,
        steps: int | None = None,
        message: str | None = None,
    ) -> None:
        with self._lock:
            if steps is not None:
                self.steps = steps
            if step is not None:
                self.step = max(self.step, step)
            if progress is not None:
                self.progress = max(self.progress, progress)
            if message is not None:
                self.message = message

    def denoising(self, step: int, steps: int) -> None:
        done = step >= steps
        self.update(
            progress=0.05 + 0.80 * (step / steps if steps else 1.0),
            step=step,
            steps=steps,
            message="decoding frames" if done else "denoising",
        )

    def phase(self, name: str) -> None:
        progress, message = self.PHASES[name]
        self.update(progress=progress, message=message)

    def snapshot(self) -> tuple[float, int, int, str]:
        with self._lock:
            return self.progress, self.step, self.steps, self.message


@dataclass
class JobContext:
    job_id: str
    msg: ReceivedMessage
    started: float
    progress: JobProgress = field(default_factory=JobProgress)
    request: contract.MotionRequest | None = None
    queue_wait_s: float = 0.0
    finalized: bool = False
    final_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def claim_finalization(self) -> bool:
        with self.final_lock:
            if self.finalized:
                return False
            self.finalized = True
            return True


class ReadyBeacon:
    """Owns ``motion-out/_worker/ready.json``: written on every state change and refreshed every ready_interval_s."""

    def __init__(self, cfg: Config, transport: Transport, pipeline: Pipeline) -> None:
        self.cfg = cfg
        self.transport = transport
        self.pipeline = pipeline
        self.state = "loading"
        self.started_at = contract.utc_now_iso()
        self._task = PeriodicTask("ready-beacon", cfg.ready_interval_s, self.write_now, immediate=True)

    def start(self) -> None:
        self._task.start()

    def set_state(self, state: str) -> None:
        self.state = state
        try:
            self.write_now()
        except Exception as exc:  # noqa: BLE001 - e.g. RBAC still propagating; the periodic task retries
            event("ready_write_failed", logging.WARNING, error=f"{type(exc).__name__}: {exc}")

    def write_now(self) -> None:
        doc = contract.build_ready(
            state=self.state,
            replica=self.cfg.replica,
            model=self.cfg.model_id,
            model_revision=self.pipeline.revision,
            vram_gib=self.pipeline.vram_gib,
            started_at=self.started_at,
        )
        self.transport.write_blob(OUT, READY_BLOB, _dump(doc))

    def stop(self) -> None:
        self._task.stop()
        try:  # delete only our own document: a successor replica may already have written its own
            raw = self.transport.read_blob(OUT, READY_BLOB)
            if raw and json.loads(raw).get("replica") == self.cfg.replica:
                self.transport.delete_blob(OUT, READY_BLOB)
        except Exception as exc:  # noqa: BLE001
            event("ready_clear_failed", logging.WARNING, error=f"{type(exc).__name__}: {exc}")


class Worker:
    def __init__(
        self,
        cfg: Config,
        transport: Transport,
        pipeline: Pipeline,
        *,
        weights: WeightsManager | None = None,
        hf_download: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        exit_fn: Callable[[int], Any] = os._exit,
    ) -> None:
        self.cfg = cfg
        self.transport = transport
        self.pipeline = pipeline
        self.clock = clock
        self.exit_fn = exit_fn
        self._stop = threading.Event()
        self._shutdown_at: float | None = None
        self._shutdown_reason = ""
        self._warmed = False
        self._mirror_thread: threading.Thread | None = None
        if weights is None and pipeline.needs_weights:
            weights = WeightsManager(cfg, transport, hf_download=hf_download, stop=self._stop)
        self.weights = weights
        self.beacon = ReadyBeacon(cfg, transport, pipeline)

    # -- lifecycle ------------------------------------------------------------------------------------

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def request_shutdown(self, reason: str = "requested") -> None:
        """Signal-handler safe (no logging, no I/O): the main loop reports and acts on it."""
        if not self._stop.is_set():
            self._shutdown_at = self.clock()
            self._shutdown_reason = reason
            self._stop.set()

    def run(self) -> int:
        event(
            "worker_start",
            replica=self.cfg.replica,
            pipeline=self.pipeline.name,
            transport=self.transport.name,
            model=self.cfg.model_id,
            revision=self.pipeline.revision,
        )
        exit_code = 0
        try:
            shutil.rmtree(self.cfg.work_dir, ignore_errors=True)
            self.cfg.work_dir.mkdir(parents=True, exist_ok=True)
            self.beacon.start()
            self.pipeline.preflight()
            self._load()
            if self._stop.is_set():  # SIGTERM during the load: never advertise 'ready' on the way out
                raise ShutdownRequested()
            self.beacon.set_state("ready")
            event("worker_ready", vram_gib=self.pipeline.vram_gib, revision=self.pipeline.revision)
            self._loop()
        except ShutdownRequested:
            event("shutdown_during_startup")
        except Exception:  # noqa: BLE001 - top-level guard: log, exit non-zero, let the platform restart the replica
            exception_event("worker_fatal")
            exit_code = 1
        finally:
            self._cleanup()
        event("worker_stopped", exit_code=exit_code, reason=self._shutdown_reason or "idle-exit")
        return exit_code

    def _cleanup(self) -> None:
        self._stop.set()
        if self._mirror_thread is not None:
            self._mirror_thread.join(15.0)
        self.beacon.stop()
        shutil.rmtree(self.cfg.work_dir, ignore_errors=True)

    # -- start-up -------------------------------------------------------------------------------------

    def _load(self) -> None:
        if self.weights is None:
            self.pipeline.load(None)
            return
        result = self.weights.ensure()
        if self._stop.is_set():  # SIGTERM arrived during the (long) download: do not load 22 GiB onto the GPU
            raise ShutdownRequested()
        try:
            info = self.pipeline.load(result.path, export_bf16_to=self._export_dir(result))
        except Exception as exc:  # any load problem with a local/mirror copy falls back to upstream once
            if result.source == "hf":
                raise
            # Local/mirror content may be damaged (the CUDA preflight already passed): rebuild from upstream once.
            event("pipeline_load_failed", logging.WARNING, source=result.source, error=f"{type(exc).__name__}: {exc}")
            result = self.weights.ensure(skip_mirror=True)
            info = self.pipeline.load(result.path, export_bf16_to=self._export_dir(result))
        if result.source == "hf":
            self._start_mirror(result, info)

    def _export_dir(self, result: WeightsResult) -> Path | None:
        if self.cfg.mirror and self.cfg.mirror_bf16 and result.source == "hf":
            return self.cfg.work_dir / "mirror-bf16"
        return None

    def _start_mirror(self, result: WeightsResult, info: LoadInfo) -> None:
        """Write-through of freshly downloaded weights, in the background so the worker is ready immediately."""
        weights = self.weights
        if not self.cfg.mirror or weights is None:
            return
        export_dir = self._export_dir(result)
        overrides = {"transformer": export_dir} if info.exported_bf16 and export_dir is not None else None

        def work() -> None:
            try:
                weights.mirror_upload(result.path, overrides)
            except ShutdownRequested:
                event("mirror_upload_interrupted")
            except Exception:  # noqa: BLE001 - the mirror is an optimisation; never take the worker down
                exception_event("mirror_upload_failed")

        self._mirror_thread = threading.Thread(target=work, name="mirror-upload", daemon=True)
        self._mirror_thread.start()

    # -- main loop ------------------------------------------------------------------------------------

    def _loop(self) -> None:
        cfg = self.cfg
        idle_since = self.clock()
        failures = 0
        while not self._stop.is_set():
            try:
                msg = self.transport.receive(cfg.visibility_timeout_s)
            except Exception as exc:  # noqa: BLE001 - never die on a transient queue problem
                failures += 1
                event("receive_failed", logging.WARNING, consecutive=failures, error=f"{type(exc).__name__}: {exc}")
                if failures == 3:
                    self.beacon.set_state("loading")  # not usable until the queue answers again
                self._stop.wait(min(30.0, cfg.poll_interval_s * 2.0**failures))
                continue
            if failures >= 3:
                self.beacon.set_state("ready")
            failures = 0
            if msg is None:
                if cfg.exit_when_idle_s and self.clock() - idle_since >= cfg.exit_when_idle_s:
                    event("idle_exit", idle_s=cfg.exit_when_idle_s)
                    return
                self._stop.wait(cfg.poll_interval_s)
                continue
            idle_since = self.clock()
            self.handle(msg)
            idle_since = self.clock()

    def handle(self, msg: ReceivedMessage) -> str:
        """Process one message; anything unexpected leaves it in the queue to reappear (bounded by the poison guard)."""
        try:
            return self.process_message(msg)
        except Exception:  # noqa: BLE001 - the message stays queued and reappears; the poison guard bounds retries
            exception_event("message_handler_error", message_id=msg.id, dequeue_count=msg.dequeue_count)
            self._stop.wait(1.0)  # no hot loop on a persistent fault
            return "error"

    # -- message handling -----------------------------------------------------------------------------

    def process_message(self, msg: ReceivedMessage) -> str:
        try:
            job = contract.parse_queue_message(msg.body)
        except BadRequest as exc:
            event("message_invalid", logging.WARNING, message_id=msg.id, error=exc.message)
            self._delete(msg)
            return "invalid"
        if job.type == contract.WARMUP:
            return self._warmup(msg, job.job_id)
        return self._generate(msg, job.job_id)

    def _delete(self, msg: ReceivedMessage) -> None:
        try:
            self.transport.delete(msg)
        except MessageLost:
            event("message_lost", logging.WARNING, message_id=msg.id, action="delete")
        except Exception as exc:  # noqa: BLE001 - result.json exists, so a re-delivery is a harmless no-op
            event("message_delete_failed", logging.ERROR, message_id=msg.id, error=f"{type(exc).__name__}: {exc}")

    def _release(self, msg: ReceivedMessage) -> None:
        try:
            self.transport.release(msg)
        except MessageLost:
            event("message_lost", logging.WARNING, message_id=msg.id, action="release")
        except Exception as exc:  # noqa: BLE001 - it reappears after its visibility timeout anyway
            event("message_release_failed", logging.ERROR, message_id=msg.id, error=f"{type(exc).__name__}: {exc}")

    def _warmup(self, msg: ReceivedMessage, job_id: str) -> str:
        event("warmup", job_id=job_id, dequeue_count=msg.dequeue_count)
        if self.cfg.warmup_generate and not self._warmed:
            try:
                self.pipeline.warmup(self.cfg.work_dir / "warmup")
                self._warmed = True
            except Exception as exc:  # noqa: BLE001 - priming is an optimisation, never a failure
                event("warmup_generate_failed", logging.WARNING, error=f"{type(exc).__name__}: {exc}")
        self.beacon.set_state(self.beacon.state)  # refresh updated_at right now
        self._delete(msg)
        return "warmup"

    def _generate(self, msg: ReceivedMessage, job_id: str) -> str:
        started = self.clock()
        if self.transport.blob_exists(OUT, f"{job_id}/result.json"):
            event("job_skipped", job_id=job_id, reason="result_exists", dequeue_count=msg.dequeue_count)
            self._delete(msg)
            return "skipped"
        if msg.dequeue_count > self.cfg.max_dequeue:
            ctx = JobContext(job_id=job_id, msg=msg, started=started)
            error = InternalError(
                f"message was delivered {msg.dequeue_count} times without completing (poison message)",
                retryable=False,
            )
            event("job_poison", logging.ERROR, job_id=job_id, dequeue_count=msg.dequeue_count)
            self._finish_failed(ctx, error)
            return "poison"
        if self._stop.is_set():
            self._release(msg)  # shutting down: let the next replica take it
            return "released"
        return self._run_job(JobContext(job_id=job_id, msg=msg, started=started))

    # -- job ------------------------------------------------------------------------------------------

    def _run_job(self, ctx: JobContext) -> str:
        tasks = self._start_tasks(ctx)
        workdir = self.cfg.work_dir / ctx.job_id
        clip: Clip | None = None
        error: MotionError | None = None
        aborted = False
        try:
            clip = self._produce_clip(ctx, workdir)
        except JobAborted:
            aborted = True
        except Exception as exc:  # noqa: BLE001
            error = classify_exception(exc)
            if error.code == "internal":
                exception_event("job_exception", job_id=ctx.job_id)
        finally:
            for task in tasks:
                task.stop()
        # the exception (and the CUDA tensors its traceback pins) is gone here, so the allocator can really release
        self.pipeline.release_memory()
        shutil.rmtree(workdir, ignore_errors=True)
        if aborted:
            event(
                "job_aborted",
                logging.WARNING,
                job_id=ctx.job_id,
                reason="shutdown",
                reason_detail=self._shutdown_reason,
            )
            self._release(ctx.msg)
            return "aborted"
        if error is not None:
            self._finish_failed(ctx, error)
            return "failed"
        assert clip is not None
        self._finish_ok(ctx, clip)
        return "succeeded"

    def _start_tasks(self, ctx: JobContext) -> list[PeriodicTask]:
        cfg = self.cfg
        watchdog_interval = min(5.0, max(0.05, cfg.job_timeout_s / 20))
        return [
            PeriodicTask(f"status-{ctx.job_id[:11]}", cfg.status_interval_s, lambda: self._write_status(ctx)).start(),
            PeriodicTask("renew", cfg.renew_interval_s, lambda: self._renew(ctx), immediate=False).start(),
            PeriodicTask("watchdog", watchdog_interval, lambda: self._watchdog(ctx), immediate=False).start(),
        ]

    def _produce_clip(self, ctx: JobContext, workdir: Path) -> Clip:
        request = self._load_request(ctx)
        ctx.request = request
        ctx.progress.update(progress=0.02, steps=request.steps, message="preparing")
        event(
            "job_start",
            job_id=ctx.job_id,
            shot_id=request.shot_id,
            campaign_id=request.campaign_id,
            width=request.width,
            height=request.height,
            num_frames=request.num_frames,
            steps=request.steps,
            seed=request.seed,
            dequeue_count=ctx.msg.dequeue_count,
            queue_wait_s=round(ctx.queue_wait_s, 1),
        )
        image, sha = self._load_image(ctx, request)
        expected = request.expected_job_id(image_sha256=sha, default_revision=self.cfg.model_revision)
        if expected != request.job_id:
            event("job_id_mismatch", logging.WARNING, job_id=request.job_id, expected=expected)

        def on_step(step: int, steps: int) -> None:
            ctx.progress.denoising(step, steps)
            self._check_abort(ctx)

        def on_phase(name: str) -> None:
            ctx.progress.phase(name)

        ctx.progress.update(progress=0.05, step=0, message="denoising")
        clip = self.pipeline.generate(request, image, on_step, on_phase, workdir=workdir)
        ctx.progress.phase("uploading")
        self.transport.write_blob(OUT, f"{ctx.job_id}/{CLIP_NAME}", clip.data, "video/mp4")
        return clip

    def _load_request(self, ctx: JobContext) -> contract.MotionRequest:
        raw = self.transport.read_blob(IN, f"{ctx.job_id}/request.json")
        if raw is None:
            raise BadRequest("request.json not found")
        if len(raw) > contract.MAX_REQUEST_BYTES:
            raise BadRequest("request.json is too large")
        try:
            doc = json.loads(raw)
        except ValueError:
            raise BadRequest("request.json is not valid JSON") from None
        request = contract.parse_request(doc)
        if request.job_id != ctx.job_id:
            raise BadRequest("request.json job_id does not match the queue message")
        if request.model != self.cfg.model_id:
            raise BadRequest(f"model {request.model!r} is not served by this worker (serves {self.cfg.model_id!r})")
        enqueued = ctx.msg.inserted_at or contract.parse_iso(request.created_at)
        if enqueued is not None:
            ctx.queue_wait_s = max(0.0, (datetime.now(UTC) - enqueued).total_seconds())
        return request

    def _load_image(self, ctx: JobContext, request: contract.MotionRequest) -> tuple[Any, str]:
        key = f"{ctx.job_id}/{request.image}"
        size = self.transport.blob_size(IN, key)
        if size is None:
            raise BadRequest(f"image blob {request.image!r} not found")
        if size > MAX_IMAGE_BYTES:
            raise BadRequest(f"image is too large ({size} bytes)")
        data = self.transport.read_blob(IN, key)
        if data is None:
            raise BadRequest(f"image blob {request.image!r} not found")
        sha = hashlib.sha256(data).hexdigest()
        if request.image_sha256 is not None and request.image_sha256 != sha:
            raise BadRequest("image_sha256 does not match the uploaded image")
        return fit_image(decode_image(data), request.width, request.height), sha

    def _check_abort(self, ctx: JobContext) -> None:
        now = self.clock()
        if now - ctx.started > self.cfg.job_timeout_s:
            raise JobTimeout(f"job exceeded {self.cfg.job_timeout_s:.0f}s")
        if (
            self._shutdown_at is not None
            and now - self._shutdown_at >= self.cfg.shutdown_grace_s - self.cfg.shutdown_margin_s
        ):
            raise JobAborted()

    # -- heartbeat tasks ------------------------------------------------------------------------------

    def _write_status(self, ctx: JobContext) -> None:
        progress, step, steps, message = ctx.progress.snapshot()
        doc = contract.build_status(
            job_id=ctx.job_id,
            state="running",
            progress=progress,
            step=step,
            steps=steps,
            message=message,
            replica=self.cfg.replica,
        )
        self.transport.write_blob(OUT, f"{ctx.job_id}/status.json", _dump(doc))

    def _renew(self, ctx: JobContext) -> None:
        if ctx.msg.lost:
            return
        try:
            self.transport.renew(ctx.msg, self.cfg.visibility_timeout_s)
        except MessageLost:
            event("message_lost", logging.WARNING, job_id=ctx.job_id, action="renew")

    def _watchdog(self, ctx: JobContext) -> None:
        if ctx.finalized or self.clock() - ctx.started <= self.cfg.job_timeout_s + self.cfg.watchdog_grace_s:
            return
        event(
            "job_stuck", logging.CRITICAL, job_id=ctx.job_id, limit_s=self.cfg.job_timeout_s + self.cfg.watchdog_grace_s
        )
        try:
            self._finish_failed(ctx, JobTimeout("the GPU worker hung on this job and was restarted"))
        finally:
            self.exit_fn(EXIT_STUCK)  # a hung CUDA call cannot be interrupted: let the platform restart the replica

    # -- terminal states ------------------------------------------------------------------------------

    def _finish_ok(self, ctx: JobContext, clip: Clip) -> None:
        if not ctx.claim_finalization():
            return
        request = ctx.request
        assert request is not None
        gpu_seconds = self.clock() - ctx.started
        status = contract.build_status(
            job_id=ctx.job_id,
            state="succeeded",
            progress=1.0,
            step=request.steps,
            steps=request.steps,
            message="done",
            replica=self.cfg.replica,
        )
        result = contract.build_result(
            job_id=ctx.job_id,
            request=request,
            model=self.cfg.model_id,
            model_revision=self.pipeline.revision,
            gpu_seconds=gpu_seconds,
            queue_wait_s=ctx.queue_wait_s,
            generate_s=clip.generate_s,
            encode_s=clip.encode_s,
            clip=CLIP_NAME,
            width=clip.width,
            height=clip.height,
            num_frames=clip.num_frames,
        )
        self.transport.write_blob(OUT, f"{ctx.job_id}/status.json", _dump(status))
        self.transport.write_blob(OUT, f"{ctx.job_id}/result.json", _dump(result))  # terminal marker: written last
        event(
            "job_done",
            job_id=ctx.job_id,
            shot_id=request.shot_id,
            state="succeeded",
            gpu_seconds=result["gpu_seconds"],
            generate_s=result["timings"]["generate_s"],
            encode_s=result["timings"]["encode_s"],
            num_frames=clip.num_frames,
            bytes=len(clip.data),
        )
        self._delete(ctx.msg)

    def _finish_failed(self, ctx: JobContext, error: MotionError) -> None:
        if not ctx.claim_finalization():
            return
        request = ctx.request
        progress, step, steps, _ = ctx.progress.snapshot()
        gpu_seconds = self.clock() - ctx.started
        status = contract.build_status(
            job_id=ctx.job_id,
            state="failed",
            progress=progress,
            step=step,
            steps=steps,
            message=error.code,
            replica=self.cfg.replica,
        )
        result = contract.build_result(
            job_id=ctx.job_id,
            request=request,
            model=request.model if request else self.cfg.model_id,
            model_revision=self.pipeline.revision,
            gpu_seconds=gpu_seconds,
            queue_wait_s=ctx.queue_wait_s,
            generate_s=0.0,
            encode_s=0.0,
            error=error.to_wire(),
        )
        self.transport.write_blob(OUT, f"{ctx.job_id}/status.json", _dump(status))
        self.transport.write_blob(OUT, f"{ctx.job_id}/result.json", _dump(result))
        event(
            "job_failed",
            logging.WARNING,
            job_id=ctx.job_id,
            shot_id=request.shot_id if request else None,
            state="failed",
            error_code=error.code,
            retryable=error.retryable,
            message=error.message[:200],
            gpu_seconds=result["gpu_seconds"],
        )
        self._delete(ctx.msg)


def install_signal_handlers(worker: Worker) -> None:
    """SIGTERM/SIGINT request a graceful stop; a second Ctrl-C raises KeyboardInterrupt for local runs."""

    def handler(signum: int, _frame: Any) -> None:
        if worker.stopping and signum == signal.SIGINT:
            raise KeyboardInterrupt
        worker.request_shutdown(signal.Signals(signum).name)

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, handler)
