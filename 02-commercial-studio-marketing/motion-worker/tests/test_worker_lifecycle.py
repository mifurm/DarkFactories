"""Process lifecycle: ready beacon, graceful shutdown, abort/release, watchdog, queue outages, weights integration."""

from __future__ import annotations

import json
import os
import signal
import threading
import time

import pytest

from motion_worker import contract
from motion_worker.errors import InternalError
from motion_worker.transport import MODELS, OUT
from motion_worker.worker import install_signal_handlers

from .conftest import Harness, read_json, wait_until
from .helpers import CountingPipeline, FakeHf, FlakyReceive, WeightsPipeline, expected_downloaded


def ready_doc(h: Harness) -> dict | None:
    raw = h.transport.read_blob(OUT, "_worker/ready.json")
    return json.loads(raw) if raw else None


def ready_state(h: Harness) -> str | None:
    doc = ready_doc(h)
    return doc["state"] if doc else None


# ---------------------------------------------------------------------------------------------- ready beacon


def test_ready_json_goes_loading_then_ready_is_refreshed_and_removed_on_shutdown(harness, validate):
    h = harness(pipeline=CountingPipeline(load_delay_s=0.4))
    h.start()
    first = wait_until(lambda: ready_doc(h))
    validate("ready", first)
    assert first["state"] == "loading", "published at start-up, before the model is loaded"
    wait_until(lambda: ready_state(h) == "ready")
    doc = ready_doc(h)
    validate("ready", doc)
    assert (doc["replica"], doc["model"], doc["model_revision"]) == ("test-replica", "wan2.2-ti2v-5b", "fake")
    assert doc["started_at"] <= doc["updated_at"]
    seen = len(h.transport.written("ready.json"))
    wait_until(lambda: len(h.transport.written("ready.json")) >= seen + 3)  # refreshed on its own interval
    h.stop()
    assert h.exit_code == 0
    assert ready_doc(h) is None, "a stale 'ready' must not outlive the replica"


def test_a_successor_replicas_ready_json_is_never_deleted_by_the_old_one(harness):
    h = harness()
    h.start()
    wait_until(lambda: ready_state(h) == "ready")
    foreign = {**ready_doc(h), "replica": "replica-two"}
    h.worker.beacon._task.stop()  # stop our refreshes so the foreign document is not overwritten
    h.transport.write_blob(OUT, "_worker/ready.json", json.dumps(foreign).encode())
    h.stop()
    assert ready_doc(h)["replica"] == "replica-two"


def test_ready_json_keeps_refreshing_while_a_job_is_running(harness):
    h = harness(pipeline=CountingPipeline(step_delay_s=0.05))
    h.start()
    wait_until(lambda: ready_state(h) == "ready")
    req = h.submit(steps=10)
    job = req["job_id"]
    wait_until(lambda: h.transport.blob_exists(OUT, f"{job}/status.json"))
    before = len(h.transport.written("ready.json"))
    h.wait_result(job)
    assert len(h.transport.written("ready.json")) - before >= 3, "Studio must not see 'cold' during a long generation"
    h.stop()


def test_the_loop_serves_jobs_as_they_arrive_one_at_a_time(harness):
    pipe = CountingPipeline(step_delay_s=0.01)
    h = harness(pipeline=pipe)
    h.start()
    jobs = [h.submit(seed=seed)["job_id"] for seed in (1, 2, 3)]
    for job in jobs:
        assert h.wait_result(job)["state"] == "succeeded"
    assert h.transport.queue_depth() == 0
    h.stop()
    assert pipe.generated == 3
    assert pipe.max_active == 1, "only one job may run at a time (one GPU)"


def test_drain_mode_exits_after_the_queue_has_been_idle(harness):
    h = harness(exit_when_idle_s=0.15)
    jobs = [h.submit(seed=seed)["job_id"] for seed in (1, 2)]
    started = time.monotonic()
    assert h.worker.run() == 0
    assert time.monotonic() - started < 10
    assert all(h.result(job)["state"] == "succeeded" for job in jobs)
    assert ready_doc(h) is None and h.transport.queue_depth() == 0


# ---------------------------------------------------------------------------------------------- graceful shutdown


def test_shutdown_lets_the_current_job_finish_and_takes_no_new_one(harness):
    pipe = CountingPipeline(step_delay_s=0.01)
    h = harness(pipeline=pipe)
    first = h.submit(seed=1)["job_id"]
    second = h.submit(seed=2)["job_id"]
    pipe.on_generate = lambda request: h.worker.request_shutdown("SIGTERM")  # SIGTERM arrives mid-job
    h.start()
    assert h.wait_result(first)["state"] == "succeeded", "the in-flight job finishes within the grace period"
    h._thread.join(15)
    assert h.exit_code == 0
    assert pipe.generated == 1
    assert not h.transport.blob_exists(OUT, f"{second}/result.json")
    assert h.transport.queue_depth() == 1, "the second job stays queued for the next replica"
    assert ready_doc(h) is None


