"""Static guards for what cannot be built here: the Dockerfile, packaging, python-version and keyless rules."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text("utf-8")
BASE_DIGEST = "sha256:ad47b0adb21075d21fd3c6a8786cbc21a09a276f278102163d8809ab0f9712b3"


def instructions() -> list[tuple[str, str]]:
    """Logical Dockerfile instructions (line continuations joined, comments dropped)."""
    joined = re.sub(r"\\\n", " ", DOCKERFILE)
    out = []
    for raw in joined.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            keyword, _, rest = line.partition(" ")
            out.append((keyword.upper(), rest.strip()))
    return out


def test_base_image_is_pinned_by_the_verified_digest():
    froms = [rest for kw, rest in instructions() if kw == "FROM"]
    assert froms == [f"mcr.microsoft.com/k8se/gpu-quickstart@{BASE_DIGEST}"]
    assert ":latest" not in DOCKERFILE


def test_runtime_is_non_root_and_starts_the_worker_module():
    steps = instructions()
    users = [rest for kw, rest in steps if kw == "USER"]
    assert users[0] == "root", "root only for the build steps"
    assert re.fullmatch(r"10001(:10001)?", users[-1]), "the final USER must be the unprivileged uid"
    assert steps[-1] == ("CMD", "[]"), "CMD [] stops the base image's CMD from being appended to the entrypoint"
    assert steps[-2] == ("ENTRYPOINT", '["python", "-m", "motion_worker"]')
    assert [i for i, (kw, rest) in enumerate(steps) if kw == "USER"][-1] < len(steps) - 2


def test_environment_keeps_every_writable_path_under_tmp():
    env_text = " ".join(rest for kw, rest in instructions() if kw == "ENV")
    assert "HF_HUB_DISABLE_TELEMETRY=1" in env_text and "PYTHONUNBUFFERED=1" in env_text
    for variable in ("HF_HOME", "HOME", "XDG_CACHE_HOME", "TORCH_HOME", "TRITON_CACHE_DIR", "TMPDIR"):
        assert re.search(rf"{variable}=/tmp(/|\b)", env_text), f"{variable} must point below /tmp"
    runs = " ".join(rest for kw, rest in instructions() if kw == "RUN")
    assert "chmod 1777" in runs and "/tmp/models" in runs and "/tmp/motion-work" in runs


def test_every_copy_source_exists_and_nothing_secret_is_baked_in():
    for kw, rest in instructions():
        if kw == "COPY":
            source = rest.split()[0]
            assert (ROOT / source).exists(), f"COPY source {source} is missing from the build context"
        assert not re.search(r"(KEY|SECRET|TOKEN|PASSWORD)=", rest) or kw != "ENV"
    ignored = (ROOT / ".dockerignore").read_text("utf-8").split()
    assert {"tests", ".venv", ".scratch"} <= set(ignored)
    assert "Dockerfile" not in ignored, "az acr build needs the Dockerfile in the context"


def test_the_image_installs_exactly_the_pinned_requirements():
    runs = [rest for kw, rest in instructions() if kw == "RUN"]
    assert any("pip install --no-cache-dir -r /opt/motion/requirements.txt" in r for r in runs)
    pins = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text("utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    names = {p.split("==")[0] for p in pins}
    assert names == {"azure-identity", "azure-storage-blob", "azure-storage-queue", "ftfy", "imageio", "imageio-ffmpeg"}
    assert all(re.fullmatch(r"[A-Za-z0-9_.-]+==\d+(\.\d+)*", p) for p in pins), (
        "every runtime dependency is pinned exactly"
    )


def test_pyproject_dependency_ranges_cover_the_pins():
    text = (ROOT / "pyproject.toml").read_text("utf-8")
    assert 'requires-python = ">=3.12"' in text
    for name in ("azure-identity", "azure-storage-blob", "azure-storage-queue", "ftfy", "imageio-ffmpeg"):
        assert f'"{name}' in text


def python_files() -> list[Path]:
    return sorted((ROOT / "motion_worker").glob("*.py"))


@pytest.mark.parametrize("path", python_files(), ids=lambda p: p.name)
def test_source_is_valid_python_3_12(path):
    ast.parse(path.read_text("utf-8"), filename=str(path), feature_version=(3, 12))


def test_no_keys_or_connection_strings_anywhere_in_the_worker():
    banned = (
        "AccountKey=",
        "SharedAccessSignature",
        "DefaultEndpointsProtocol",
        "connection_string",
        "AZURE_STORAGE_KEY",
        "account_key",
        "sas_token",
        "AZURE_CLIENT_SECRET",
        "from_connection_string",
    )
    for path in [*python_files(), ROOT / "Dockerfile", ROOT / "requirements.txt"]:
        text = path.read_text("utf-8")
        for token in banned:
            assert token not in text, f"{token!r} found in {path.name}: the worker must be keyless (Entra only)"


def test_writes_only_under_tmp_by_default():
    from motion_worker.config import Config

    cfg = Config.from_env({"MOTION_TRANSPORT": "local", "MOTION_LOCAL_DIR": "/x"})
    assert str(cfg.model_dir).startswith("/tmp") and str(cfg.work_dir).startswith("/tmp")


def test_the_golden_vectors_file_is_valid_json_with_the_documented_shape():
    vectors = json.loads((ROOT.parent / "contracts" / "job-id-vectors.json").read_text("utf-8"))
    assert {v["name"] for v in vectors["vectors"]} == {"plain", "escaping-unicode", "guidance-rounding"}
