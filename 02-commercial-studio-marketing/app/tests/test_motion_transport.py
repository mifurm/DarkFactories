"""Cinematic motion — transports and the queue protocol: the generic client against an in-memory transport and a scripted GPU worker, the Azure Queue + Blob
transport against in-memory fakes of ``QueueClient`` / ``BlobServiceClient``, and the local-directory transport against a real worker thread."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import re
import threading
import time
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from azure.core.exceptions import ResourceNotFoundError
from PIL import Image

from spotlight.config import Settings
from spotlight.core.ai.stubs import render_stub_scene
from spotlight.motion import animator, wire
from spotlight.motion.azure_client import MESSAGE_TTL_S, AzureMotionClient, AzureTransport
from spotlight.motion.client import OffMotionClient, build_client
from spotlight.motion.local_client import LocalMotionClient, LocalTransport
from spotlight.motion.models import (
    MotionBadRequest,
    MotionFailed,
    MotionRequest,
    MotionTimeout,
    MotionTransportError,
    MotionUnavailable,
)
from spotlight.motion.queue_client import QueueMotionClient
from spotlight.motion.stub_client import StubMotionClient

ROOT = Path(__file__).resolve().parents[2]
REV = wire.MODEL_REVISION


def jpeg(seed: int = 3, size: tuple[int, int] = (320, 256)) -> bytes:
    buf = io.BytesIO()
    render_stub_scene("dawn", size, None, seed).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def make_request(**kw: Any) -> MotionRequest:
    return MotionRequest(**{"prompt": "A hand lifts the mug.", "image": jpeg(), "width": 320, "height": 256, "num_frames": 29, "seed": 5, "campaign_id": "camp", "shot_id": "s1", **kw})


def stamp(n: int) -> str:
    return f"2026-11-18T18:{n // 60:02d}:{n % 60:02d}Z"


# ------------------------------------------------------------------------------------------------ an in-memory transport and a scripted worker
#
# Nothing here is paced by wall time: the worker takes one step per poll of the client, and the clock the client decides timeouts / re-queueing / stalls on is a
# ManualClock that the polls move. Every ordering (queued -> running -> done, "nobody picked the message up", "the status stopped advancing") is therefore the same on
# a slow, loaded machine as on a fast one.


class ManualClock:
    """A clock that only moves when it is told to (the polls of the client move it): used for ``QueueMotionClient(clock=...)``."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class MemoryTransport:
    name = "memory"

    def __init__(self, clock: ManualClock | None = None, tick: float = 0.0) -> None:
        self.inputs: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.outputs: dict[tuple[str, str], bytes] = {}
        self.queue: list[dict[str, Any]] = []
        self.log: list[str] = []
        self.read_failures = 0
        self.blip_after_enqueue = 0  # reads that fail right after the job was queued (while polling)
        self.enqueue_error: Exception | None = None
        self.depth_error: Exception | None = None
        self.closed = False
        self.clock, self.tick = clock, tick  # every poll of a result moves the clock by ``tick`` seconds
        self.on_poll: Callable[[], None] | None = None  # the (simulated) worker takes one step each time the client polls

    async def put_input(self, job_id: str, name: str, data: bytes, content_type: str) -> None:
        self.log.append(f"put:{name}")
        self.inputs[(job_id, name)] = (data, content_type)

    async def get_output(self, job_id: str, name: str) -> bytes | None:
        if self.read_failures > 0:
            self.read_failures -= 1
            raise OSError("storage hiccup")
        if name == "result.json" and job_id != "_worker":  # a poll
            if self.clock is not None:
                self.clock.now += self.tick
            if self.on_poll is not None:
                self.on_poll()
        return self.outputs.get((job_id, name))

    async def delete_output(self, job_id: str, name: str) -> None:
        self.log.append(f"delete:{name}")
        self.outputs.pop((job_id, name), None)

    async def enqueue(self, message: dict[str, Any]) -> None:
        if self.enqueue_error:
            raise self.enqueue_error
        self.log.append(f"enqueue:{message['type']}")
        self.queue.append(message)
        if message["type"] == "generate":
            self.read_failures = self.blip_after_enqueue

    async def queue_depth(self) -> int:
        if self.depth_error:
            raise self.depth_error
        return len(self.queue)

    async def close(self) -> None:
        self.closed = True

    def put_json(self, job_id: str, name: str, doc: dict[str, Any]) -> None:
        self.outputs[(job_id, name)] = json.dumps(doc).encode()