def test_when_the_grace_period_is_exhausted_the_job_is_aborted_and_the_message_released(harness):
    pipe = CountingPipeline(step_delay_s=0.02)
    h = harness(pipeline=pipe, shutdown_grace_s=0.0, shutdown_margin_s=0.0)
    req = h.submit(steps=20)
    job = req["job_id"]
    pipe.after_step = lambda step: h.worker.request_shutdown("SIGTERM") if step == 3 else None
    h.start()
    h._thread.join(15)
    assert h.exit_code == 0
    assert not h.transport.blob_exists(OUT, f"{job}/result.json"), (
        "no terminal result: the job must be re-run elsewhere"
    )
    assert not h.transport.blob_exists(OUT, f"{job}/clip.mp4")
    assert h.transport.queue_depth() == 1
    again = h.transport.receive(600)
    assert again.dequeue_count == 2, "released (visible immediately), not deleted"
    assert contract.parse_queue_message(again.body).job_id == job
    status = read_json(h.transport, OUT, f"{job}/status.json")
    assert status["state"] == "running", "an aborted job never reports failure"
    assert pipe.released >= 1


def test_a_message_received_after_shutdown_was_requested_is_released_untouched(harness):
    pipe = CountingPipeline()
    h = harness(pipeline=pipe)
    h.submit()
    h.worker.request_shutdown("SIGTERM")
    assert h.run_once() == "released"
    assert pipe.generated == 0
    assert h.transport.receive(600).dequeue_count == 2


def test_sigterm_and_sigint_handlers_request_a_graceful_stop(harness):
    previous = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        h1 = harness()
        install_signal_handlers(h1.worker)
        os.kill(os.getpid(), signal.SIGTERM)
        wait_until(lambda: h1.worker.stopping)
        assert h1.worker._shutdown_reason == "SIGTERM"

        h2 = harness()
        install_signal_handlers(h2.worker)
        os.kill(os.getpid(), signal.SIGINT)
        wait_until(lambda: h2.worker.stopping)
        with pytest.raises(KeyboardInterrupt):  # a second Ctrl-C escalates
            os.kill(os.getpid(), signal.SIGINT)
            time.sleep(0.2)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def test_shutdown_requested_during_start_up_exits_cleanly_without_downloading(harness):
    hf = FakeHf()
    h = harness(pipeline=WeightsPipeline(), hf_download=hf)
    h.worker.request_shutdown("SIGTERM")
    assert h.worker.run() == 0
    assert hf.calls == [] and h.pipeline.loads == []
    assert ready_doc(h) is None


def test_sigterm_during_the_weights_download_skips_the_gpu_load_and_never_goes_ready(harness):
    hf = FakeHf()
    pipe = WeightsPipeline()
    h = harness(pipeline=pipe, hf_download=hf)
    hf.on_call = lambda: h.worker.request_shutdown("SIGTERM")  # the signal lands while files are downloading
    assert h.worker.run() == 0
    assert len(hf.calls) == 1 and pipe.loads == [], "22 GiB must not be loaded just to exit"
    assert "ready" not in [d["state"] for d in h.transport.written("ready.json")]
    assert ready_doc(h) is None


def test_sigterm_during_the_gpu_load_never_publishes_ready(harness):
    pipe = CountingPipeline(load_delay_s=0.3)
    h = harness(pipeline=pipe)
    h.start()
    wait_until(lambda: ready_state(h) == "loading")
    h.worker.request_shutdown("SIGTERM")
    h._thread.join(15)
    assert h.exit_code == 0
    assert "ready" not in [d["state"] for d in h.transport.written("ready.json")]


# ---------------------------------------------------------------------------------------------- watchdog


def test_a_hung_job_is_failed_by_the_watchdog_and_the_replica_is_restarted(harness, validate):
    pipe = CountingPipeline()
    pipe.block = threading.Event()  # a GPU call that never returns
    h = harness(pipeline=pipe, job_timeout_s=0.1, watchdog_grace_s=0.1)
    req = h.submit()
    job = req["job_id"]
    runner = threading.Thread(target=h.run_once, daemon=True)
    runner.start()
    wait_until(lambda: h.exits, 10)
    assert h.exits == [70], "exit_fn (os._exit in production) is invoked exactly once"
    result = h.result(job)
    validate("result", result)
    assert result["state"] == "failed" and result["error"]["code"] == "timeout" and result["error"]["retryable"] is True
    assert h.transport.queue_depth() == 0
    pipe.block.set()  # the main thread wakes up late...
    runner.join(10)
    assert h.result(job)["state"] == "failed", "...and must not overwrite the failure"
    assert h.exits == [70]


# ---------------------------------------------------------------------------------------------- outages / fatal errors


def test_a_queue_outage_marks_the_worker_not_ready_until_the_queue_answers_again(harness):
    h = harness(transport_cls=FlakyReceive, poll_interval_s=0.01)
    h.transport.failures = 5
    h.start()
    states = lambda: [d["state"] for d in h.transport.written("ready.json")]  # noqa: E731

    def recovered() -> bool:
        s = states()
        return "loading" in s[s.index("ready") :] and s[-1] == "ready" if "ready" in s else False

    wait_until(recovered, 10)
    job = h.submit()["job_id"]
    assert h.wait_result(job)["state"] == "succeeded", "the worker kept running through the outage"
    h.stop()


