"""Local-directory transport of the motion protocol (tests, development, the worker's fake pipeline).

Same layout as the blobs, rooted at ``MOTION_LOCAL_DIR``: ``queue/<ts>-<uuid>.json`` (one file per message; the worker claims it by renaming it to
``….claimed``), ``motion-in/<job_id>/…`` and ``motion-out/<job_id>/…``. Writes are atomic (temp file + rename) so a reader never sees half a file.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from . import wire
from .queue_client import QueueMotionClient


def _safe(part: str) -> str:
    if not part or "/" in part or "\\" in part or part in {".", ".."}:
        raise ValueError(f"invalid path part {part!r}")
    return part


class LocalTransport:
    name = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        for d in (wire.QUEUE_DIR, wire.IN_PREFIX, wire.OUT_PREFIX):
            (self.root / d).mkdir(parents=True, exist_ok=True)

    def _path(self, prefix: str, job_id: str, name: str) -> Path:
        return self.root / prefix / _safe(job_id) / _safe(name)

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    async def put_input(self, job_id: str, name: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(self._write, self._path(wire.IN_PREFIX, job_id, name), data)

    async def get_output(self, job_id: str, name: str) -> bytes | None:
        path = self._path(wire.OUT_PREFIX, job_id, name)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            return None

    async def delete_output(self, job_id: str, name: str) -> None:
        await asyncio.to_thread(self._path(wire.OUT_PREFIX, job_id, name).unlink, True)

    async def enqueue(self, message: dict[str, Any]) -> None:
        name = f"{time.time_ns():020d}-{uuid.uuid4().hex}.json"
        await asyncio.to_thread(self._write, self.root / wire.QUEUE_DIR / name, json.dumps(message).encode("utf-8"))

    async def queue_depth(self) -> int:
        def count() -> int:
            return sum(1 for p in (self.root / wire.QUEUE_DIR).iterdir() if p.name.endswith((".json", ".claimed")) and not p.name.startswith("."))

        return await asyncio.to_thread(count)

    async def close(self) -> None:
        return None


class LocalMotionClient(QueueMotionClient):
    """The queue protocol over a local directory (``MOTION_MODE=local`` + ``MOTION_LOCAL_DIR``)."""

    def __init__(self, root: str | Path, *, model: str = wire.MODEL_ID, revision: str = wire.MODEL_REVISION, poll_s: float = 0.2, **kw: Any) -> None:
        super().__init__(LocalTransport(root), name="local", model=model, revision=revision, license=wire.MODEL_LICENSES.get(model, ""), host="local-dir worker (development)", poll_s=poll_s, **kw)
        self.root = Path(root)

    @classmethod
    def from_settings(cls, settings: Any) -> LocalMotionClient:
        return cls(settings.motion_local_dir, model=settings.motion_model, revision=settings.motion_model_revision or wire.MODEL_REVISION)
