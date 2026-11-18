"""Worker configuration, read once from the environment (see README env table)."""

from __future__ import annotations

import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .contract import DEFAULT_MODEL_ID, MODELS
from .errors import ConfigError

TRANSPORTS = ("azure", "local")
PIPELINES = ("wan", "fake")

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


class _Env:
    """Typed env access that collects every problem so the operator sees them all at once."""

    def __init__(self, env: Mapping[str, str]) -> None:
        self.env = env
        self.errors: list[str] = []

    def str(self, name: str, default: str | None = None) -> str | None:
        value = self.env.get(name)
        return value.strip() if value and value.strip() else default

    def choice(self, name: str, default: str, allowed: tuple[str, ...]) -> str:
        value = (self.str(name, default) or default).lower()
        if value not in allowed:
            self.errors.append(f"{name} must be one of {', '.join(allowed)} (got {value!r})")
            return default
        return value

    def number(self, name: str, default: float, lo: float, hi: float) -> float:
        raw = self.str(name)
        if raw is None:
            return default
        try:
            value = float(raw)
        except ValueError:
            self.errors.append(f"{name} must be a number (got {raw!r})")
            return default
        if not lo <= value <= hi:
            self.errors.append(f"{name} must be between {lo:g} and {hi:g} (got {value:g})")
            return default
        return value

    def integer(self, name: str, default: int, lo: int, hi: int) -> int:
        return int(self.number(name, float(default), lo, hi))

    def flag(self, name: str, default: bool) -> bool:
        raw = self.str(name)
        if raw is None:
            return default
        if raw.lower() in _TRUE:
            return True
        if raw.lower() in _FALSE:
            return False
        self.errors.append(f"{name} must be a boolean (got {raw!r})")
        return default


def _check_url(errors: list[str], name: str, value: str | None) -> None:
    if not value:
        errors.append(f"{name} is required when MOTION_TRANSPORT=azure")
        return
    parsed = urlparse(value)
    local_http = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")
    if not parsed.hostname or (parsed.scheme != "https" and not local_http):
        errors.append(f"{name} must be an https URL (got {value!r})")


def _check_work_dir(errors: list[str], work: Path, others: dict[str, Path | None]) -> None:
    """The worker deletes its work dir at start-up and on exit, so it must be a dedicated directory."""
    resolved = work.expanduser().resolve()
    absolute = Path(
        os.path.abspath(work.expanduser())
    )  # the symlink-free depth can differ (macOS /var -> /private/var)
    if min(len(resolved.parts), len(absolute.parts)) < 3:  # "/", "/tmp", "/var", ...
        errors.append(f"MOTION_WORK_DIR must be a dedicated directory because it is wiped (got {work})")
    for name, other in others.items():
        if other is None:
            continue
        theirs = other.expanduser().resolve()
        if theirs == resolved or resolved in theirs.parents or theirs in resolved.parents:
            errors.append(f"MOTION_WORK_DIR must not equal, contain or sit inside {name} ({other})")