def test_a_fatal_startup_error_exits_non_zero_and_cleans_up(harness):
    pipe = CountingPipeline()
    pipe.preflight_error = InternalError("CUDA is not available")
    h = harness(pipeline=pipe)
    assert h.worker.run() == 1
    assert ready_doc(h) is None and not h.cfg.work_dir.exists()


# ---------------------------------------------------------------------------------------- weights inside the worker


def prefix(h: Harness) -> str:
    return f"{h.cfg.model_id}/{h.cfg.model_revision}"


def manifest(h: Harness) -> dict | None:
    raw = h.transport.read_blob(MODELS, f"{prefix(h)}/manifest.json")
    return json.loads(raw) if raw else None


def test_first_start_downloads_from_hf_serves_and_mirrors_in_the_background(harness, validate):
    hf = FakeHf()
    pipe = WeightsPipeline()
    h = harness(pipeline=pipe, hf_download=hf, download_workers=2)
    h.start()
    wait_until(lambda: ready_state(h) == "ready")
    validate("ready", ready_doc(h))
    assert ready_doc(h)["vram_gib"] == 22.6
    assert pipe.loads == [(h.cfg.model_dir / h.cfg.model_id / h.cfg.model_revision, None)]
    job = h.submit()["job_id"]
    assert h.wait_result(job)["state"] == "succeeded", "jobs are served while the mirror upload runs"
    wait_until(lambda: manifest(h))
    assert {f["path"] for f in manifest(h)["files"]} == set(expected_downloaded())
    h.stop()
    assert h.exit_code == 0


def test_a_second_replica_cold_starts_from_the_mirror_not_from_hugging_face(harness, tmp_path):
    first = harness(pipeline=WeightsPipeline(), hf_download=FakeHf())
    first.start()
    wait_until(lambda: manifest(first))
    first.stop()

    hf2 = FakeHf()
    pipe2 = WeightsPipeline()
    second = Harness(tmp_path / "replica2", pipeline=pipe2, hf_download=hf2, local_dir=first.cfg.local_dir)
    second.start()
    wait_until(lambda: ready_state(second) == "ready")
    assert hf2.calls == []
    assert pipe2.loads[0][0] == second.cfg.model_dir / second.cfg.model_id / second.cfg.model_revision
    assert {p.name for p in pipe2.loads[0][0].iterdir()} >= {"model_index.json", "transformer", "vae"}
    second.stop()


def test_a_corrupt_mirror_is_detected_at_load_time_and_rebuilt_from_hugging_face(harness, tmp_path):
    first = harness(pipeline=WeightsPipeline(), hf_download=FakeHf())
    first.start()
    wait_until(lambda: manifest(first))
    first.stop()
    key = f"{prefix(first)}/text_encoder/model.safetensors"
    first.transport.write_blob(MODELS, key, b"X" * 4000)  # corrupt, but the size still matches the manifest

    hf2 = FakeHf()
    pipe2 = WeightsPipeline()
    pipe2.fail_loads = 1  # the first load (from the mirror copy) raises
    second = Harness(tmp_path / "replica2", pipeline=pipe2, hf_download=hf2, local_dir=first.cfg.local_dir)
    second.start()
    wait_until(lambda: ready_state(second) == "ready")
    assert len(hf2.calls) == 1, "fell back to upstream exactly once"
    assert len(pipe2.loads) == 2
    wait_until(lambda: second.transport.read_blob(MODELS, key) == b"E" * 4000)  # forced re-mirror heals the blob
    second.stop()


def test_a_load_failure_of_freshly_downloaded_weights_is_fatal(harness):
    pipe = WeightsPipeline()
    pipe.fail_loads = 1
    h = harness(pipeline=pipe, hf_download=FakeHf())
    assert h.worker.run() == 1
    assert ready_doc(h) is None
    assert manifest(h) is None, "weights that fail to load are never published to the mirror"


def test_the_optional_bf16_transformer_replaces_the_fp32_shards_in_the_mirror(harness):
    pipe = WeightsPipeline()
    pipe.export_bf16 = True
    h = harness(pipeline=pipe, hf_download=FakeHf(), mirror_bf16=True)
    h.start()
    wait_until(lambda: manifest(h))
    sizes = {f["path"]: f["size"] for f in manifest(h)["files"]}
    assert sizes["transformer/diffusion_pytorch_model.safetensors"] == 321
    assert not any("00001-of-00002" in p for p in sizes)
    assert pipe.loads[0][1] == h.cfg.work_dir / "mirror-bf16"
    h.stop()


def test_mirroring_can_be_switched_off(harness):
    pipe = WeightsPipeline()
    h = harness(pipeline=pipe, hf_download=FakeHf(), mirror=False)
    h.start()
    wait_until(lambda: ready_state(h) == "ready")
    time.sleep(0.3)
    assert manifest(h) is None and pipe.loads[0][1] is None
    h.stop()
