"""Worker behaviour with the local transport and the fake pipeline (no GPU, no Azure, no network)."""

from __future__ import annotations

import json
import threading
import time

import pytest

from motion_worker import contract
from motion_worker.transport import IN, OUT
from motion_worker.worker import JobProgress, PeriodicTask

from .conftest import Harness, keyframe_bytes, read_json, sha256_hex, submit_job
from .helpers import CountingPipeline, FlakyTransport

# ---------------------------------------------------------------------------------------------- happy path


@pytest.mark.ffmpeg
def test_a_job_runs_end_to_end_and_writes_every_document_in_the_contracted_order(harness, validate):
    h = harness()
    req = h.submit(prompt="slow push-in, steam rises", width=320, height=256, num_frames=25, steps=8, seed=99)
    job = req["job_id"]
    assert h.run_once() == "succeeded"

    result = h.result(job)
    validate("result", result)
    assert result["state"] == "succeeded" and result["error"] is None and result["clip"] == "clip.mp4"
    assert (result["width"], result["height"], result["fps"], result["num_frames"], result["seed"]) == (
        320,
        256,
        24,
        25,
        99,
    )
    assert (result["model"], result["model_revision"]) == ("wan2.2-ti2v-5b", "fake")
    timings = result["timings"]
    assert result["gpu_seconds"] >= round(timings["generate_s"] + timings["encode_s"], 1) - 0.11
    assert result["gpu_seconds"] > 0 and timings["queue_wait_s"] >= 0

    clip = h.transport.read_blob(OUT, f"{job}/clip.mp4")
    assert clip[4:8] == b"ftyp" and len(clip) > 1000
    status = read_json(h.transport, OUT, f"{job}/status.json")
    validate("status", status)
    assert (status["state"], status["progress"], status["step"], status["steps"]) == ("succeeded", 1.0, 8, 8)
    assert status["replica"] == "test-replica"

    names = [n for n in h.transport.write_names() if n.startswith(job)]
    assert names[0] == f"{job}/status.json", "a status document appears as soon as the job starts"
    assert names[-2:] == [f"{job}/status.json", f"{job}/result.json"], "result.json is written last"
    assert names.index(f"{job}/clip.mp4") < len(names) - 2, "the clip is uploaded before the terminal documents"
    assert h.transport.queue_depth() == 0, "a completed message must not stay in the queue (KEDA counts messages)"
    assert not (h.cfg.work_dir / job).exists(), "scratch files are removed"


def test_progress_is_monotonic_and_observable_while_the_job_runs(harness, validate):
    h = harness(pipeline=CountingPipeline(step_delay_s=0.04))
    req = h.submit(steps=10)
    assert h.run_once() == "succeeded"
    statuses = h.transport.written(f"{req['job_id']}/status.json")
    assert len(statuses) >= 5, "the status task writes while the pipeline is busy"
    for doc in statuses:
        validate("status", doc)
    progress = [d["progress"] for d in statuses]
    assert progress == sorted(progress), progress
    steps = [d["step"] for d in statuses]
    assert steps == sorted(steps) and max(steps[:-1]) > 0
    running = [d for d in statuses if d["state"] == "running"]
    assert running and all(d["steps"] in (0, 10) for d in running)
    assert {"denoising"} <= {d["message"] for d in running}
    assert statuses[-1]["state"] == "succeeded" and statuses[-1]["progress"] == 1.0
    assert all(d["progress"] < 1.0 for d in running)


def test_visibility_is_renewed_while_generating_and_the_final_delete_uses_the_latest_receipt(harness):
    h = harness(pipeline=CountingPipeline(step_delay_s=0.04), renew_interval_s=0.05)
    h.submit(steps=10)
    msg = h.transport.receive(600)
    first_receipt = msg.receipt
    assert h.worker.process_message(msg) == "succeeded"
    assert h.transport.renewals >= 3
    assert len(set(h.transport.receipts_seen)) == h.transport.renewals, "every renewal rotates the pop receipt"
    assert msg.receipt != first_receipt
    assert h.transport.queue_depth() == 0


