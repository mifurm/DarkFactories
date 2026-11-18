"""Entry points: ``python -m motion_worker`` (in-process and as a real subprocess incl. SIGTERM) and the submit tool."""

from __future__ import annotations

import io
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from motion_worker import __main__ as entry
from motion_worker import contract, submit
from motion_worker.logs import LOG, JsonFormatter, configure_logging, event, exception_event
from motion_worker.transport import OUT, LocalTransport

from .conftest import keyframe_bytes, submit_job, wait_until

PROJECT = Path(__file__).resolve().parents[1]


def worker_env(bus: Path, **extra: str) -> dict[str, str]:
    return {
        "MOTION_PIPELINE": "fake",
        "MOTION_TRANSPORT": "local",
        "MOTION_LOCAL_DIR": str(bus),
        "MOTION_WORK_DIR": str(bus.parent / "work"),
        "MOTION_POLL_INTERVAL_S": "0.05",
        "MOTION_READY_INTERVAL_S": "0.2",
        "MOTION_REPLICA": "subprocess-replica",
        **extra,
    }


@pytest.fixture
def restore_process_state():
    handlers = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    saved = (LOG.handlers[:], LOG.level, LOG.propagate)
    yield
    for sig, handler in handlers.items():
        signal.signal(sig, handler)
    LOG.handlers[:], LOG.level, LOG.propagate = saved[0], saved[1], saved[2]


# ---------------------------------------------------------------------------------------------- main() in-process


def test_version_and_print_config(capsys, restore_process_state):
    with pytest.raises(SystemExit) as exit_info:
        entry.main(["--version"])
    assert exit_info.value.code == 0
    assert "motion-worker 1.0.0" in capsys.readouterr().out
    assert (
        entry.main(
            ["--print-config"], env={"MOTION_TRANSPORT": "local", "MOTION_LOCAL_DIR": "/x", "MOTION_PIPELINE": "fake"}
        )
        == 0
    )
    printed = json.loads(capsys.readouterr().out)
    assert (printed["pipeline"], printed["transport"], printed["queue_name"]) == ("fake", "local", "motion-jobs")


def test_configuration_errors_exit_with_code_2_and_a_readable_message(capsys, restore_process_state):
    assert entry.main([], env={"MOTION_TRANSPORT": "azure"}) == 2
    err = capsys.readouterr().err
    assert "MOTION_STORAGE_ACCOUNT_URL" in err and "MOTION_QUEUE_URL" in err


def test_initialisation_failures_exit_with_code_3(monkeypatch, tmp_path, capsys, restore_process_state):
    def boom(cfg):
        raise ImportError("No module named 'azure'")

    monkeypatch.setattr(entry, "build_transport", boom)
    assert entry.main([], env=worker_env(tmp_path / "bus")) == 3
    assert "worker_init_failed" in capsys.readouterr().out


@pytest.mark.ffmpeg
def test_main_runs_a_job_in_process_with_the_fake_pipeline(tmp_path, capsys, restore_process_state):
    bus = tmp_path / "bus"
    transport = LocalTransport(bus)
    job = submit_job(transport)["job_id"]
    code = entry.main([], env=worker_env(bus, MOTION_EXIT_WHEN_IDLE_S="0.3"))
    assert code == 0
    result = json.loads(transport.read_blob(OUT, f"{job}/result.json"))
    assert result["state"] == "succeeded"
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    events = [line["event"] for line in lines]
    assert events[0] == "worker_start" and events[-1] == "worker_stopped"
    done = next(line for line in lines if line["event"] == "job_done")
    assert done["job_id"] == job and done["shot_id"] == "s1" and done["state"] == "succeeded" and "gpu_seconds" in done


# ---------------------------------------------------------------------------------------------- real subprocess