def result_doc(job_id: str, *, state: str = "succeeded", gpu: float = 42.0, error: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
    ok = state == "succeeded"
    return {
        "v": 1, "job_id": job_id, "state": state, "clip": "clip.mp4" if ok else None, "width": 320, "height": 256, "fps": 24, "num_frames": 29, "seed": 5, "model": "wan2.2-ti2v-5b", "model_revision": REV,
        "gpu_seconds": gpu, "timings": {"queue_wait_s": 3.1, "generate_s": 38.0, "encode_s": 0.9}, "error": error, **kw,
    }


class FakeGpuWorker:
    """Plays the worker, one step each time the client polls (never on a timer): picks a message up, writes status.json while 'generating', then clip.mp4 + result.json
    (or a failed result). A poll is also the only thing that moves the worker, so the client always sees queued -> running (4 reports) -> done, in that order."""

    STAGES = (0.3, 0.6, 0.85)

    def __init__(self, t: MemoryTransport, *, gpu: float = 42.0, fail: dict[str, Any] | None = None, stall: bool = False, clip: bytes = b"\x00\x00\x00\x18ftypmp42FAKE") -> None:
        self.t, self.gpu, self.fail, self.stall, self.clip = t, gpu, fail, stall, clip
        self.jobs: list[str] = []
        self.warmups = 0
        self._tick = 0
        self._job: str | None = None  # the job being 'generated'
        self._stage = 0
        t.on_poll = self.step

    def _status(self, job_id: str, progress: float, state: str = "running") -> None:
        self._tick += 1
        self.t.put_json(job_id, "status.json", {"v": 1, "job_id": job_id, "state": state, "progress": progress, "step": int(progress * 20), "steps": 20, "message": "denoising", "replica": "r1", "updated_at": stamp(self._tick)})

    def step(self) -> None:
        if self._job is None:
            if not self.t.queue:
                return
            msg = self.t.queue.pop(0)
            if msg["type"] == "warmup":
                self.warmups += 1
                self.t.put_json("_worker", "ready.json", {"v": 1, "state": "ready", "replica": "r1", "model": "wan2.2-ti2v-5b", "model_revision": REV, "vram_gib": 22.6, "started_at": stamp(0), "updated_at": wire.utc_iso()})
                return
            job_id = msg["job_id"]
            if (job_id, "result.json") in self.t.outputs:
                return  # idempotent, exactly like the real worker
            self.jobs.append(job_id)
            self._job, self._stage = job_id, 0
            self._status(job_id, 0.1)
            return
        if self.stall:  # the status stopped advancing: the worker is hung
            return
        job_id = self._job
        if self._stage < len(self.STAGES):
            self._status(job_id, self.STAGES[self._stage])
            self._stage += 1
            return
        if self.fail:
            self.t.put_json(job_id, "result.json", result_doc(job_id, state="failed", gpu=self.gpu, error=self.fail))
        else:
            self.t.outputs[(job_id, "clip.mp4")] = self.clip
            self._status(job_id, 1.0, "succeeded")
            self.t.put_json(job_id, "result.json", result_doc(job_id, gpu=self.gpu))
        self._job = None


def timed(tick: float = 1.0) -> tuple[ManualClock, MemoryTransport]:
    """A transport whose every poll of a result moves a manual clock by ``tick`` seconds, and that clock: timeouts and delays are decided on it, not on wall time."""
    clock = ManualClock()
    return clock, MemoryTransport(clock, tick)


def client_for(t: MemoryTransport, **kw: Any) -> QueueMotionClient:
    return QueueMotionClient(t, name="memory", model="wan2.2-ti2v-5b", revision=REV, license="Apache-2.0", host="test", **{"poll_s": 0.0, "status_ttl_s": 0, **kw})


@pytest.fixture
def worker_world():
    t = MemoryTransport()
    return t, FakeGpuWorker(t)


# ------------------------------------------------------------------------------------------------ the protocol


async def test_generate_uploads_the_image_then_the_request_then_the_message_and_returns_the_clip(worker_world):
    t, worker = worker_world
    req = make_request()
    seen = []

    async def on_progress(p):
        seen.append(p)

    res = await client_for(t).generate(req, on_progress, 5)
    assert t.log[:3] == ["put:image.jpg", "put:request.json", "enqueue:generate"]  # contract §8.2: a worker must never dequeue a job whose inputs are missing
    assert t.inputs[(req.job_id, "image.jpg")] == (req.image, "image/jpeg")
    doc = json.loads(t.inputs[(req.job_id, "request.json")][0])
    assert doc["job_id"] == req.job_id and doc["image"] == "image.jpg" and doc["image_sha256"] == hashlib.sha256(req.image).hexdigest() and doc["model_revision"] == REV
    assert t.inputs[(req.job_id, "request.json")][1] == "application/json"
    assert res.clip == worker.clip and res.gpu_seconds == 42.0 and not res.cached and res.job_id == req.job_id and res.revision == REV and res.provider == "memory"
    assert res.timings == {"queue_wait_s": 3.1, "generate_s": 38.0, "encode_s": 0.9} and (res.width, res.height, res.num_frames, res.seed) == (320, 256, 29, 5)
    running = [p for p in seen if p.state == "running"]
    assert running and 0.0 < max(p.progress for p in running) < 1.0 and all(p.steps == 20 for p in running) and seen[0].waited_s >= 0
    assert worker.jobs == [req.job_id]


async def test_an_existing_result_is_a_free_cache_hit_and_nothing_is_queued(worker_world):
    t, worker = worker_world
    client, req = client_for(t), make_request()
    first = await client.generate(req, None, 5)
    t.log.clear()
    again = await client.generate(req, None, 5)
    assert again.cached and again.gpu_seconds == 0.0 and again.clip == first.clip and first.gpu_seconds == 42.0  # no GPU time is attributed to the second call
    assert t.log == [] and worker.jobs == [req.job_id]  # no upload, no message, no second run
    other = await client.generate(make_request(seed=6), None, 5)
    assert other.job_id != req.job_id and not other.cached and len(worker.jobs) == 2


async def test_a_failed_result_that_cannot_succeed_fails_fast_without_queueing_and_is_not_billed_twice():
    t, req = MemoryTransport(), make_request()
    t.put_json(req.job_id, "result.json", result_doc(req.job_id, state="failed", gpu=41.8, error={"code": "oom", "message": "out of memory", "retryable": False}))
    with pytest.raises(MotionFailed) as exc:
        await client_for(t).generate(req, None, 1)
    assert exc.value.reason == "oom" and not exc.value.retryable and exc.value.gpu_seconds == 0.0  # an old failure: its GPU seconds were metered when it happened
    assert t.log == []


async def test_a_retryable_failure_of_an_earlier_attempt_is_cleared_and_the_job_runs_again(worker_world):
    t, worker = worker_world
    req = make_request()
    t.put_json(req.job_id, "result.json", result_doc(req.job_id, state="failed", error={"code": "timeout", "message": "hung", "retryable": True}))
    t.put_json(req.job_id, "status.json", {"state": "failed"})
    res = await client_for(t).generate(req, None, 5)
    assert not res.cached and res.gpu_seconds == 42.0 and worker.jobs == [req.job_id]
    assert t.log[:2] == ["delete:result.json", "delete:status.json"]  # contract §8.5


@pytest.mark.parametrize(("code", "reason"), [("oom", "oom"), ("timeout", "timeout"), ("internal", "internal")])
async def test_a_failure_during_this_call_carries_its_reason_and_the_gpu_seconds_it_cost(code, reason):
    t = MemoryTransport()
    FakeGpuWorker(t, fail={"code": code, "message": "it broke", "retryable": code != "oom"}, gpu=41.8)
    with pytest.raises(MotionFailed) as exc:
        await client_for(t).generate(make_request(), None, 5)
    assert exc.value.reason == reason and exc.value.worker_code == code and exc.value.gpu_seconds == 41.8 and exc.value.retryable == (code != "oom")
    assert exc.value.params["detail"] == f"{code}: it broke"


async def test_a_bad_request_result_is_a_bad_request_error_not_a_model_failure():
    t = MemoryTransport()
    FakeGpuWorker(t, fail={"code": "bad_request", "message": "image_sha256 mismatch", "retryable": False})
    with pytest.raises(MotionBadRequest) as exc:
        await client_for(t).generate(make_request(), None, 5)
    assert exc.value.reason == "bad_request"


async def test_requests_the_worker_would_reject_never_reach_the_queue():
    t = MemoryTransport()
    with pytest.raises(MotionBadRequest):
        await client_for(t).generate(make_request(num_frames=30), None, 1)
    assert t.log == []


async def test_no_worker_means_a_timeout_that_says_so_and_progress_reports_the_cold_worker():
    clock, t = timed()
    seen = []

    async def on_progress(p):
        seen.append(p)

    with pytest.raises(MotionTimeout) as exc:
        await client_for(t, clock=clock).generate(make_request(), on_progress, 3)  # three polls of (manual) time: no worker answers
    assert exc.value.reason == "timeout" and exc.value.params == {"seconds": 3}
    assert len(seen) == 3 and all(p.state == "queued" for p in seen) and any(p.worker_state == "warming" for p in seen)  # our own message is waiting in the queue: the worker is being woken


async def test_a_message_nobody_picked_up_is_sent_again_after_the_requeue_delay_but_not_while_a_worker_is_alive():
    clock, t = timed()
    with pytest.raises(MotionTimeout):
        await client_for(t, clock=clock, requeue_after_s=2).generate(make_request(), None, 6)
    jobs = [m for m in t.queue if m["type"] == "generate"]
    assert len(jobs) >= 2 and len({m["job_id"] for m in jobs}) == 1  # the same deterministic job: the worker's idempotency makes a duplicate harmless
    busy_clock, busy = timed()  # a worker is up (loading its model, or busy with another job): the message is not lost, it is just waiting its turn
    busy.put_json("_worker", "ready.json", {"v": 1, "state": "loading", "replica": "r", "model": "m", "model_revision": "x", "vram_gib": 0, "started_at": wire.utc_iso(), "updated_at": wire.utc_iso()})
    with pytest.raises(MotionTimeout):
        await client_for(busy, clock=busy_clock, requeue_after_s=2).generate(make_request(), None, 6)
    assert len([m for m in busy.queue if m["type"] == "generate"]) == 1


async def test_a_running_job_whose_status_stops_advancing_is_a_stall():
    clock, t = timed()
    FakeGpuWorker(t, stall=True)
    with pytest.raises(MotionTimeout) as exc:
        await client_for(t, clock=clock, stall_after_s=3).generate(make_request(), None, 100)  # a stall is seen after 3 (manual) seconds, long before the time limit
    assert "stopped reporting progress" in exc.value.message and exc.value.reason == "timeout" and exc.value.params["seconds"] >= 3


async def test_a_storage_blip_is_tolerated_but_a_dead_storage_is_not(worker_world):
    t, _ = worker_world
    t.blip_after_enqueue = 4  # fewer than the tolerated number of consecutive polling errors
    res = await client_for(t).generate(make_request(), None, 5)
    assert res.gpu_seconds == 42.0
    dead = MemoryTransport()
    dead.blip_after_enqueue = 10**6
    with pytest.raises(MotionTransportError) as exc:
        await client_for(dead).generate(make_request(), None, 5)
    assert "stopped answering" in exc.value.message
    unreadable = MemoryTransport()
    unreadable.read_failures = 1  # the very first read (the cache check) fails: nothing was queued yet
    with pytest.raises(MotionTransportError):
        await client_for(unreadable).generate(make_request(), None, 1)
    assert unreadable.log == []


async def test_an_unreachable_queue_is_a_transport_error_with_a_worker_unavailable_reason():
    t = MemoryTransport()
    t.enqueue_error = ConnectionError("no route to queue")
    with pytest.raises(MotionTransportError) as exc:
        await client_for(t).generate(make_request(), None, 1)
    assert exc.value.reason == "worker_unavailable" and "no route to queue" in exc.value.params["detail"]
    with pytest.raises(MotionTransportError):
        await client_for(t).warmup()


async def test_worker_state_is_cold_warming_or_ready_by_the_contract_rule():
    t = MemoryTransport()
    client = client_for(t)

    async def state() -> str:
        client._status_cache = None
        return (await client.status()).state

    assert await state() == "cold"  # nothing there
    t.put_json("_worker", "ready.json", {"v": 1, "state": "loading", "replica": "r", "model": "m", "model_revision": "x", "vram_gib": 0, "started_at": wire.utc_iso(), "updated_at": wire.utc_iso()})
    assert await state() == "warming"
    t.put_json("_worker", "ready.json", {"v": 1, "state": "ready", "replica": "r", "model": "m", "model_revision": "x", "vram_gib": 22.6, "started_at": wire.utc_iso(), "updated_at": wire.utc_iso()})
    st = await client.status()
    assert st.state == "ready" and st.age_s is not None and st.age_s < 5 and st.queue_depth == 0
    t.put_json("_worker", "ready.json", {"v": 1, "state": "ready", "replica": "r", "model": "m", "model_revision": "x", "vram_gib": 22.6, "started_at": stamp(0), "updated_at": "2020-01-01T00:00:00Z"})
    assert await state() == "cold"  # a stale heartbeat: the replica is gone
    t.queue.append({"v": 1, "type": "generate", "job_id": "mj_" + "0" * 24})
    assert await state() == "warming"  # a message is waiting for a worker that is not there yet
    assert (await client.status()).queue_depth == 1


async def test_status_never_raises_and_a_missing_queue_read_permission_only_costs_the_pending_hint():
    t = MemoryTransport()
    t.read_failures = 1
    st = await client_for(t).status()
    assert st.state == "cold" and "OSError" in (st.error or "")
    t2 = MemoryTransport()
    t2.depth_error = PermissionError("AuthorizationPermissionMismatch")  # the identity cannot read the queue length
    client = client_for(t2)
    assert (await client.status()).error is None and (await client.status()).state == "cold"
    await client.warmup()  # it still wakes the worker, and remembers that it did
    assert (await client.status()).state == "warming"


async def test_warmup_sends_one_message_only_while_the_worker_is_cold_and_is_idempotent():
    t = MemoryTransport()
    client = client_for(t)
    first = await client.warmup()
    assert first.requested and first.state == "warming" and len(t.queue) == 1
    assert t.queue[0]["type"] == "warmup" and re.fullmatch(r"mw_[0-9a-f]{32}", t.queue[0]["job_id"]) and t.queue[0]["v"] == 1
    second = await client.warmup()
    assert not second.requested and len(t.queue) == 1  # already warming: no second message
    ready = MemoryTransport()
    ready.put_json("_worker", "ready.json", {"v": 1, "state": "ready", "replica": "r", "model": "m", "model_revision": "x", "vram_gib": 1, "started_at": stamp(0), "updated_at": wire.utc_iso()})
    done = await client_for(ready).warmup()
    assert done.state == "ready" and not done.requested and ready.queue == []


async def test_the_request_document_the_studio_writes_satisfies_the_contract_schema(worker_world):
    schema_path = ROOT / "contracts" / "motion-v1.schema.json"
    if not schema_path.is_file():
        pytest.skip("contracts/ is not part of this checkout")
    t, _ = worker_world
    req = make_request(width=1024, height=576, num_frames=93)
    await client_for(t).generate(req, None, 5)
    defs = json.loads(schema_path.read_text(encoding="utf-8"))["$defs"]
    doc = json.loads(t.inputs[(req.job_id, "request.json")][0])
    assert check_schema(defs, defs["request"], doc) == []
    assert check_schema(defs, defs["queueMessage"]["oneOf"][0], {"v": 1, "type": "generate", "job_id": req.job_id}) == []
    assert check_schema(defs, defs["request"], {**doc, "num_frames": 94}) != []  # the checker really checks


def check_schema(defs: dict[str, Any], schema: dict[str, Any], value: Any, path: str = "$") -> list[str]:
    """A small JSON-Schema subset checker (type, const, enum, pattern, minimum/maximum, multipleOf, lengths, required, properties, additionalProperties, $ref) — enough to hold the
    documents we write against ``contracts/motion-v1.schema.json`` without a new dependency."""
    if "$ref" in schema:
        return check_schema(defs, defs[schema["$ref"].rsplit("/", 1)[1]], value, path)
    errs: list[str] = []
    kinds = {"string": str, "integer": int, "number": (int, float), "object": dict, "boolean": bool, "null": type(None)}
    want = schema.get("type")
    if want:
        allowed = want if isinstance(want, list) else [want]
        if not any(isinstance(value, kinds[k]) and not (k in {"integer", "number"} and isinstance(value, bool)) for k in allowed):
            return [f"{path}: expected {want}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errs.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not in enum")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{path}: {value!r} does not match {schema['pattern']}")
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 10**9):
            errs.append(f"{path}: length {len(value)} out of range")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
            errs.append(f"{path}: {value} out of range")
        if "multipleOf" in schema and value % schema["multipleOf"]:
            errs.append(f"{path}: {value} is not a multiple of {schema['multipleOf']}")
    if isinstance(value, dict):
        errs += [f"{path}.{k}: required" for k in schema.get("required", []) if k not in value]
        for k, v in value.items():
            if k in schema.get("properties", {}):
                errs += check_schema(defs, schema["properties"][k], v, f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}.{k}: unexpected property")
    return errs


