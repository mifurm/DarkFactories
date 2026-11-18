"""Test doubles shared by several test modules."""

from __future__ import annotations

import fnmatch
import threading
from pathlib import Path
from typing import Any

from motion_worker.errors import MessageLost
from motion_worker.pipeline import FakePipeline, LoadInfo
from motion_worker.transport import LocalTransport

from .conftest import RecordingTransport

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + bytes(40)


def stub_encoder(frames, **kwargs):
    return FAKE_MP4, sum(1 for _ in frames)


class CountingPipeline(FakePipeline):
    """FakePipeline that records calls and offers hooks: ``after_step(step)``, ``on_generate(request)``, ``block``."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("encoder", stub_encoder)
        super().__init__(None, **kwargs)
        self.generated = 0
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()
        self.released = 0
        self.warmups = 0
        self.fail_warmup = False
        self.on_generate = None
        self.after_step = None
        self.block: threading.Event | None = None
        self.preflight_error: Exception | None = None

    def preflight(self) -> None:
        if self.preflight_error:
            raise self.preflight_error

    def generate(self, request, image, on_step=None, on_phase=None, *, workdir):
        with self._lock:
            self.generated += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.on_generate:
                self.on_generate(request)
            if self.block is not None:
                self.block.wait(30)

            def wrapped(step: int, steps: int) -> None:
                if self.after_step:
                    self.after_step(step)
                if on_step:
                    on_step(step, steps)

            return super().generate(request, image, wrapped, on_phase, workdir=workdir)
        finally:
            with self._lock:
                self.active -= 1

    def release_memory(self) -> None:
        self.released += 1

    def warmup(self, workdir: Path) -> None:
        self.warmups += 1
        if self.fail_warmup:
            raise RuntimeError("warm-up exploded")


class WeightsPipeline(CountingPipeline):
    """Needs weights: records the directories it was loaded from and can simulate failures / a bf16 export."""

    needs_weights = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.loads: list[tuple[Path | None, Path | None]] = []
        self.fail_loads = 0
        self.export_bf16 = False

    def load(self, model_path, *, export_bf16_to=None):
        self.loads.append((model_path, export_bf16_to))
        if self.fail_loads:
            self.fail_loads -= 1
            raise OSError("safetensors: corrupt header")
        exported = False
        if self.export_bf16 and export_bf16_to is not None:
            export_bf16_to.mkdir(parents=True, exist_ok=True)
            (export_bf16_to / "config.json").write_text("{}")
            (export_bf16_to / "diffusion_pytorch_model.safetensors").write_bytes(b"B" * 321)
            exported = True
        self.vram_gib = 22.6
        return LoadInfo(22.6, exported)


class FlakyTransport(LocalTransport):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fail_writes_ending: str | None = None
        self.lose_message = False
        self.fail_exists = False

    def write_blob(self, area, name, data, content_type="application/json"):
        if self.fail_writes_ending and name.endswith(self.fail_writes_ending):
            raise ConnectionError("storage is down")
        super().write_blob(area, name, data, content_type)

    def renew(self, msg, visibility_timeout_s):
        if self.lose_message:
            msg.lost = True
            raise MessageLost("expired")
        super().renew(msg, visibility_timeout_s)

    def delete(self, msg):
        if self.lose_message:
            raise MessageLost("expired")
        super().delete(msg)

    def blob_exists(self, area, name):
        if self.fail_exists:
            raise ConnectionError("storage is down")
        return super().blob_exists(area, name)


class FlakyReceive(RecordingTransport):
    """Queue outage: the first ``failures`` receive() calls raise."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.failures = 0

    def receive(self, visibility_timeout_s):
        if self.failures > 0:
            self.failures -= 1
            raise ConnectionError("queue unreachable")
        return super().receive(visibility_timeout_s)


REPO_FILES = {
    "model_index.json": b'{"_class_name": "WanImageToVideoPipeline"}',
    "transformer/config.json": b"{}",
    "transformer/diffusion_pytorch_model-00001-of-00002.safetensors": b"T" * 3000,
    "transformer/diffusion_pytorch_model-00002-of-00002.safetensors": b"U" * 2000,
    "text_encoder/model.safetensors": b"E" * 4000,
    "vae/diffusion_pytorch_model.safetensors": b"V" * 500,
    "assets/preview.png": b"P" * 100,
    "examples/demo.mp4": b"M" * 100,
    "README.md": b"# readme",
}


def expected_downloaded() -> dict[str, bytes]:
    return {k: v for k, v in REPO_FILES.items() if not k.startswith(("assets/", "examples/")) and k != "README.md"}


class FakeHf:
    """huggingface_hub.snapshot_download stand-in: honours ignore_patterns, leaves its .cache bookkeeping behind."""

    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files = REPO_FILES if files is None else files
        self.calls: list[dict] = []
        self.on_call = None

    def __call__(self, *, repo_id, revision, local_dir, ignore_patterns, max_workers):
        self.calls.append(
            {"repo_id": repo_id, "revision": revision, "local_dir": local_dir, "ignore": list(ignore_patterns),
             "workers": max_workers}
        )  # fmt: skip
        if self.on_call:
            self.on_call()
        for rel, data in self.files.items():
            if any(fnmatch.fnmatch(rel, pattern) for pattern in ignore_patterns):
                continue
            target = Path(local_dir) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        meta = Path(local_dir) / ".cache" / "huggingface" / "download" / "x.metadata"
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text("etag")
        return str(local_dir)