def test_the_job_id_check_is_soft_a_mismatching_id_still_runs(harness, caplog):
    h = harness(pipeline=CountingPipeline())
    image = keyframe_bytes()
    req = contract.build_request(prompt="p", image_name="image.jpg", image_bytes=image, width=256, height=256,
                                 num_frames=25, steps=8, seed=1)  # fmt: skip
    forged = "mj_" + "ab" * 12
    req["job_id"] = forged
    h.transport.write_blob(IN, f"{forged}/image.jpg", image)
    h.transport.write_blob(IN, f"{forged}/request.json", json.dumps(req).encode())
    h.transport.send(contract.build_queue_message(forged))
    assert h.run_once() == "succeeded"
    assert h.result(forged)["state"] == "succeeded"


# ---------------------------------------------------------------------------------------------- idempotency & poison


@pytest.mark.parametrize("existing", ["succeeded", "failed"])
def test_an_existing_result_makes_redelivery_a_no_op(harness, existing):
    pipe = CountingPipeline()
    h = harness(pipeline=pipe)
    req = h.submit()
    job = req["job_id"]
    marker = {"v": 1, "job_id": job, "state": existing, "note": "written earlier"}
    h.transport.write_blob(OUT, f"{job}/result.json", json.dumps(marker).encode())
    assert h.run_once() == "skipped"
    assert pipe.generated == 0
    assert h.result(job) == marker, "the earlier result is never overwritten"
    assert h.transport.queue_depth() == 0


def test_poison_messages_get_a_failed_result_and_are_deleted_without_running(harness, validate):
    pipe = CountingPipeline()
    h = harness(pipeline=pipe)
    req = h.submit()
    job = req["job_id"]
    for expected in (1, 2, 3):
        assert h.transport.receive(0).dequeue_count == expected  # crashed consumers: never deleted
    assert h.run_once() == "poison"  # 4th delivery > MAX_DEQUEUE (3)
    result = h.result(job)
    validate("result", result)
    assert result["state"] == "failed"
    assert result["error"]["code"] == "internal" and result["error"]["retryable"] is False
    assert "4 times" in result["error"]["message"]
    assert (result["width"], result["seed"]) == (None, None)
    assert pipe.generated == 0
    assert h.transport.queue_depth() == 0
    status = read_json(h.transport, OUT, f"{job}/status.json")
    assert status["state"] == "failed"


def test_the_third_delivery_is_still_processed(harness):
    pipe = CountingPipeline()
    h = harness(pipeline=pipe)
    h.submit()
    h.transport.receive(0)
    h.transport.receive(0)
    assert h.run_once() == "succeeded"  # dequeue_count == 3 is allowed
    assert pipe.generated == 1


def test_unparseable_messages_are_dropped(harness):
    pipe = CountingPipeline()
    h = harness(pipeline=pipe)
    h.transport.send("this is not a contract message")
    h.transport.send('{"v":1,"type":"generate","job_id":"mj_short"}')
    assert h.run_once() == "invalid"
    assert h.run_once() == "invalid"
    assert h.transport.queue_depth() == 0 and pipe.generated == 0


# ---------------------------------------------------------------------------------------------- failure mapping


def run_failing(h, **submit_overrides):
    req = h.submit(**submit_overrides)
    outcome = h.run_once()
    return req, outcome, h.result(req["job_id"])


def assert_failed(h, validate, result, code, retryable):
    validate("result", result)
    assert result["state"] == "failed" and result["clip"] is None
    assert (result["error"]["code"], result["error"]["retryable"]) == (code, retryable)
    assert result["gpu_seconds"] >= 0
    assert h.transport.queue_depth() == 0, "failed jobs are terminal: the message must be deleted"
    status = read_json(h.transport, OUT, f"{result['job_id']}/status.json")
    validate("status", status)
    assert status["state"] == "failed"


def test_cuda_oom_maps_to_oom_not_retryable_and_frees_memory(harness, validate):
    pipe = CountingPipeline()
    h = harness(pipeline=pipe)
    _, outcome, result = run_failing(h, prompt="slow push-in [fake:oom]")
    assert outcome == "failed"
    assert_failed(h, validate, result, "oom", False)
    assert "out of memory" in result["error"]["message"]
    assert (result["width"], result["num_frames"]) == (256, 25), "request echo is kept for failures after validation"
    assert pipe.released >= 1


def test_unexpected_pipeline_errors_map_to_internal_retryable(harness, validate):
    h = harness(pipeline=CountingPipeline())
    _, _, result = run_failing(h, prompt="x [fake:error]")
    assert_failed(h, validate, result, "internal", True)
    assert "RuntimeError" in result["error"]["message"]