# ------------------------------------------------------------------------------------------------ the Azure transport (Queue + Blob, Entra) against in-memory fakes


class FakeStream:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def readall(self) -> bytes:
        return self._data


class FakeBlob:
    def __init__(self, store: dict[tuple[str, str], tuple[bytes, str | None]], key: tuple[str, str]) -> None:
        self.store, self.key = store, key

    async def upload_blob(self, data: bytes, overwrite: bool = False, content_settings: Any = None, **_: Any) -> None:
        assert overwrite is True  # the deterministic job prefix is rewritten on a retry
        self.store[self.key] = (bytes(data), getattr(content_settings, "content_type", None))

    async def download_blob(self) -> FakeStream:
        if self.key not in self.store:
            raise ResourceNotFoundError("BlobNotFound")
        return FakeStream(self.store[self.key][0])

    async def delete_blob(self) -> None:
        if self.key not in self.store:
            raise ResourceNotFoundError("BlobNotFound")
        del self.store[self.key]


class FakeBlobService:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], tuple[bytes, str | None]] = {}
        self.closed = False

    def get_blob_client(self, container: str, blob: str) -> FakeBlob:
        return FakeBlob(self.store, (container, blob))

    async def close(self) -> None:
        self.closed = True


class FakeQueue:
    def __init__(self) -> None:
        self.sent: list[tuple[str, int | None]] = []
        self.closed = False
        self.arrived = asyncio.Event()

    async def send_message(self, content: str, *, time_to_live: int | None = None, **_: Any) -> None:
        self.sent.append((content, time_to_live))
        self.arrived.set()

    async def get_queue_properties(self) -> Any:
        return types.SimpleNamespace(approximate_message_count=len(self.sent))

    async def close(self) -> None:
        self.closed = True


