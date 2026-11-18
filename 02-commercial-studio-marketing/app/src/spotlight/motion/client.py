"""MotionClient: the pluggable image-to-video backend behind cinematic renders.

* ``azure``  — storage queue + blobs to the GPU worker (Wan 2.2 TI2V-5B on Azure Container Apps serverless GPU), keyless (Entra / managed identity)
* ``local``  — the same protocol over a local directory (tests, development, the worker's fake pipeline)
* ``stub``   — a deterministic procedural animator: the offline default, produces a real moving clip without any model
* ``off``    — cinematic quality is not offered
"""

from __future__ import annotations

from typing import Any, Protocol

from .models import MotionDisabled, MotionRequest, MotionResult, ProgressCb, WorkerStatus


class MotionClient(Protocol):
    name: str  # azure | local | stub | off
    model: str  # what actually renders the motion (a model id, or the stub animator)
    revision: str
    license: str
    host: str

    def capabilities(self) -> dict[str, Any]: ...

    async def status(self) -> WorkerStatus: ...

    async def warmup(self) -> WorkerStatus: ...

    async def generate(self, req: MotionRequest, on_progress: ProgressCb | None = None, timeout_s: float = 1500.0) -> MotionResult: ...

    async def close(self) -> None: ...


class OffMotionClient:
    """Cinematic motion is not configured: every call says so (status() still answers, so the UI can explain why the option is disabled)."""

    name = "off"
    model = ""
    revision = ""
    license = ""
    host = ""

    def __init__(self, model: str = "", reason: str = "") -> None:
        self.model = model
        self.reason = reason

    def capabilities(self) -> dict[str, Any]:
        return {"kind": "image-to-video", "configured": False}

    async def status(self) -> WorkerStatus:
        return WorkerStatus(state="cold", age_s=None, queue_depth=0)

    async def warmup(self) -> WorkerStatus:
        return await self.status()

    async def generate(self, req: MotionRequest, on_progress: ProgressCb | None = None, timeout_s: float = 1500.0) -> MotionResult:
        raise MotionDisabled("Cinematic motion is not available in this deployment.", hint="Use the Preview quality, or ask an Admin to enable the GPU motion worker (MOTION_MODE).")

    async def close(self) -> None:
        return None


def build_client(settings: Any, credential: Any = None) -> MotionClient:
    """The motion backend for ``settings.motion_effective_mode``."""
    mode = settings.motion_effective_mode
    if mode == "stub":
        from .stub_client import StubMotionClient

        return StubMotionClient(settings)
    if mode == "local":
        from .local_client import LocalMotionClient

        return LocalMotionClient.from_settings(settings)
    if mode == "azure":
        from .azure_client import AzureMotionClient

        return AzureMotionClient.from_settings(settings, credential)
    return OffMotionClient(settings.motion_model)
