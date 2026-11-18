"""Environment configuration."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from motion_worker.config import Config
from motion_worker.contract import MODELS
from motion_worker.errors import ConfigError

AZURE = {
    "MOTION_STORAGE_ACCOUNT_URL": "https://stdemo.blob.core.windows.net",
    "MOTION_QUEUE_URL": "https://stdemo.queue.core.windows.net",
    "AZURE_CLIENT_ID": "11111111-2222-3333-4444-555555555555",
}


def test_azure_defaults_match_the_deployment_contract():
    cfg = Config.from_env(AZURE)
    assert cfg.transport == "azure"
    assert (cfg.queue_name, cfg.in_container, cfg.out_container, cfg.models_container) == (
        "motion-jobs",
        "motion-in",
        "motion-out",
        "motion-models",
    )
    assert cfg.model_dir == Path("/tmp/models")
    assert cfg.work_dir == Path("/tmp/motion-work")
    spec = MODELS["wan2.2-ti2v-5b"]
    assert (cfg.model_id, cfg.model_repo, cfg.model_revision) == ("wan2.2-ti2v-5b", spec.repo, spec.revision)
    assert cfg.pipeline == "wan"
    assert cfg.azure_client_id == AZURE["AZURE_CLIENT_ID"]
    # contract timings
    assert cfg.visibility_timeout_s == 600
    assert cfg.renew_interval_s <= 120
    assert cfg.status_interval_s <= 3
    assert cfg.ready_interval_s == 60
    assert cfg.max_dequeue == 3
    assert cfg.shutdown_grace_s == 600


def test_local_transport_needs_a_directory_and_fake_pipeline_is_selectable():
    cfg = Config.from_env({"MOTION_TRANSPORT": "local", "MOTION_LOCAL_DIR": "/data/bus", "MOTION_PIPELINE": "fake"})
    assert cfg.local_dir == Path("/data/bus")
    assert cfg.pipeline == "fake"
    with pytest.raises(ConfigError, match="MOTION_LOCAL_DIR"):
        Config.from_env({"MOTION_TRANSPORT": "local"})


def test_all_problems_are_reported_together():
    with pytest.raises(ConfigError) as err:
        Config.from_env(
            {
                "MOTION_TRANSPORT": "carrier-pigeon",
                "MOTION_PIPELINE": "magic",
                "MOTION_JOB_TIMEOUT_S": "abc",
                "MOTION_MAX_DEQUEUE": "0",
                "MOTION_MIRROR": "maybe",
            }
        )
    message = str(err.value)
    for fragment in (
        "MOTION_TRANSPORT",
        "MOTION_PIPELINE",
        "MOTION_JOB_TIMEOUT_S",
        "MOTION_MAX_DEQUEUE",
        "MOTION_MIRROR",
    ):
        assert fragment in message


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"MOTION_QUEUE_URL": ""}, "MOTION_QUEUE_URL"),
        ({"MOTION_STORAGE_ACCOUNT_URL": "http://evil.example.com"}, "https"),
        ({"MOTION_STORAGE_ACCOUNT_URL": "not a url"}, "MOTION_STORAGE_ACCOUNT_URL"),
        ({"MOTION_RENEW_INTERVAL_S": "400"}, "MOTION_RENEW_INTERVAL_S"),
        ({"MOTION_VISIBILITY_TIMEOUT_S": "60", "MOTION_RENEW_INTERVAL_S": "50"}, "half"),
        ({"MOTION_STATUS_INTERVAL_S": "5"}, "MOTION_STATUS_INTERVAL_S"),
        ({"MOTION_READY_INTERVAL_S": "120"}, "MOTION_READY_INTERVAL_S"),
        ({"MOTION_MODEL_ID": "mystery-model"}, "MOTION_MODEL_REPO"),
    ],
)
def test_invalid_azure_configurations_are_rejected(overrides, fragment):
    with pytest.raises(ConfigError, match=fragment):
        Config.from_env({**AZURE, **overrides})


@pytest.mark.parametrize(
    "work_dir",
    ["/", "/tmp", "/var", "/tmp/models", "/tmp/models/wan", "/tmp/bus/inner", "/tmp/bus"],
)
def test_the_wiped_work_dir_must_be_a_dedicated_directory(work_dir):
    env = {"MOTION_TRANSPORT": "local", "MOTION_LOCAL_DIR": "/tmp/bus", "MOTION_WORK_DIR": work_dir}
    with pytest.raises(ConfigError, match="MOTION_WORK_DIR"):
        Config.from_env(env)
    assert Config.from_env({**env, "MOTION_WORK_DIR": "/tmp/motion-work"}).work_dir == Path("/tmp/motion-work")


def test_azurite_style_http_endpoints_are_allowed_on_localhost_only():
    env = {**AZURE, "MOTION_STORAGE_ACCOUNT_URL": "http://127.0.0.1:10000/devstoreaccount1"}
    assert Config.from_env(env).storage_account_url.startswith("http://127.0.0.1")


def test_unknown_models_work_when_repo_and_revision_are_given():
    cfg = Config.from_env(
        {**AZURE, "MOTION_MODEL_ID": "other", "MOTION_MODEL_REPO": "org/repo", "MOTION_MODEL_REVISION": "abc"}
    )
    assert (cfg.model_id, cfg.model_repo, cfg.model_revision) == ("other", "org/repo", "abc")


def test_flags_numbers_and_overrides():
    cfg = Config.from_env(
        {
            **AZURE,
            "MOTION_MIRROR": "0",
            "MOTION_MIRROR_BF16": "true",
            "MOTION_WARMUP_GENERATE": "Yes",
            "MOTION_JOB_TIMEOUT_S": "900",
            "MOTION_DOWNLOAD_WORKERS": "6",
            "MOTION_QUEUE_NAME": "q2",
            "MOTION_FFMPEG": "/usr/local/bin/ffmpeg",
            "MOTION_LOG_LEVEL": "debug",
            "MOTION_FAKE_STEP_DELAY_S": "0.5",
        }
    )
    assert (cfg.mirror, cfg.mirror_bf16, cfg.warmup_generate) == (False, True, True)
    assert (cfg.job_timeout_s, cfg.download_workers, cfg.queue_name) == (900.0, 6, "q2")
    assert cfg.ffmpeg == "/usr/local/bin/ffmpeg"
    assert cfg.log_level == "DEBUG"
    assert cfg.fake_step_delay_s == 0.5


def test_replica_name_precedence():
    assert Config.from_env({**AZURE, "MOTION_REPLICA": "mine", "CONTAINER_APP_REPLICA_NAME": "aca"}).replica == "mine"
    assert Config.from_env({**AZURE, "CONTAINER_APP_REPLICA_NAME": "aca-rep-1"}).replica == "aca-rep-1"
    assert Config.from_env(AZURE).replica == socket.gethostname()


def test_public_dict_is_json_serialisable_and_container_for():
    cfg = Config.from_env(AZURE)
    assert json.loads(json.dumps(cfg.public_dict()))["queue_name"] == "motion-jobs"
    assert cfg.container_for("in") == "motion-in"
    assert cfg.container_for("out") == "motion-out"
    assert cfg.container_for("models") == "motion-models"


def test_process_environment_is_used_when_no_mapping_is_given(monkeypatch):
    for key, value in {"MOTION_TRANSPORT": "local", "MOTION_LOCAL_DIR": "/x", "MOTION_PIPELINE": "fake"}.items():
        monkeypatch.setenv(key, value)
    assert Config.from_env().local_dir == Path("/x")