@dataclass(frozen=True)
class Config:
    transport: str = "azure"
    local_dir: Path | None = None
    azure_client_id: str | None = None
    storage_account_url: str | None = None
    queue_url: str | None = None
    queue_name: str = "motion-jobs"
    in_container: str = "motion-in"
    out_container: str = "motion-out"
    models_container: str = "motion-models"

    model_dir: Path = Path("/tmp/models")
    work_dir: Path = Path("/tmp/motion-work")
    model_id: str = DEFAULT_MODEL_ID
    model_repo: str = MODELS[DEFAULT_MODEL_ID].repo
    model_revision: str = MODELS[DEFAULT_MODEL_ID].revision
    pipeline: str = "wan"

    visibility_timeout_s: int = 600
    renew_interval_s: float = 60.0
    status_interval_s: float = 2.0
    ready_interval_s: float = 60.0
    poll_interval_s: float = 2.0
    max_dequeue: int = 3
    job_timeout_s: float = 600.0
    watchdog_grace_s: float = 120.0
    shutdown_grace_s: float = 600.0
    shutdown_margin_s: float = 30.0
    exit_when_idle_s: float = 0.0

    download_workers: int = 4
    blob_concurrency: int = 8
    mirror: bool = True
    mirror_bf16: bool = False
    warmup_generate: bool = False
    fake_step_delay_s: float = 0.0
    fake_load_delay_s: float = 0.0

    ffmpeg: str | None = None
    replica: str = field(default_factory=socket.gethostname)
    log_level: str = "INFO"

    def container_for(self, area: str) -> str:
        return {"in": self.in_container, "out": self.out_container, "models": self.models_container}[area]

    def public_dict(self) -> dict[str, Any]:
        """Config as JSON-able dict (nothing here is secret: identities are ids, auth is token based)."""
        return {k: (str(v) if isinstance(v, Path) else v) for k, v in self.__dict__.items()}

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        e = _Env(os.environ if env is None else env)
        transport = e.choice("MOTION_TRANSPORT", "azure", TRANSPORTS)
        model_id = e.str("MOTION_MODEL_ID", DEFAULT_MODEL_ID) or DEFAULT_MODEL_ID
        known = MODELS.get(model_id)
        repo = e.str("MOTION_MODEL_REPO", known.repo if known else None)
        revision = e.str("MOTION_MODEL_REVISION", known.revision if known else None)
        pipeline = e.choice("MOTION_PIPELINE", "wan", PIPELINES)

        local_dir = e.str("MOTION_LOCAL_DIR")
        storage_url = e.str("MOTION_STORAGE_ACCOUNT_URL")
        queue_url = e.str("MOTION_QUEUE_URL")
        if transport == "local" and not local_dir:
            e.errors.append("MOTION_LOCAL_DIR is required when MOTION_TRANSPORT=local")
        if transport == "azure":
            _check_url(e.errors, "MOTION_STORAGE_ACCOUNT_URL", storage_url)
            _check_url(e.errors, "MOTION_QUEUE_URL", queue_url)
        if pipeline == "wan" and not (repo and revision):
            e.errors.append(
                f"MOTION_MODEL_REPO and MOTION_MODEL_REVISION are required for unknown MOTION_MODEL_ID {model_id!r}"
            )

        visibility = e.integer("MOTION_VISIBILITY_TIMEOUT_S", 600, 30, 3600)
        renew = e.number("MOTION_RENEW_INTERVAL_S", 60.0, 0.01, 120.0)
        if renew > visibility / 2:
            e.errors.append("MOTION_RENEW_INTERVAL_S must not exceed half of MOTION_VISIBILITY_TIMEOUT_S")
        model_dir = Path(e.str("MOTION_MODEL_DIR", "/tmp/models") or "/tmp/models")
        work_dir = Path(e.str("MOTION_WORK_DIR", "/tmp/motion-work") or "/tmp/motion-work")
        _check_work_dir(
            e.errors,
            work_dir,
            {"MOTION_MODEL_DIR": model_dir, "MOTION_LOCAL_DIR": Path(local_dir) if local_dir else None},
        )

        cfg = cls(
            transport=transport,
            local_dir=Path(local_dir) if local_dir else None,
            azure_client_id=e.str("AZURE_CLIENT_ID"),
            storage_account_url=storage_url,
            queue_url=queue_url,
            queue_name=e.str("MOTION_QUEUE_NAME", "motion-jobs") or "motion-jobs",
            in_container=e.str("MOTION_IN_CONTAINER", "motion-in") or "motion-in",
            out_container=e.str("MOTION_OUT_CONTAINER", "motion-out") or "motion-out",
            models_container=e.str("MOTION_MODELS_CONTAINER", "motion-models") or "motion-models",
            model_dir=model_dir,
            work_dir=work_dir,
            model_id=model_id,
            model_repo=repo or "",
            model_revision=revision or "",
            pipeline=pipeline,
            visibility_timeout_s=visibility,
            renew_interval_s=renew,
            status_interval_s=e.number("MOTION_STATUS_INTERVAL_S", 2.0, 0.01, 3.0),
            ready_interval_s=e.number("MOTION_READY_INTERVAL_S", 60.0, 0.01, 90.0),
            poll_interval_s=e.number("MOTION_POLL_INTERVAL_S", 2.0, 0.001, 60.0),
            max_dequeue=e.integer("MOTION_MAX_DEQUEUE", 3, 1, 20),
            job_timeout_s=e.number("MOTION_JOB_TIMEOUT_S", 600.0, 1.0, 7200.0),
            watchdog_grace_s=e.number("MOTION_WATCHDOG_GRACE_S", 120.0, 0.1, 3600.0),
            shutdown_grace_s=e.number("MOTION_SHUTDOWN_GRACE_S", 600.0, 0.0, 3600.0),
            shutdown_margin_s=e.number("MOTION_SHUTDOWN_MARGIN_S", 30.0, 0.0, 600.0),
            exit_when_idle_s=e.number("MOTION_EXIT_WHEN_IDLE_S", 0.0, 0.0, 86400.0),
            download_workers=e.integer("MOTION_DOWNLOAD_WORKERS", 4, 1, 32),
            blob_concurrency=e.integer("MOTION_BLOB_CONCURRENCY", 8, 1, 64),
            mirror=e.flag("MOTION_MIRROR", True),
            mirror_bf16=e.flag("MOTION_MIRROR_BF16", False),
            warmup_generate=e.flag("MOTION_WARMUP_GENERATE", False),
            fake_step_delay_s=e.number("MOTION_FAKE_STEP_DELAY_S", 0.0, 0.0, 10.0),
            fake_load_delay_s=e.number("MOTION_FAKE_LOAD_DELAY_S", 0.0, 0.0, 600.0),
            ffmpeg=e.str("MOTION_FFMPEG"),
            replica=e.str("MOTION_REPLICA") or e.str("CONTAINER_APP_REPLICA_NAME") or socket.gethostname(),
            log_level=(e.str("MOTION_LOG_LEVEL", "INFO") or "INFO").upper(),
        )
        if e.errors:
            raise ConfigError("invalid configuration: " + "; ".join(e.errors))
        return cfg