@pytest.mark.ffmpeg
def test_python_m_motion_worker_starts_serves_a_job_and_exits_when_idle(tmp_path):
    bus = tmp_path / "bus"
    transport = LocalTransport(bus)
    job = submit_job(transport, width=320, height=256, num_frames=25)["job_id"]
    proc = subprocess.run(
        [sys.executable, "-m", "motion_worker"],
        cwd=PROJECT,
        env={**os.environ, **worker_env(bus, MOTION_EXIT_WHEN_IDLE_S="1")},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert [line["event"] for line in lines if line["event"] in ("worker_start", "job_done", "worker_stopped")] == [
        "worker_start",
        "job_done",
        "worker_stopped",
    ]
    assert json.loads(transport.read_blob(OUT, f"{job}/result.json"))["state"] == "succeeded"
    assert transport.read_blob(OUT, "_worker/ready.json") is None
    assert transport.queue_depth() == 0


def test_a_real_sigterm_stops_the_idle_worker_gracefully(tmp_path):
    bus = tmp_path / "bus"
    transport = LocalTransport(bus)
    proc = subprocess.Popen(
        [sys.executable, "-m", "motion_worker"],
        cwd=PROJECT,
        env={**os.environ, **worker_env(bus)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_until(lambda: (transport.read_blob(OUT, "_worker/ready.json") or b"").find(b'"ready"') > 0, 20)
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=20)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0, err
    stopped = [json.loads(line) for line in out.splitlines() if '"worker_stopped"' in line][0]
    assert stopped["reason"] == "SIGTERM" and stopped["exit_code"] == 0
    assert transport.read_blob(OUT, "_worker/ready.json") is None


def test_importing_the_worker_does_not_import_the_gpu_or_azure_stacks():
    code = (
        "import sys, motion_worker.worker, motion_worker.__main__, motion_worker.submit, motion_worker.weights, "
        "motion_worker.pipeline, motion_worker.transport\n"
        "heavy = ['torch','diffusers','transformers','huggingface_hub','azure.identity','azure.storage.blob',"
        "'azure.storage.queue','imageio_ffmpeg']\n"
        "print([m for m in heavy if m in sys.modules])"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=PROJECT, capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "[]", out.stdout + out.stderr


# ---------------------------------------------------------------------------------------------- submit tool


@pytest.fixture
def bus_env(tmp_path, monkeypatch):
    monkeypatch.setattr(submit, "POLL_SECONDS", 0.02)
    bus = tmp_path / "bus"
    return bus, worker_env(bus), tmp_path


def image_file(tmp_path: Path, name: str = "key.jpg") -> Path:
    path = tmp_path / name
    path.write_bytes(keyframe_bytes())
    return path


def test_submit_writes_the_same_documents_the_studio_writes(bus_env, capsys):
    bus, env, tmp_path = bus_env
    code = submit.main(
        ["--image", str(image_file(tmp_path)), "--frames", "25", "--steps", "8", "--width", "512", "--height", "288",
         "--campaign", "cmp", "--shot", "s9"], env=env,
    )  # fmt: skip
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    job = out["job_id"]
    assert out["enqueued"] is True
    transport = LocalTransport(bus)
    request = json.loads(transport.read_blob("in", f"{job}/request.json"))
    parsed = contract.parse_request(request)
    assert (parsed.shot_id, parsed.campaign_id, parsed.width, parsed.height) == ("s9", "cmp", 512, 288)
    assert transport.blob_exists("in", f"{job}/image.jpg")
    msg = transport.receive(60)
    assert contract.parse_queue_message(msg.body).job_id == job


def test_submit_warmup_and_cache_hits(bus_env, capsys):
    bus, env, tmp_path = bus_env
    assert submit.main(["--warmup"], env=env) == 0
    warm = json.loads(capsys.readouterr().out)
    transport = LocalTransport(bus)
    assert contract.parse_queue_message(transport.receive(60).body).job_id == warm["job_id"]

    args = ["--image", str(image_file(tmp_path)), "--frames", "25", "--steps", "8", "--width", "256", "--height", "256"]
    assert submit.main(args, env=env) == 0
    first = json.loads(capsys.readouterr().out)
    transport.write_blob(OUT, f"{first['job_id']}/result.json", b'{"state":"succeeded"}')
    transport.receive(60)  # drain the first message
    assert submit.main(args, env=env) == 0
    second = json.loads(capsys.readouterr().out)
    assert (second["job_id"], second["enqueued"], second["cached"]) == (first["job_id"], False, True)
    assert transport.receive(60) is None, "a cached job is not enqueued a second time"


@pytest.mark.ffmpeg
def test_submit_wait_returns_the_result_and_saves_the_clip(harness, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(submit, "POLL_SECONDS", 0.02)
    h = harness()
    h.start()
    env = worker_env(h.cfg.local_dir)
    out_path = tmp_path / "clip.mp4"
    code = submit.main(
        ["--image", str(image_file(tmp_path)), "--frames", "25", "--steps", "8", "--width", "256", "--height", "256",
         "--wait", "30", "--out", str(out_path)], env=env,
    )  # fmt: skip
    assert code == 0
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert printed[-1]["state"] == "succeeded"
    assert out_path.read_bytes()[4:8] == b"ftyp"
    code = submit.main(
        ["--image", str(image_file(tmp_path)), "--frames", "25", "--steps", "8", "--width", "256", "--height", "256",
         "--prompt", "boom [fake:oom]", "--wait", "30"], env=env,
    )  # fmt: skip
    assert code == 1, "a failed job gives a non-zero exit code"
    h.stop()


def test_submit_wait_times_out_without_a_worker(bus_env, capsys):
    bus, env, tmp_path = bus_env
    code = submit.main(["--image", str(image_file(tmp_path)), "--frames", "25", "--steps", "8", "--width", "256",
                        "--height", "256", "--wait", "0.2"], env=env)  # fmt: skip
    assert code == 1
    assert "timeout-waiting" in capsys.readouterr().out


def test_submit_input_errors(bus_env, capsys):
    bus, env, tmp_path = bus_env
    assert submit.main(["--image", str(image_file(tmp_path)), "--frames", "50"], env=env) == 2
    assert "invalid request" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        submit.main([], env=env)
    bad = tmp_path / "frame.gif"
    bad.write_bytes(b"GIF89a")
    with pytest.raises(SystemExit):
        submit.main(["--image", str(bad)], env=env)
    assert submit.main(["--warmup"], env={"MOTION_TRANSPORT": "local"}) == 2


# ---------------------------------------------------------------------------------------------- logging


def test_logs_are_one_json_object_per_line_with_structured_fields():
    stream = io.StringIO()
    configure_logging("INFO", stream)
    event("job_done", job_id="mj_x", shot_id="s1", gpu_seconds=74.2, name="a field called name", ts="not overwritten")
    event("hidden", logging.DEBUG, secret_detail=1)
    event("warn", logging.WARNING, state="failed")
    try:
        raise ValueError("boom")
    except ValueError:
        exception_event("handler_error", job_id="mj_y")
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [line["event"] for line in lines] == ["job_done", "warn", "handler_error"], "DEBUG is filtered at INFO"
    first = lines[0]
    assert first["level"] == "INFO" and first["logger"] == "motion_worker" and first["gpu_seconds"] == 74.2
    assert first["name"] == "a field called name" and first["ts"].endswith("Z") and first["ts"] != "not overwritten"
    assert lines[1]["level"] == "WARNING"
    assert "ValueError: boom" in lines[2]["exc"]
    configure_logging("DEBUG", stream)  # idempotent: no duplicate handlers
    assert len(LOG.handlers) == 1
    assert isinstance(LOG.handlers[0].formatter, JsonFormatter)
    configure_logging("nonsense-level", stream)
    assert LOG.level == logging.INFO
    time.sleep(0)  # (keeps the module's `time` import honest for readers of the timing tests)