def test_a_job_that_exceeds_its_time_limit_times_out(harness, validate):
    h = harness(pipeline=CountingPipeline(step_delay_s=0.05), job_timeout_s=0.12)
    _, _, result = run_failing(h, steps=20)
    assert_failed(h, validate, result, "timeout", True)
    assert "exceeded" in result["error"]["message"]


def test_missing_request_json_is_a_bad_request(harness, validate):
    pipe = CountingPipeline()
    h = harness(pipeline=pipe)
    job = "mj_" + "0" * 24
    h.transport.send(contract.build_queue_message(job))
    assert h.run_once() == "failed"
    result = h.result(job)
    assert_failed(h, validate, result, "bad_request", False)
    assert result["width"] is None and result["seed"] is None
    assert "request.json not found" in result["error"]["message"]
    assert pipe.generated == 0


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"mutate": {"width": 1000}}, "multiples of 32"),
        ({"mutate": {"num_frames": 26}}, "4n+1"),
        ({"mutate": {"model": "some-other-model"}}, "not served"),
        ({"mutate": {"job_id": "mj_" + "9" * 24}}, "does not match"),
        ({"mutate": {"image": "missing.jpg"}}, "not found"),
        ({"mutate": {"image_sha256": "0" * 64}}, "image_sha256"),
        ({"raw_request": b"{not json"}, "not valid JSON"),
        ({"raw_request": b'{"v":1}'}, "job_id"),
        ({"raw_request": b"x" * (300 * 1024)}, "too large"),
        ({"image_bytes": b"definitely not an image"}, "decoded"),
        ({"image_bytes": b""}, "empty"),
    ],
)
def test_invalid_inputs_fail_as_bad_request_without_touching_the_gpu(harness, validate, overrides, fragment):
    pipe = CountingPipeline()
    h = harness(pipeline=pipe)
    request = contract.build_request(
        prompt="p", image_name="image.jpg", image_bytes=overrides.get("image_bytes", keyframe_bytes()),
        width=256, height=256, num_frames=25, steps=8, seed=3,
    )  # fmt: skip
    job = request["job_id"]
    stored = {**request, **overrides.get("mutate", {})}
    h.transport.write_blob(IN, f"{job}/image.jpg", overrides.get("image_bytes", keyframe_bytes()))
    h.transport.write_blob(IN, f"{job}/request.json", overrides.get("raw_request", json.dumps(stored).encode()))
    h.transport.send(contract.build_queue_message(job))
    assert h.run_once() == "failed"
    result = h.result(job)
    assert_failed(h, validate, result, "bad_request", False)
    assert fragment in result["error"]["message"]
    assert pipe.generated == 0


def test_an_oversized_image_blob_is_rejected_before_it_is_read(harness, validate, monkeypatch):
    from motion_worker import worker as worker_mod

    monkeypatch.setattr(worker_mod, "MAX_IMAGE_BYTES", 1000)
    h = harness(pipeline=CountingPipeline())
    _, _, result = run_failing(h)
    assert_failed(h, validate, result, "bad_request", False)
    assert "too large" in result["error"]["message"]


# ---------------------------------------------------------------------------------------------- warm-up


def test_warmup_refreshes_ready_json_and_leaves_no_message_behind(harness, validate):
    pipe = CountingPipeline()
    h = harness(pipeline=pipe)
    h.transport.send(contract.build_queue_message(contract.new_warmup_id()))
    assert h.run_once() == "warmup"
    ready = read_json(h.transport, OUT, "_worker/ready.json")
    validate("ready", ready)
    assert ready["state"] == "loading", "no start-up happened in this synchronous test, so the beacon keeps its state"
    assert h.transport.queue_depth() == 0
    assert pipe.warmups == 0
    assert [p for p in (h.cfg.local_dir / "motion-out").iterdir() if p.name != "_worker"] == []


def test_warmup_generation_is_opt_in_once_only_and_never_fatal(harness):
    pipe = CountingPipeline()
    h = harness(pipeline=pipe, warmup_generate=True)
    for _ in range(2):
        h.transport.send(contract.build_queue_message(contract.new_warmup_id()))
    assert (h.run_once(), h.run_once()) == ("warmup", "warmup")
    assert pipe.warmups == 1

    broken = CountingPipeline()
    broken.fail_warmup = True
    h2 = Harness(h.cfg.work_dir.parent / "other", pipeline=broken, warmup_generate=True)
    h2.transport.send(contract.build_queue_message(contract.new_warmup_id()))
    assert h2.run_once() == "warmup"
    assert h2.transport.queue_depth() == 0


