"""Error taxonomy. Wire codes (result.json ``error.code``): oom | bad_request | timeout | internal."""

from __future__ import annotations

from typing import Any


class MotionError(Exception):
    """A job-level failure that is reported to the producer in ``result.json``."""

    code = "internal"
    retryable = True

    def __init__(self, message: str, *, retryable: bool | None = None) -> None:
        super().__init__(message)
        self.message = message
        if retryable is not None:
            self.retryable = retryable

    def to_wire(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message[:500], "retryable": self.retryable}


class BadRequest(MotionError):
    """The request can never succeed as sent (invalid fields, missing/unsupported image, wrong model)."""

    code = "bad_request"
    retryable = False


class OutOfMemory(MotionError):
    """CUDA (or host) out of memory. The same parameters will fail again, so it is not retryable."""

    code = "oom"
    retryable = False


class JobTimeout(MotionError):
    code = "timeout"
    retryable = True


class InternalError(MotionError):
    code = "internal"
    retryable = True


class ConfigError(Exception):
    """Invalid worker configuration (environment)."""


class WeightsError(Exception):
    """Model weights could not be made available."""


class ShutdownRequested(Exception):
    """Control flow: SIGTERM/SIGINT arrived while a long start-up step (weights download) was running."""


class JobAborted(Exception):
    """Control flow: an in-flight job is abandoned because the shutdown grace period is nearly exhausted."""


class MessageLost(Exception):
    """The queue message no longer belongs to this worker (expired and re-delivered, or already deleted)."""


_OOM_MARKERS = (
    "out of memory",
    "cublas_status_alloc_failed",
    "cudnn_status_alloc_failed",
    "cannot allocate memory",
)


def is_out_of_memory(exc: BaseException) -> bool:
    """True for torch.cuda.OutOfMemoryError (detected by name, no torch import), MemoryError and CUDA OOM text."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    for _ in range(6):
        if cur is None or id(cur) in seen:
            break
        seen.add(id(cur))
        if isinstance(cur, MemoryError) or any(c.__name__ == "OutOfMemoryError" for c in type(cur).__mro__):
            return True
        if isinstance(cur, RuntimeError | OSError):
            text = str(cur).lower()
            if any(marker in text for marker in _OOM_MARKERS):
                return True
        cur = cur.__cause__ or cur.__context__
    return False


def classify_exception(exc: BaseException) -> MotionError:
    """Map any exception raised while serving a job to a wire error."""
    if isinstance(exc, MotionError):
        return exc
    if is_out_of_memory(exc):
        return OutOfMemory("out of memory while generating the clip (reduce resolution or frame count)")
    return InternalError(f"{type(exc).__name__}: {exc}"[:400])
