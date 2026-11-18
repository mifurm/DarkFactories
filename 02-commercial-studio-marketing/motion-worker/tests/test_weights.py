"""Weights: local dir -> blob mirror -> Hugging Face, write-through, resume, verification."""

from __future__ import annotations

import json
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from motion_worker import weights as weights_mod
from motion_worker.errors import ShutdownRequested, WeightsError
from motion_worker.transport import MODELS, LocalTransport
from motion_worker.weights import HF_IGNORE_PATTERNS, MANIFEST_NAME, MARKER_NAME, WeightsManager, scan_files

from .conftest import make_cfg
from .helpers import FakeHf, expected_downloaded


class SpyTransport(LocalTransport):
    """Records model-area traffic, tracks download concurrency, and can run a hook on each download."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.events: list[tuple[str, str]] = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()
        self.download_delay = 0.0
        self.on_download = None

    def download_to(self, area, name, dest):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.events.append(("download", name))
        try:
            time.sleep(self.download_delay)
            super().download_to(area, name, dest)
            if self.on_download:
                self.on_download(name)
        finally:
            with self.lock:
                self.active -= 1

    def upload_from(self, area, name, src, content_type="application/octet-stream"):
        with self.lock:
            self.events.append(("upload", name))
        super().upload_from(area, name, src, content_type)

    def write_blob(self, area, name, data, content_type="application/json"):
        with self.lock:
            self.events.append(("write", name))
        super().write_blob(area, name, data, content_type)

    def names(self, kind):
        return [n for k, n in self.events if k == kind]


@pytest.fixture
def env(tmp_path):
    cfg = make_cfg(tmp_path, download_workers=3)
    transport = SpyTransport(cfg.local_dir)
    hf = FakeHf()
    stop = threading.Event()
    manager = WeightsManager(cfg, transport, hf_download=hf, stop=stop)
    return cfg, transport, hf, manager, stop


def weight_files(root: Path) -> dict[str, bytes]:
    return {rel: (root / rel).read_bytes() for rel, _ in scan_files(root)}


def seed_mirror(
    manager: WeightsManager, transport: SpyTransport, blobs: dict[str, bytes] | None = None, **manifest_over
):
    files = expected_downloaded() if blobs is None else blobs
    for rel, data in files.items():
        transport.write_blob(MODELS, f"{manager.prefix}/{rel}", data)
    manifest = {
        "v": 1,
        "model_id": manager.cfg.model_id,
        "revision": manager.cfg.model_revision,
        "files": [{"path": rel, "size": len(data)} for rel, data in files.items()],
    } | manifest_over
    transport.write_blob(MODELS, f"{manager.prefix}/{MANIFEST_NAME}", json.dumps(manifest).encode())
    transport.events.clear()
    return files


# ---------------------------------------------------------------------------------------------- Hugging Face path


def test_first_start_downloads_from_hf_without_assets_and_examples(env):
    cfg, transport, hf, manager, _ = env
    result = manager.ensure()
    assert result.source == "hf"
    assert result.path == cfg.model_dir / cfg.model_id / cfg.model_revision
    (call,) = hf.calls
    assert (call["repo_id"], call["revision"]) == (cfg.model_repo, cfg.model_revision)
    assert {"assets/*", "examples/*"} <= set(call["ignore"]) and set(call["ignore"]) == set(HF_IGNORE_PATTERNS)
    assert weight_files(result.path) == expected_downloaded()
    assert not (result.path / "assets").exists() and not (result.path / "examples").exists()
    assert (result.path / MARKER_NAME).exists()
    assert result.files == len(expected_downloaded()) and result.bytes == sum(map(len, expected_downloaded().values()))
    assert manager.force_remirror is False


def test_second_start_reuses_the_verified_local_copy(env):
    cfg, transport, hf, manager, stop = env
    manager.ensure()
    again = WeightsManager(cfg, transport, hf_download=hf, stop=stop).ensure()
    assert again.source == "local"
    assert len(hf.calls) == 1


def test_a_damaged_local_copy_is_not_trusted(env):
    cfg, transport, hf, manager, stop = env
    result = manager.ensure()
    (result.path / "text_encoder" / "model.safetensors").write_bytes(b"short")
    again = WeightsManager(cfg, transport, hf_download=hf, stop=stop).ensure()
    assert again.source == "hf"
    assert (result.path / "text_encoder" / "model.safetensors").read_bytes() == b"E" * 4000


def test_a_marker_for_another_revision_is_ignored(env):
    cfg, transport, hf, manager, stop = env
    result = manager.ensure()
    marker = result.path / MARKER_NAME
    doc = json.loads(marker.read_text())
    doc["revision"] = "something-else"
    marker.write_text(json.dumps(doc))
    assert WeightsManager(cfg, transport, hf_download=hf, stop=stop).ensure().source == "hf"


def test_hf_that_produces_nothing_is_an_error(env):
    cfg, transport, _, _, stop = env
    manager = WeightsManager(cfg, transport, hf_download=FakeHf({"README.md": b"x"}), stop=stop)
    with pytest.raises(WeightsError, match="no files"):
        manager.ensure()


def test_the_real_download_wrapper_passes_the_documented_arguments(env, monkeypatch):
    cfg, transport, _, _, stop = env
    seen = {}

    def snapshot_download(**kwargs):
        seen.update(kwargs)
        for rel, data in expected_downloaded().items():
            target = Path(kwargs["local_dir"]) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(snapshot_download=snapshot_download))
    manager = WeightsManager(cfg, transport, stop=stop)  # default downloader
    assert manager.ensure().source == "hf"
    assert seen["repo_id"] == cfg.model_repo and seen["revision"] == cfg.model_revision
    assert isinstance(seen["local_dir"], str) and seen["ignore_patterns"] == list(HF_IGNORE_PATTERNS)
    assert seen["max_workers"] >= 8


# ---------------------------------------------------------------------------------------------- mirror path


def test_mirror_download_is_parallel_size_verified_and_skips_hf(env):
    cfg, transport, hf, manager, _ = env
    files = seed_mirror(manager, transport)
    transport.download_delay = 0.05
    result = manager.ensure()
    assert result.source == "mirror"
    assert hf.calls == []
    assert weight_files(result.path) == files
    assert 1 < transport.max_active <= cfg.download_workers
    assert sorted(transport.names("download")) == sorted(f"{manager.prefix}/{rel}" for rel in files)
    # largest first keeps the workers busy
    assert transport.names("download")[0].endswith("text_encoder/model.safetensors")
    assert not list(result.path.rglob("*.part"))
    assert manager.ensure().source == "local"


def test_a_size_mismatch_against_the_manifest_falls_back_to_hf(env):
    cfg, transport, hf, manager, _ = env
    seed_mirror(manager, transport)
    transport.write_blob(MODELS, f"{manager.prefix}/text_encoder/model.safetensors", b"truncated")
    result = manager.ensure()
    assert result.source == "hf" and len(hf.calls) == 1
    assert weight_files(result.path) == expected_downloaded()


@pytest.mark.parametrize(
    "manifest_over",
    [
        {"revision": "other"},
        {"model_id": "other"},
        {"v": 2},
        {"files": []},
        {"files": [{"path": "../escape", "size": 1}]},
        {"files": [{"path": "/abs/path", "size": 1}]},
        {"files": [{"path": ".cache/x", "size": 1}]},
        {"files": [{"path": "a\\b", "size": 1}]},
        {"files": "nonsense"},
    ],
)
def test_untrustworthy_manifests_are_ignored(env, manifest_over):
    cfg, transport, hf, manager, _ = env
    seed_mirror(manager, transport, **manifest_over)
    assert manager.ensure().source == "hf"
    assert len(hf.calls) == 1


def test_non_json_manifest_and_unreadable_mirror_fall_back(env):
    cfg, transport, hf, manager, stop = env
    transport.write_blob(MODELS, f"{manager.prefix}/{MANIFEST_NAME}", b"not json")
    assert manager.ensure().source == "hf"
    manager.discard_local()

    class Broken(SpyTransport):
        def read_blob(self, area, name):
            raise ConnectionError("storage unreachable")

    broken = WeightsManager(cfg, Broken(cfg.local_dir), hf_download=FakeHf(), stop=stop)
    assert broken.ensure().source == "hf"


def test_an_interrupted_mirror_download_is_resumed_without_refetching_finished_files(env):
    cfg, transport, hf, manager, _ = env
    files = seed_mirror(manager, transport)
    done = manager.local_path / "text_encoder" / "model.safetensors"
    done.parent.mkdir(parents=True, exist_ok=True)
    done.write_bytes(files["text_encoder/model.safetensors"])
    (manager.local_path / "vae").mkdir(parents=True, exist_ok=True)
    (manager.local_path / "vae" / "diffusion_pytorch_model.safetensors.part").write_bytes(b"half")
    result = manager.ensure()
    assert result.source == "mirror"
    assert f"{manager.prefix}/text_encoder/model.safetensors" not in transport.names("download")
    assert weight_files(result.path) == files
    assert not list(result.path.rglob("*.part"))


def test_shutdown_during_the_mirror_download_stops_cleanly(env):
    cfg, transport, hf, manager, stop = env
    seed_mirror(manager, transport)
    transport.download_delay = 0.05
    transport.on_download = lambda name: stop.set()
    with pytest.raises(ShutdownRequested):
        manager.ensure()
    assert hf.calls == []
    assert not (manager.local_path / MARKER_NAME).exists()


def test_shutdown_before_start_is_honoured(env):
    _, _, hf, manager, stop = env
    stop.set()
    with pytest.raises(ShutdownRequested):
        manager.ensure()
    assert hf.calls == []


# ---------------------------------------------------------------------------------------------- write-through


def test_write_through_uploads_every_file_and_the_manifest_last(env):
    cfg, transport, hf, manager, _ = env
    result = manager.ensure()
    assert manager.mirror_upload(result.path) is True
    uploaded = transport.names("upload")
    assert sorted(uploaded) == sorted(f"{manager.prefix}/{rel}" for rel in expected_downloaded())
    assert not any(".cache" in n or MARKER_NAME in n or "assets" in n for n in uploaded)
    assert transport.events[-1] == ("write", f"{manager.prefix}/{MANIFEST_NAME}")
    manifest = json.loads(transport.read_blob(MODELS, f"{manager.prefix}/{MANIFEST_NAME}"))
    assert (manifest["v"], manifest["model_id"], manifest["revision"], manifest["repo"]) == (
        1, cfg.model_id, cfg.model_revision, cfg.model_repo,
    )  # fmt: skip
    assert {f["path"]: f["size"] for f in manifest["files"]} == {k: len(v) for k, v in expected_downloaded().items()}
    assert manager.mirror_upload(result.path) is False, "already mirrored"

    # a fresh replica now cold-starts from the mirror and gets identical bytes
    other = make_cfg(cfg.local_dir.parent / "replica2", local_dir=cfg.local_dir)
    second = WeightsManager(other, transport, hf_download=FakeHf(), stop=threading.Event()).ensure()
    assert second.source == "mirror"
    assert weight_files(second.path) == expected_downloaded()


def test_write_through_resumes_and_skips_blobs_that_are_already_there(env):
    cfg, transport, hf, manager, _ = env
    result = manager.ensure()
    transport.write_blob(MODELS, f"{manager.prefix}/text_encoder/model.safetensors", b"E" * 4000)
    transport.events.clear()
    manager.mirror_upload(result.path)
    assert f"{manager.prefix}/text_encoder/model.safetensors" not in transport.names("upload")
    assert len(transport.names("upload")) == len(expected_downloaded()) - 1


def test_write_through_stops_without_a_manifest_when_shutdown_is_requested(env):
    cfg, transport, hf, manager, stop = env
    result = manager.ensure()
    stop.set()
    with pytest.raises(ShutdownRequested):
        manager.mirror_upload(result.path)
    assert transport.read_blob(MODELS, f"{manager.prefix}/{MANIFEST_NAME}") is None, (
        "incomplete mirrors never get a manifest"
    )


def test_bf16_override_replaces_the_transformer_folder_in_the_mirror(env, tmp_path):
    cfg, transport, hf, manager, _ = env
    result = manager.ensure()
    export = tmp_path / "bf16"
    export.mkdir()
    (export / "config.json").write_bytes(b'{"bf16": true}')
    (export / "diffusion_pytorch_model.safetensors").write_bytes(b"B" * 1234)
    manager.mirror_upload(result.path, {"transformer": export})
    manifest = json.loads(transport.read_blob(MODELS, f"{manager.prefix}/{MANIFEST_NAME}"))
    sizes = {f["path"]: f["size"] for f in manifest["files"]}
    assert sizes["transformer/diffusion_pytorch_model.safetensors"] == 1234
    assert sizes["transformer/config.json"] == len(b'{"bf16": true}')
    assert not any("00001-of-00002" in p for p in sizes), "fp32 shards must not be mirrored"
    assert sizes["text_encoder/model.safetensors"] == 4000


def test_skip_mirror_rebuilds_from_hf_and_forces_a_full_remirror(env):
    cfg, transport, hf, manager, _ = env
    first = manager.ensure()
    manager.mirror_upload(first.path)
    transport.write_blob(MODELS, f"{manager.prefix}/text_encoder/model.safetensors", b"X" * 4000)  # corrupt, same size
    transport.events.clear()
    fresh = manager.ensure(skip_mirror=True)
    assert fresh.source == "hf" and len(hf.calls) == 2 and manager.force_remirror is True
    assert manager.mirror_upload(fresh.path) is True
    assert len(transport.names("upload")) == len(expected_downloaded()), "same-size blobs are re-uploaded when forced"
    assert transport.read_blob(MODELS, f"{manager.prefix}/text_encoder/model.safetensors") == b"E" * 4000
    assert manager.force_remirror is False


def test_invalidate_mirror_removes_the_manifest(env):
    cfg, transport, hf, manager, _ = env
    seed_mirror(manager, transport)
    assert manager.mirror_complete()
    manager.invalidate_mirror()
    assert not manager.mirror_complete()


def test_scan_files_ignores_bookkeeping(tmp_path):
    root = tmp_path / "w"
    (root / ".cache" / "huggingface").mkdir(parents=True)
    (root / ".cache" / "huggingface" / "m").write_text("x")
    (root / "a").mkdir()
    for name in ("a/ok.safetensors", "a/big.part", "a/x.lock", "a/y.incomplete", MARKER_NAME, "top.json"):
        (root / name).write_text("data")
    assert [rel for rel, _ in scan_files(root)] == ["a/ok.safetensors", "top.json"]
    assert weights_mod.scan_files(tmp_path / "nothing") == []