async def test_azure_transport_uses_the_contract_containers_names_content_types_and_a_ttl_on_every_message():
    blobs, queue = FakeBlobService(), FakeQueue()
    tr = AzureTransport(queue, blobs)
    await tr.put_input("mj_abc", "image.jpg", b"JPEG", "image/jpeg")
    await tr.put_input("mj_abc", "request.json", b"{}", "application/json")
    assert blobs.store == {("motion-in", "mj_abc/image.jpg"): (b"JPEG", "image/jpeg"), ("motion-in", "mj_abc/request.json"): (b"{}", "application/json")}
    assert await tr.get_output("mj_abc", "result.json") is None  # a missing blob is None, not an error
    blobs.store[("motion-out", "mj_abc/result.json")] = (b'{"v":1}', None)
    assert await tr.get_output("mj_abc", "result.json") == b'{"v":1}'
    await tr.delete_output("mj_abc", "result.json")
    await tr.delete_output("mj_abc", "result.json")  # deleting what is not there is fine
    assert await tr.get_output("mj_abc", "result.json") is None
    await tr.enqueue(wire.queue_message("generate", "mj_abc"))
    text, ttl = queue.sent[0]
    assert json.loads(text) == {"v": 1, "type": "generate", "job_id": "mj_abc"} and ttl == MESSAGE_TTL_S == 3600
    assert await tr.queue_depth() == 1
    await tr.close()
    assert blobs.closed and queue.closed
    custom = AzureTransport(queue, blobs, "in2", "out2")
    await custom.put_input("j", "x", b"1", "text/plain")
    assert ("in2", "j/x") in blobs.store


