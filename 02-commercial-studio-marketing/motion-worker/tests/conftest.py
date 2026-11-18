"""Shared fixtures: everything here is CPU-only, offline and Azure-free."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from motion_worker import contract
from motion_worker.config import Config
from motion_worker.pipeline import FakePipeline
from motion_worker.transport import IN, OUT, LocalTransport
from motion_worker.video import find_ffmpeg
from motion_worker.worker import Worker

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
SCHEMA_PATH = CONTRACTS / "motion-v1.schema.json"
VECTORS_PATH = CONTRACTS / "job-id-vectors.json"
CONTRACT_README = CONTRACTS / "README.md"


def have_ffmpeg() -> bool:
    try:
        find_ffmpeg()
    except Exception:  # noqa: BLE001 - any failure means "no usable ffmpeg": the ffmpeg-marked tests are skipped
        return False
    return True


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "ffmpeg: needs ffmpeg")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if have_ffmpeg():
        return
    skip = pytest.mark.skip(reason="ffmpeg not available (install imageio-ffmpeg)")
    for item in items:
        if "ffmpeg" in item.keywords:
            item.add_marker(skip)


def wait_until(predicate: Callable[[], Any], timeout: float = 10.0, interval: float = 0.01) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met within timeout")


def make_cfg(tmp_path: Path, **overrides: Any) -> Config:
    """A fast local-transport config (tiny intervals) for in-process tests."""
    base: dict[str, Any] = {
        "transport": "local",
        "local_dir": tmp_path / "bus",
        "model_dir": tmp_path / "models",
        "work_dir": tmp_path / "work",
        "pipeline": "fake",
        "replica": "test-replica",
        "poll_interval_s": 0.01,
        "status_interval_s": 0.02,
        "ready_interval_s": 0.05,
        "renew_interval_s": 0.05,
        "job_timeout_s": 30.0,
        "watchdog_grace_s": 30.0,
    }
    base.update(overrides)
    return replace(Config(), **base)


def keyframe_bytes(width: int = 320, height: int = 200, fmt: str = "JPEG", seed: int = 1) -> bytes:
    """A textured image: any sub-pixel motion changes many pixels, so 'it moves' assertions are meaningful."""
    rng = np.random.default_rng(seed)
    arr = (rng.random((height, width, 3)) * 160 + 40).astype(np.uint8)
    arr[height // 4 : height // 2, width // 5 : width // 2] = (225, 120, 40)
    arr[height // 2 :, width // 2 :] = (30, 90, 200)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format=fmt, **({"quality": 92} if fmt == "JPEG" else {}))
    return buf.getvalue()


def submit_job(transport: Any, *, image_bytes: bytes | None = None, **overrides: Any) -> dict[str, Any]:
    """Producer side of the contract: image + request.json + queue message. Returns the request dict."""
    params: dict[str, Any] = {
        "prompt": "slow cinematic push-in, steam rises",
        "negative_prompt": "blurry, text",
        "width": 256,
        "height": 256,
        "num_frames": 25,
        "steps": 8,
        "seed": 7,
        "shot_id": "s1",
        "campaign_id": "cmp_test",
        "image_name": "image.jpg",
    }
    params.update(overrides)
    data = image_bytes if image_bytes is not None else keyframe_bytes()
    request = contract.build_request(image_bytes=data, **params)
    job_id = request["job_id"]
    transport.write_blob(IN, f"{job_id}/{request['image']}", data, "image/jpeg")
    transport.write_blob(IN, f"{job_id}/request.json", json.dumps(request).encode())
    transport.send(contract.build_queue_message(job_id))
    return request


def read_json(transport: Any, area: str, name: str) -> Any:
    raw = transport.read_blob(area, name)
    assert raw is not None, f"missing blob {area}/{name}"
    return json.loads(raw)


def result_of(transport: Any, job_id: str) -> dict[str, Any]:
    return read_json(transport, OUT, f"{job_id}/result.json")


class RecordingTransport(LocalTransport):
    """LocalTransport that records every blob write and queue renewal (order + content)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.writes: list[tuple[str, str, bytes]] = []
        self.renewals = 0
        self.receipts_seen: list[str] = []
        self._rec_lock = threading.Lock()

    def write_blob(self, area: str, name: str, data: bytes, content_type: str = "application/json") -> None:
        with self._rec_lock:
            self.writes.append((area, name, data))
        super().write_blob(area, name, data, content_type)

    def renew(self, msg: Any, visibility_timeout_s: int) -> None:
        super().renew(msg, visibility_timeout_s)
        with self._rec_lock:
            self.renewals += 1
            self.receipts_seen.append(msg.receipt)

    def written(self, suffix: str) -> list[dict[str, Any]]:
        with self._rec_lock:
            return [json.loads(d) for (_, n, d) in self.writes if n.endswith(suffix)]

    def write_names(self, area: str = OUT) -> list[str]:
        with self._rec_lock:
            return [n for (a, n, _) in self.writes if a == area]


class Harness:
    """A worker wired to a local transport + FakePipeline inside tmp_path."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        pipeline: Any = None,
        transport_cls: type = RecordingTransport,
        hf_download: Any = None,
        **cfg: Any,
    ):
        self.cfg = make_cfg(tmp_path, **cfg)
        self.transport = transport_cls(self.cfg.local_dir)
        self.pipeline = pipeline if pipeline is not None else FakePipeline(self.cfg)
        self.exits: list[int] = []
        self.worker = Worker(
            self.cfg, self.transport, self.pipeline, exit_fn=self.exits.append, hf_download=hf_download
        )
        self._thread: threading.Thread | None = None
        self.exit_code: int | None = None

    def submit(self, **overrides: Any) -> dict[str, Any]:
        return submit_job(self.transport, **overrides)

    def run_once(self) -> str | None:
        """Receive one message and process it synchronously."""
        msg = self.transport.receive(self.cfg.visibility_timeout_s)
        return None if msg is None else self.worker.process_message(msg)

    def start(self) -> Harness:
        def target() -> None:
            self.exit_code = self.worker.run()

        self._thread = threading.Thread(target=target, name="worker-under-test", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 15.0) -> None:
        self.worker.request_shutdown("test")
        if self._thread is not None:
            self._thread.join(timeout)
            assert not self._thread.is_alive(), "worker thread did not stop"

    def result(self, job_id: str) -> dict[str, Any]:
        return result_of(self.transport, job_id)

    def wait_result(self, job_id: str, timeout: float = 20.0) -> dict[str, Any]:
        wait_until(lambda: self.transport.blob_exists(OUT, f"{job_id}/result.json"), timeout)
        return self.result(job_id)


@pytest.fixture
def harness(tmp_path: Path) -> Callable[..., Harness]:
    created: list[Harness] = []

    def factory(**kwargs: Any) -> Harness:
        h = Harness(tmp_path, **kwargs)
        created.append(h)
        return h

    yield factory
    for h in created:
        if h._thread is not None and h._thread.is_alive():
            h.stop()
    shutil.rmtree(tmp_path / "work", ignore_errors=True)


@pytest.fixture(scope="session")
def schema() -> dict[str, Any]:
    if not SCHEMA_PATH.exists():
        pytest.skip("contracts/motion-v1.schema.json not present")
    return json.loads(SCHEMA_PATH.read_text("utf-8"))


@pytest.fixture(scope="session")
def validate(schema: dict[str, Any]) -> Callable[[str, Any], None]:
    jsonschema = pytest.importorskip("jsonschema")

    def check(name: str, doc: Any) -> None:
        validator = jsonschema.Draft202012Validator(
            {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{name}"}
        )
        validator.validate(doc)

    return check


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
