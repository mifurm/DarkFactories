"""Model weights: local dir -> blob mirror (``motion-models``) -> Hugging Face, then write-through to the mirror.

Mirror layout: ``motion-models/<model_id>/<revision>/<relative file>`` plus ``manifest.json`` (written LAST, so its
presence means the mirror is complete). Files are verified by size against the manifest. ``assets/`` and
``examples/`` are never downloaded.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .config import Config
from .contract import utc_now_iso
from .errors import ShutdownRequested, WeightsError
from .logs import event
from .transport import MODELS, Transport

MANIFEST_NAME = "manifest.json"
MARKER_NAME = ".motion-weights.json"
HF_IGNORE_PATTERNS = ("assets/*", "examples/*", "*.md", ".gitattributes")
_SKIP_SUFFIXES = (".part", ".lock", ".incomplete", ".tmp")

HfDownload = Callable[..., Any]


@dataclass(frozen=True)
class WeightsResult:
    path: Path
    source: str  # "local" | "mirror" | "hf"
    files: int
    bytes: int
    seconds: float


def _hf_snapshot_download(
    *, repo_id: str, revision: str, local_dir: Path, ignore_patterns: list[str], max_workers: int
) -> Any:
    from huggingface_hub import snapshot_download  # noqa: PLC0415 - heavy, only needed on a cold start

    return snapshot_download(
        repo_id=repo_id,
        revision=revision,
        local_dir=str(local_dir),
        ignore_patterns=ignore_patterns,
        max_workers=max_workers,
    )


def _safe_relative(rel: Any) -> str:
    if not isinstance(rel, str) or not rel or "\\" in rel or "\x00" in rel:
        raise WeightsError(f"unsafe path in manifest: {rel!r}")
    parts = PurePosixPath(rel).parts
    if PurePosixPath(rel).is_absolute() or ".." in parts or ".cache" in parts:
        raise WeightsError(f"unsafe path in manifest: {rel!r}")
    return rel


def scan_files(root: Path) -> list[tuple[str, int]]:
    """(relative posix path, size) of every weight file under root (HF bookkeeping and partials excluded)."""
    found = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if not path.is_file() or ".cache" in rel.parts or path.name == MARKER_NAME:
            continue
        if path.name.endswith(_SKIP_SUFFIXES):
            continue
        found.append((rel.as_posix(), path.stat().st_size))
    return sorted(found)


class WeightsManager:
    def __init__(
        self,
        cfg: Config,
        transport: Transport,
        *,
        hf_download: HfDownload | None = None,
        stop: threading.Event | None = None,
    ) -> None:
        self.cfg = cfg
        self.transport = transport
        self._hf_download = hf_download or _hf_snapshot_download
        self._stop = stop or threading.Event()
        self.force_remirror = False

    @property
    def prefix(self) -> str:
        return f"{self.cfg.model_id}/{self.cfg.model_revision}"

    @property
    def local_path(self) -> Path:
        return self.cfg.model_dir / self.cfg.model_id / self.cfg.model_revision

    def _check_stop(self) -> None:
        if self._stop.is_set():
            raise ShutdownRequested()

    # -- ensure ---------------------------------------------------------------------------------------

    def ensure(self, *, skip_mirror: bool = False) -> WeightsResult:
        started = time.monotonic()
        path = self.local_path
        if not skip_mirror:
            files = self._verify_local(path)
            if files is not None:
                return self._result(path, "local", files, started)
        self._check_stop()

        manifest = None if skip_mirror else self._read_manifest()
        if manifest is not None:
            try:
                files = self._download_mirror(manifest, path)
                self._write_marker(path, "mirror", files)
                return self._result(path, "mirror", files, started)
            except ShutdownRequested:
                raise
            except Exception as exc:  # noqa: BLE001 - any mirror problem falls back to the upstream source
                event("weights_mirror_failed", logging.WARNING, error=f"{type(exc).__name__}: {exc}")
                shutil.rmtree(path, ignore_errors=True)
        if skip_mirror:
            shutil.rmtree(path, ignore_errors=True)
            self.force_remirror = True
        self._check_stop()

        files = self._download_hf(path)
        self._write_marker(path, "hf", files)
        return self._result(path, "hf", files, started)

    def discard_local(self) -> None:
        shutil.rmtree(self.local_path, ignore_errors=True)

    def _result(self, path: Path, source: str, files: list[tuple[str, int]], started: float) -> WeightsResult:
        result = WeightsResult(path, source, len(files), sum(s for _, s in files), round(time.monotonic() - started, 1))
        event("weights_ready", source=source, files=result.files, bytes=result.bytes, seconds=result.seconds)
        return result

    # -- local ----------------------------------------------------------------------------------------

    def _verify_local(self, path: Path) -> list[tuple[str, int]] | None:
        try:
            marker = json.loads((path / MARKER_NAME).read_text("utf-8"))
            if marker.get("revision") != self.cfg.model_revision:
                return None
            files = [(f["path"], int(f["size"])) for f in marker["files"]]
            if not files:
                return None
            for rel, size in files:
                if (path / _safe_relative(rel)).stat().st_size != size:
                    return None
        except (OSError, ValueError, KeyError, TypeError, WeightsError):
            return None
        return files

    def _write_marker(self, path: Path, source: str, files: list[tuple[str, int]]) -> None:
        doc = {
            "v": 1,
            "model_id": self.cfg.model_id,
            "revision": self.cfg.model_revision,
            "source": source,
            "created_at": utc_now_iso(),
            "files": [{"path": rel, "size": size} for rel, size in files],
        }
        (path / MARKER_NAME).write_text(json.dumps(doc), "utf-8")

    # -- mirror ---------------------------------------------------------------------------------------

    def _read_manifest(self) -> dict[str, Any] | None:
        try:
            raw = self.transport.read_blob(MODELS, f"{self.prefix}/{MANIFEST_NAME}")
        except Exception as exc:  # noqa: BLE001 - e.g. container missing / no access: behave as "no mirror"
            event("weights_mirror_unavailable", logging.WARNING, error=f"{type(exc).__name__}: {exc}")
            return None
        if raw is None:
            return None
        try:
            doc = json.loads(raw)
            if (
                doc.get("v") != 1
                or doc.get("model_id") != self.cfg.model_id
                or doc.get("revision") != self.cfg.model_revision
            ):
                raise WeightsError("manifest does not match the configured model/revision")
            files = [{"path": _safe_relative(f["path"]), "size": int(f["size"])} for f in doc["files"]]
            if not files:
                raise WeightsError("manifest lists no files")
        except (ValueError, KeyError, TypeError, WeightsError) as exc:
            event("weights_manifest_invalid", logging.WARNING, error=str(exc))
            return None
        return {**doc, "files": files}

    def _download_mirror(self, manifest: Mapping[str, Any], dest: Path) -> list[tuple[str, int]]:
        files = sorted(manifest["files"], key=lambda f: -f["size"])  # biggest first keeps the workers busy
        dest.mkdir(parents=True, exist_ok=True)
        event("weights_mirror_download", files=len(files), bytes=sum(f["size"] for f in files))

        def fetch(entry: Mapping[str, Any]) -> tuple[str, int]:
            self._check_stop()
            rel, size = entry["path"], entry["size"]
            target = dest / rel
            if target.is_file() and target.stat().st_size == size:
                return rel, size  # finished by an earlier, interrupted attempt
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_name(target.name + ".part")
            self.transport.download_to(MODELS, f"{self.prefix}/{rel}", part)
            actual = part.stat().st_size
            if actual != size:
                part.unlink(missing_ok=True)
                raise WeightsError(f"{rel}: size {actual} does not match manifest ({size})")
            os.replace(part, target)
            return rel, size

        done: list[tuple[str, int]] = []
        with ThreadPoolExecutor(max_workers=self.cfg.download_workers, thread_name_prefix="weights") as pool:
            futures = [pool.submit(fetch, f) for f in files]
            try:
                for future in as_completed(futures):
                    done.append(future.result())
            except BaseException:
                pool.shutdown(wait=False, cancel_futures=True)
                raise
        return sorted(done)

    def mirror_complete(self) -> bool:
        return self._read_manifest() is not None

    def invalidate_mirror(self) -> None:
        self.transport.delete_blob(MODELS, f"{self.prefix}/{MANIFEST_NAME}")

    def mirror_upload(self, path: Path, overrides: Mapping[str, Path] | None = None) -> bool:
        """Write-through of a verified local copy. ``overrides`` replaces a top-level folder by another directory
        (the optional bf16 transformer). Existing blobs of the same size are skipped (resume); the manifest is
        written last. Returns False when nothing had to be done."""
        if not self.force_remirror and self.mirror_complete():
            return False
        overrides = dict(overrides or {})
        entries: dict[str, Path] = {}
        for rel, _ in scan_files(path):
            if rel.split("/", 1)[0] in overrides:
                continue
            entries[rel] = path / rel
        for folder, directory in overrides.items():
            for rel, _ in scan_files(directory):
                entries[f"{folder}/{rel}"] = directory / rel
        listing = sorted(((rel, src.stat().st_size, src) for rel, src in entries.items()), key=lambda e: -e[1])
        event("mirror_upload_start", files=len(listing), bytes=sum(s for _, s, _ in listing))

        def push(entry: tuple[str, int, Path]) -> None:
            self._check_stop()
            rel, size, src = entry
            key = f"{self.prefix}/{rel}"
            if not self.force_remirror and self.transport.blob_size(MODELS, key) == size:
                return
            self.transport.upload_from(MODELS, key, src, "application/octet-stream")

        with ThreadPoolExecutor(max_workers=self.cfg.download_workers, thread_name_prefix="mirror") as pool:
            futures = [pool.submit(push, e) for e in listing]
            try:
                for future in as_completed(futures):
                    future.result()
            except BaseException:
                pool.shutdown(wait=False, cancel_futures=True)
                raise
        manifest = {
            "v": 1,
            "model_id": self.cfg.model_id,
            "repo": self.cfg.model_repo,
            "revision": self.cfg.model_revision,
            "created_at": utc_now_iso(),
            "files": [{"path": rel, "size": size} for rel, size, _ in sorted(listing)],
        }
        self.transport.write_blob(MODELS, f"{self.prefix}/{MANIFEST_NAME}", json.dumps(manifest).encode("utf-8"))
        self.force_remirror = False
        event("mirror_upload_done", files=len(listing))
        return True

    # -- Hugging Face ---------------------------------------------------------------------------------

    def _download_hf(self, dest: Path) -> list[tuple[str, int]]:
        dest.mkdir(parents=True, exist_ok=True)
        event("weights_hf_download", repo=self.cfg.model_repo, revision=self.cfg.model_revision)
        self._hf_download(
            repo_id=self.cfg.model_repo,
            revision=self.cfg.model_revision,
            local_dir=dest,
            ignore_patterns=list(HF_IGNORE_PATTERNS),
            max_workers=max(8, self.cfg.download_workers),
        )
        files = scan_files(dest)
        if not files:
            raise WeightsError("Hugging Face download produced no files")
        return files