async def test_azure_client_runs_the_whole_protocol_over_queue_and_blob_fakes():
    blobs, queue = FakeBlobService(), FakeQueue()
    client = AzureMotionClient(AzureTransport(queue, blobs), poll_s=0.01)
    assert (client.name, client.model, client.revision, client.license) == ("azure", "wan2.2-ti2v-5b", REV, "Apache-2.0") and "tenant-local" in client.host
    req = make_request()

    async def worker() -> None:
        await queue.arrived.wait()
        msg = json.loads(queue.sent[-1][0])
        assert msg["job_id"] == req.job_id and ("motion-in", f"{req.job_id}/request.json") in blobs.store
        blobs.store[("motion-out", f"{req.job_id}/clip.mp4")] = (b"CLIP", "video/mp4")
        blobs.store[("motion-out", f"{req.job_id}/result.json")] = (json.dumps(result_doc(req.job_id, gpu=12.5)).encode(), None)

    task = asyncio.create_task(worker())
    res = await client.generate(req, None, 5)
    await task
    assert res.clip == b"CLIP" and res.gpu_seconds == 12.5 and not res.cached
    ws = await client.status()
    assert ws.state == "warming" and ws.queue_depth == 1  # the job message is still in the (fake) queue
    await client.close()
    assert blobs.closed and queue.closed