# ------------------------------------------------------------------------------------ lost messages / failing writes


def test_a_lost_message_does_not_prevent_the_result_from_being_published(harness):
    h = harness(pipeline=CountingPipeline(step_delay_s=0.03), transport_cls=FlakyTransport, renew_interval_s=0.03)
    h.transport.lose_message = True
    req = h.submit(steps=10)
    assert h.run_once() == "succeeded"
    assert h.result(req["job_id"])["state"] == "succeeded"


def test_if_result_json_cannot_be_written_the_message_stays_queued_for_redelivery(harness):
    h = harness(pipeline=CountingPipeline(), transport_cls=FlakyTransport)
    h.transport.fail_writes_ending = "result.json"
    req = h.submit()
    msg = h.transport.receive(600)
    assert h.worker.handle(msg) == "error"
    assert not h.transport.blob_exists(OUT, f"{req['job_id']}/result.json")
    assert h.transport.queue_depth() == 1, "no terminal marker => the message must not be deleted"
    # storage recovers; the message reappears and the job is simply done again
    h.transport.fail_writes_ending = None
    h.transport.release(msg)
    assert h.run_once() == "succeeded"
    assert h.transport.queue_depth() == 0


def test_unexpected_handler_errors_leave_the_message_for_later(harness):
    h = harness(pipeline=CountingPipeline(), transport_cls=FlakyTransport)
    h.submit()
    h.transport.fail_exists = True
    msg = h.transport.receive(600)
    assert h.worker.handle(msg) == "error"
    assert h.transport.queue_depth() == 1


# ---------------------------------------------------------------------------------------------- helpers


def test_job_progress_is_monotonic_and_maps_phases():
    p = JobProgress()
    p.update(progress=0.5, step=3, steps=10, message="a")
    p.update(progress=0.2, step=1, message="b")
    assert p.snapshot() == (0.5, 3, 10, "b")
    p = JobProgress()
    p.denoising(5, 10)
    assert p.snapshot()[0] == pytest.approx(0.45) and p.snapshot()[3] == "denoising"
    p.denoising(10, 10)
    assert p.snapshot() == (pytest.approx(0.85), 10, 10, "decoding frames")
    p.phase("encoding")
    assert p.snapshot()[0] == 0.93 and p.snapshot()[3] == "encoding video"
    p.phase("uploading")
    assert p.snapshot()[0] == 0.97
    p.denoising(1, 0)  # steps unknown: must not divide by zero
    assert p.snapshot()[0] == 0.97


def test_periodic_task_repeats_survives_errors_and_stops_promptly():
    calls = []

    def tick():
        calls.append(time.monotonic())
        if len(calls) == 2:
            raise RuntimeError("one bad tick")

    task = PeriodicTask("t", 0.02, tick).start()
    time.sleep(0.2)
    stopped = time.monotonic()
    task.stop()
    assert time.monotonic() - stopped < 1.0
    assert len(calls) >= 4, "an exception in one tick must not stop the heartbeat"
    count = len(calls)
    time.sleep(0.1)
    assert len(calls) == count


def test_periodic_task_can_delay_its_first_run():
    seen = []
    task = PeriodicTask("t", 0.2, lambda: seen.append(1), immediate=False).start()
    time.sleep(0.05)
    assert seen == []
    task.stop()
    assert seen == []


def test_concurrent_status_writes_and_the_final_documents_do_not_interleave_badly(harness, validate):
    """The status task stops (joins) before the terminal documents are written: nothing 'running' may follow."""
    h = harness(pipeline=CountingPipeline(step_delay_s=0.01), status_interval_s=0.01)
    req = h.submit(steps=20)
    assert h.run_once() == "succeeded"
    statuses = h.transport.written(f"{req['job_id']}/status.json")
    states = [d["state"] for d in statuses]
    assert states[-1] == "succeeded" and states.count("succeeded") == 1
    assert "running" not in states[states.index("succeeded") :]


def test_sha256_helper_matches_the_contract_hash():
    data = keyframe_bytes()
    req = contract.build_request(prompt="p", image_name="image.jpg", image_bytes=data, width=256, height=256,
                                 num_frames=25, seed=1)  # fmt: skip
    assert req["image_sha256"] == sha256_hex(data)
    assert threading.active_count() >= 1
    assert submit_job is not None
