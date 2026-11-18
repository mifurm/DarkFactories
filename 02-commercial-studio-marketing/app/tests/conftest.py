"""Test configuration: offline mode, scratch files kept inside the project (never the system temp dir)."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".tmp"
SCRATCH.mkdir(exist_ok=True)
os.environ["TMPDIR"] = str(SCRATCH)
tempfile.tempdir = str(SCRATCH)
os.environ["SPOTLIGHT_MODE"] = "offline"
os.environ["RATE_LIMIT_ENABLED"] = "false"
for key in ("COSMOS_ENDPOINT", "BLOB_ACCOUNT_URL", "AZURE_OPENAI_ENDPOINT", "AI_ENDPOINT", "APPLICATIONINSIGHTS_CONNECTION_STRING"):
    os.environ.pop(key, None)

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not installed")


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(SCRATCH, ignore_errors=True)


@pytest.fixture
def settings():
    from spotlight.config import Settings

    return Settings(spotlight_mode="offline", rate_limit_enabled=False, seed_on_start=True)


@pytest.fixture
async def services(settings):
    from spotlight.seed import ensure_seeded
    from spotlight.services import build_services

    s = await build_services(settings)
    await ensure_seeded(s)
    yield s
    await s.close()