def test_azure_client_is_built_from_settings_with_an_entra_credential_and_the_real_sdk_clients():
    class Credential:
        async def get_token(self, *scopes: str, **kw: Any) -> Any:
            raise AssertionError("no network in unit tests")

    s = Settings(spotlight_mode="offline", motion_mode="azure", motion_queue_url="https://stx.queue.core.windows.net", motion_blob_account_url="https://stx.blob.core.windows.net", motion_queue_name="motion-jobs", motion_in_container="in", motion_out_container="out")
    client = build_client(s, Credential())
    assert isinstance(client, AzureMotionClient) and client.model == "wan2.2-ti2v-5b" and client.name == "azure"
    transport = client.transport
    assert isinstance(transport, AzureTransport) and transport._queue.queue_name == "motion-jobs" and transport._in == "in" and transport._out == "out"
    assert transport._queue.url.startswith("https://stx.queue.core.windows.net/") and transport._blobs.url.startswith("https://stx.blob.core.windows.net")
    asyncio.run(client.close())


# ------------------------------------------------------------------------------------------------ the local-directory transport against a worker thread


class LocalFakeWorker(threading.Thread):
    """The worker side of the local-dir protocol (contracts/README.md §9) with the procedural animator as its 'model'.

    It is driven by events, not by a clock. ``loading=True`` keeps the model "loading" until the test calls ``load()``; ``hold_jobs=True`` lets a job get as far as
    ``status.json: running`` and finish only after ``release_jobs()``. Like the real worker's beacon, one loop pass decides ONCE what it advertises and acts on exactly
    that: ``ready.json`` says ``ready`` (written first) before a message is ever claimed, and while it says ``loading`` nothing is claimed. A status read can therefore never
    contradict what the worker is doing, however the threads happen to be scheduled."""

    def __init__(self, root: Path, *, loading: bool = False, hold_jobs: bool = False, fail: bool = False) -> None:
        super().__init__(daemon=True)
        self.root, self.fail = root, fail
        self.stop_flag = threading.Event()
        self._loaded = threading.Event()
        self._go = threading.Event()
        if not loading:
            self._loaded.set()
        if not hold_jobs:
            self._go.set()
        self.jobs: list[str] = []
        self.warmups = 0

    def load(self) -> None:
        self._loaded.set()

    def release_jobs(self) -> None:
        self._go.set()

    def stop(self) -> None:
        self.stop_flag.set()
        self._go.set()  # never leave a held job behind
        self.join(10)

    def _write(self, rel: str, data: bytes) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def _advertise(self, state: str) -> None:
        self._write("motion-out/_worker/ready.json", json.dumps({"v": 1, "state": state, "replica": "local", "model": "wan2.2-ti2v-5b", "model_revision": REV, "vram_gib": 0.0, "started_at": wire.utc_iso(), "updated_at": wire.utc_iso()}).encode())

    def run(self) -> None:
        queue = self.root / "queue"
        while not self.stop_flag.is_set():
            ready = self._loaded.is_set()  # one read per pass: what is advertised is what is done
            self._advertise("ready" if ready else "loading")
            if ready:
                for path in sorted(queue.glob("*.json")):
                    claimed = path.with_suffix(".claimed")
                    try:
                        os.rename(path, claimed)
                    except FileNotFoundError:
                        continue
                    msg = json.loads(claimed.read_text())
                    if msg["type"] == "generate":
                        self._generate(msg["job_id"])
                    else:
                        self.warmups += 1
                    claimed.unlink()
            self.stop_flag.wait(0.02)  # the pace of the loop; nothing is ever decided by it

    def _generate(self, job_id: str) -> None:
        req = json.loads((self.root / "motion-in" / job_id / "request.json").read_text())
        image = (self.root / "motion-in" / job_id / req["image"]).read_bytes()
        assert hashlib.sha256(image).hexdigest() == req["image_sha256"]
        self.jobs.append(job_id)
        self._write(f"motion-out/{job_id}/status.json", json.dumps({"v": 1, "job_id": job_id, "state": "running", "progress": 0.5, "step": 10, "steps": req["steps"], "message": "denoising", "replica": "local", "updated_at": wire.utc_iso()}).encode())
        self._go.wait(30)  # a held job finishes only once the test has seen it running
        t0 = time.monotonic()
        if self.fail:
            doc = result_doc(job_id, state="failed", gpu=1.5, error={"code": "internal", "message": "fake failure", "retryable": False})
        else:
            clip = animator.animate(image, req["width"], req["height"], req["num_frames"], req["fps"], req["seed"])
            self._write(f"motion-out/{job_id}/clip.mp4", clip)
            doc = result_doc(job_id, gpu=round(time.monotonic() - t0, 1), width=req["width"], height=req["height"], num_frames=req["num_frames"], seed=req["seed"])
        self._write(f"motion-out/{job_id}/result.json", json.dumps(doc).encode())


@pytest.fixture
def local_world(tmp_path: Path):
    workers: list[LocalFakeWorker] = []

    def start(**kw: Any) -> tuple[LocalMotionClient, LocalFakeWorker]:
        w = LocalFakeWorker(tmp_path, **kw)
        w.start()
        workers.append(w)
        return LocalMotionClient(tmp_path, poll_s=0.01, status_ttl_s=0), w

    yield tmp_path, start
    for w in workers:
        w.stop()


async def test_local_dir_round_trip_with_a_worker_thread_including_cold_start_and_the_cache(local_world):
    root, start = local_world
    client, worker = start(loading=True, hold_jobs=True)  # the model is still loading, and a job only finishes after the client has seen it run
    assert (await client.status()).state in {"warming", "cold"}  # no heartbeat written yet (cold) or "loading" (warming): never ready
    warm = await client.warmup()
    assert warm.state == "warming" or not warm.requested
    req = make_request()
    seen: list[str] = []

    async def on_progress(p):
        seen.append(p.state)
        if p.state == "queued":
            worker.load()  # the job waits in the queue while the worker loads: now the model is there
        elif p.state == "running":
            worker.release_jobs()  # the client has seen the job run: it may finish

    res = await client.generate(req, on_progress, 30)
    assert res.clip[4:8] == b"ftyp" and (res.width, res.height, res.num_frames) == (320, 256, 29) and not res.cached and res.provider == "local" and worker.jobs == [req.job_id]
    assert seen[0] == "queued" and "running" in seen  # in that order: nothing can run while the worker is loading
    assert (root / "motion-in" / req.job_id / "image.jpg").read_bytes() == req.image and (root / "motion-out" / req.job_id / "clip.mp4").is_file()
    assert [p.name for p in (root / "queue").iterdir() if p.suffix == ".json"] == []  # every message was claimed (the claim marker of the last one may not be deleted yet)
    again = await client.generate(req, None, 5)
    assert again.cached and again.gpu_seconds == 0.0 and worker.jobs == [req.job_id]
    assert (await client.status()).state == "ready"  # the worker advertised "ready" before it claimed anything, and says so from then on


async def test_local_dir_failed_result_is_reported_with_its_reason(local_world):
    _, start = local_world
    client, _worker = start(fail=True)
    with pytest.raises(MotionFailed) as exc:
        await client.generate(make_request(), None, 30)
    assert exc.value.reason == "internal" and exc.value.gpu_seconds == 1.5


async def test_local_transport_writes_atomically_names_messages_fifo_and_rejects_path_tricks(tmp_path: Path):
    tr = LocalTransport(tmp_path)
    await tr.enqueue({"v": 1, "type": "warmup", "job_id": "mw_" + "0" * 32})
    await tr.enqueue({"v": 1, "type": "generate", "job_id": "mj_" + "1" * 24})
    names = sorted(p.name for p in (tmp_path / "queue").iterdir())
    assert len(names) == 2 and all(re.fullmatch(r"\d{20}-[0-9a-f]{32}\.json", n) for n in names) and names == sorted(names)
    assert json.loads((tmp_path / "queue" / names[0]).read_text())["type"] == "warmup"  # FIFO by name
    assert await tr.queue_depth() == 2
    (tmp_path / "queue" / names[0]).rename(tmp_path / "queue" / names[0].replace(".json", ".claimed"))
    assert await tr.queue_depth() == 2  # in-flight messages count too (like Azure's approximate message count)
    await tr.put_input("mj_x", "image.jpg", b"1", "image/jpeg")
    assert (tmp_path / "motion-in" / "mj_x" / "image.jpg").read_bytes() == b"1"
    assert not await asyncio.to_thread(lambda: list(tmp_path.rglob("*.tmp")))
    assert await tr.get_output("mj_x", "nothing.json") is None
    for bad in ("../x", "a/b", "..", ""):
        with pytest.raises(ValueError):
            await tr.put_input("mj_x", bad, b"x", "text/plain")


# ------------------------------------------------------------------------------------------------ choosing a backend


async def test_the_backend_follows_the_settings_and_every_mode_has_the_same_surface(tmp_path: Path):
    stub = build_client(Settings(spotlight_mode="offline"))
    assert isinstance(stub, StubMotionClient) and stub.name == "stub"
    local = build_client(Settings(spotlight_mode="offline", motion_mode="local", motion_local_dir=str(tmp_path / "d")))
    assert isinstance(local, LocalMotionClient) and local.name == "local" and (tmp_path / "d" / "queue").is_dir()
    off = build_client(Settings(spotlight_mode="offline", motion_mode="off"))
    assert isinstance(off, OffMotionClient) and off.name == "off" and off.capabilities()["configured"] is False
    st = await off.status()
    assert (st.state, st.queue_depth) == ("cold", 0) and (await off.warmup()).state == "cold"
    with pytest.raises(MotionUnavailable) as exc:
        await off.generate(make_request())
    assert exc.value.reason == "disabled" and exc.value.status == 503 and exc.value.code == "motion_unavailable"
    for c in (stub, local, off):
        assert {"name", "model", "revision", "license", "host"} <= set(dir(c)) and c.capabilities()
        await c.close()
    assert Image.open(io.BytesIO(jpeg())).size == (320, 256)
