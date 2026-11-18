"""Queue + blob transports.

* ``AzureTransport``: Azure Queue Storage + Blob Storage, Entra ID only (managed identity), no keys.
* ``LocalTransport``: a directory with the same layout and Azure-like queue semantics (visibility timeout,
  pop receipts, dequeue counts) so everything is testable on a laptop and by the Studio's local mode.

Local layout (root ``D``): ``D/queue/<ts>-<uuid>.json`` pending message, ``.claimed`` in flight (renamed atomically),
``.state`` receipt/dequeue-count/visibility; blobs live in ``D/<container>/<blob name>``.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .config import Config
from .errors import MessageLost

try:  # POSIX only; the in-process lock still serialises threads elsewhere
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

IN, OUT, MODELS = "in", "out", "models"
DEFAULT_CONTAINERS: Mapping[str, str] = {IN: "motion-in", OUT: "motion-out", MODELS: "motion-models"}


@dataclass
class ReceivedMessage:
    """A dequeued message. ``receipt`` rotates on every renewal (Azure pop receipts do); always use the latest."""

    id: str
    body: str
    dequeue_count: int
    receipt: str
    inserted_at: datetime | None = None
    lost: bool = False
    lock: Any = field(default_factory=threading.RLock, repr=False, compare=False)


@dataclass(frozen=True)
class BlobInfo:
    name: str
    size: int


class Transport(Protocol):
    name: str

    def receive(self, visibility_timeout_s: int) -> ReceivedMessage | None: ...
    def renew(self, msg: ReceivedMessage, visibility_timeout_s: int) -> None: ...
    def release(self, msg: ReceivedMessage) -> None: ...
    def delete(self, msg: ReceivedMessage) -> None: ...
    def send(self, body: str) -> None: ...
    def queue_depth(self) -> int: ...
    def read_blob(self, area: str, name: str) -> bytes | None: ...
    def write_blob(self, area: str, name: str, data: bytes, content_type: str = "application/json") -> None: ...
    def blob_exists(self, area: str, name: str) -> bool: ...
    def blob_size(self, area: str, name: str) -> int | None: ...
    def delete_blob(self, area: str, name: str) -> bool: ...
    def list_blobs(self, area: str, prefix: str = "") -> list[BlobInfo]: ...
    def download_to(self, area: str, name: str, dest: Path) -> None: ...
    def upload_from(self, area: str, name: str, src: Path, content_type: str = ...) -> None: ...


# --------------------------------------------------------------------------------------------------
# Local directory transport
# --------------------------------------------------------------------------------------------------


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class LocalTransport:
    name = "local"

    def __init__(
        self,
        root: Path | str,
        *,
        containers: Mapping[str, str] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.root = Path(root)
        self.containers = dict(containers or DEFAULT_CONTAINERS)
        self.queue_dir = self.root / "queue"
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.RLock()

    # -- blobs ---------------------------------------------------------------------------------------

    def _blob_path(self, area: str, name: str) -> Path:
        base = (self.root / self.containers[area]).resolve()
        target = (base / name).resolve()
        if target == base or base not in target.parents:
            raise ValueError(f"unsafe blob name: {name!r}")
        return target

    def read_blob(self, area: str, name: str) -> bytes | None:
        try:
            return self._blob_path(area, name).read_bytes()
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            return None

    def write_blob(self, area: str, name: str, data: bytes, content_type: str = "application/json") -> None:
        _atomic_write(self._blob_path(area, name), data)

    def blob_exists(self, area: str, name: str) -> bool:
        return self._blob_path(area, name).is_file()

    def blob_size(self, area: str, name: str) -> int | None:
        path = self._blob_path(area, name)
        return path.stat().st_size if path.is_file() else None

    def delete_blob(self, area: str, name: str) -> bool:
        try:
            self._blob_path(area, name).unlink()
        except FileNotFoundError:
            return False
        return True

    def list_blobs(self, area: str, prefix: str = "") -> list[BlobInfo]:
        base = (self.root / self.containers[area]).resolve()
        if not base.is_dir():
            return []
        found = []
        for path in base.rglob("*"):
            if not path.is_file() or (path.name.startswith(".") and path.name.endswith(".tmp")):
                continue
            name = path.relative_to(base).as_posix()
            if name.startswith(prefix):
                found.append(BlobInfo(name, path.stat().st_size))
        return sorted(found, key=lambda b: b.name)

    def download_to(self, area: str, name: str, dest: Path) -> None:
        src = self._blob_path(area, name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)  # FileNotFoundError when the blob does not exist

    def upload_from(self, area: str, name: str, src: Path, content_type: str = "application/octet-stream") -> None:
        target = self._blob_path(area, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.tmp")
        shutil.copyfile(src, tmp)
        os.replace(tmp, target)

    # -- queue ---------------------------------------------------------------------------------------

    @contextlib.contextmanager
    def _queue_lock(self) -> Iterator[None]:
        with self._lock:
            fd = None
            if fcntl is not None:
                fd = os.open(self.queue_dir / ".lock", os.O_CREAT | os.O_RDWR, 0o666)
                fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fd is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)

    def _paths(self, message_id: str) -> tuple[Path, Path, Path]:
        base = self.queue_dir / message_id
        return base.with_suffix(".json"), base.with_suffix(".claimed"), base.with_suffix(".state")

    def _read_state(self, state_path: Path) -> dict[str, Any]:
        try:
            return json.loads(state_path.read_text("utf-8"))
        except (FileNotFoundError, ValueError):
            return {}

    def _write_state(self, state_path: Path, state: dict[str, Any]) -> None:
        _atomic_write(state_path, json.dumps(state).encode("utf-8"))

    def send(self, body: str) -> None:
        _atomic_write(self.queue_dir / f"{time.time_ns():020d}-{uuid.uuid4().hex}.json", body.encode("utf-8"))

    def queue_depth(self) -> int:
        return len(list(self.queue_dir.glob("*.json"))) + len(list(self.queue_dir.glob("*.claimed")))

    def _reap_expired(self, now: float) -> None:
        for claimed in self.queue_dir.glob("*.claimed"):
            json_path, _, state_path = self._paths(claimed.stem)
            if self._read_state(state_path).get("visible_at", 0) <= now:
                with contextlib.suppress(FileNotFoundError):
                    os.rename(claimed, json_path)

    def receive(self, visibility_timeout_s: int) -> ReceivedMessage | None:
        with self._queue_lock():
            now = self._clock()
            self._reap_expired(now)
            pending = []
            for path in self.queue_dir.glob("*.json"):
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    continue
                if stat.st_size > 0:  # an empty file is a torn write by a non-atomic producer: skip it
                    pending.append((stat.st_mtime_ns, path.name, path, stat.st_mtime))
            for _, _, path, mtime in sorted(pending):
                _, claimed, state_path = self._paths(path.stem)
                try:
                    os.rename(path, claimed)
                except FileNotFoundError:
                    continue
                count = int(self._read_state(state_path).get("dequeue_count", 0)) + 1
                receipt = uuid.uuid4().hex
                self._write_state(
                    state_path,
                    {"dequeue_count": count, "visible_at": now + visibility_timeout_s, "receipt": receipt},
                )
                return ReceivedMessage(
                    id=path.stem,
                    body=claimed.read_text("utf-8"),
                    dequeue_count=count,
                    receipt=receipt,
                    inserted_at=datetime.fromtimestamp(mtime, UTC),
                )
        return None

    def _owned_state(self, msg: ReceivedMessage) -> tuple[Path, Path, Path, dict[str, Any]]:
        json_path, claimed, state_path = self._paths(msg.id)
        state = self._read_state(state_path)
        if not claimed.exists() or state.get("receipt") != msg.receipt:
            msg.lost = True
            raise MessageLost(f"message {msg.id} is no longer owned by this consumer")
        return json_path, claimed, state_path, state

    def renew(self, msg: ReceivedMessage, visibility_timeout_s: int) -> None:
        with self._queue_lock(), msg.lock:
            _, _, state_path, state = self._owned_state(msg)
            state.update(visible_at=self._clock() + visibility_timeout_s, receipt=uuid.uuid4().hex)
            self._write_state(state_path, state)
            msg.receipt = state["receipt"]

    def release(self, msg: ReceivedMessage) -> None:
        with self._queue_lock(), msg.lock:
            json_path, claimed, state_path, state = self._owned_state(msg)
            state.update(visible_at=0, receipt="")
            self._write_state(state_path, state)
            os.rename(claimed, json_path)

    def delete(self, msg: ReceivedMessage) -> None:
        with self._queue_lock(), msg.lock:
            _, claimed, state_path, _ = self._owned_state(msg)
            claimed.unlink()
            state_path.unlink(missing_ok=True)


# --------------------------------------------------------------------------------------------------
# Azure transport
# --------------------------------------------------------------------------------------------------

_GONE_CODES = {"MessageNotFound", "PopReceiptMismatch", "QueueNotFound"}


def _status(exc: BaseException) -> int | None:
    value = getattr(exc, "status_code", None)
    return value if isinstance(value, int) else None


def _error_code(exc: BaseException) -> str:
    """The wire code, e.g. 'PopReceiptMismatch'. The SDK's code is a str-mixin Enum: its str() is not the wire value."""
    code = getattr(exc, "error_code", None)
    return str(getattr(code, "value", code) or "")


def _is_gone(exc: BaseException) -> bool:
    """The queue message is no longer ours (deleted, expired, or re-delivered with a newer pop receipt)."""
    return _status(exc) == 404 or _error_code(exc) in _GONE_CODES


def _is_blob_missing(exc: BaseException) -> bool:
    return _status(exc) == 404 and _error_code(exc) != "ContainerNotFound"


def _default_content_settings(content_type: str) -> Any:
    from azure.storage.blob import ContentSettings  # noqa: PLC0415

    return ContentSettings(content_type=content_type)


class AzureTransport:
    name = "azure"

    def __init__(
        self,
        *,
        queue_client: Any,
        blob_service: Any,
        containers: Mapping[str, str] | None = None,
        blob_concurrency: int = 8,
        content_settings: Callable[[str], Any] = _default_content_settings,
    ) -> None:
        self._queue = queue_client
        self._blobs = blob_service
        self.containers = dict(containers or DEFAULT_CONTAINERS)
        self.blob_concurrency = blob_concurrency
        self._content_settings = content_settings

    @classmethod
    def from_config(cls, cfg: Config) -> AzureTransport:
        """Entra ID only: DefaultAzureCredential with the user-assigned identity AZURE_CLIENT_ID; no keys."""
        from azure.identity import DefaultAzureCredential  # noqa: PLC0415
        from azure.storage.blob import BlobServiceClient  # noqa: PLC0415
        from azure.storage.blob import ExponentialRetry as BlobRetry  # noqa: PLC0415
        from azure.storage.queue import ExponentialRetry as QueueRetry  # noqa: PLC0415
        from azure.storage.queue import QueueClient  # noqa: PLC0415

        credential = (
            DefaultAzureCredential(managed_identity_client_id=cfg.azure_client_id)
            if cfg.azure_client_id
            else DefaultAzureCredential()
        )
        # Short retry ladder (~2+4+6+10 s): a stuck storage call must not stall heartbeats for minutes.
        blob_service = BlobServiceClient(
            account_url=cfg.storage_account_url,
            credential=credential,
            retry_policy=BlobRetry(initial_backoff=2, increment_base=2, retry_total=4, random_jitter_range=1),
            max_chunk_get_size=8 * 1024 * 1024,
            max_block_size=8 * 1024 * 1024,
        )
        queue_client = QueueClient(
            account_url=cfg.queue_url,
            queue_name=cfg.queue_name,
            credential=credential,
            retry_policy=QueueRetry(initial_backoff=2, increment_base=2, retry_total=4, random_jitter_range=1),
        )
        containers = {IN: cfg.in_container, OUT: cfg.out_container, MODELS: cfg.models_container}
        return cls(
            queue_client=queue_client,
            blob_service=blob_service,
            containers=containers,
            blob_concurrency=cfg.blob_concurrency,
        )

    # -- queue ---------------------------------------------------------------------------------------

    def receive(self, visibility_timeout_s: int) -> ReceivedMessage | None:
        # max_messages=1 is essential: without it the SDK iterator keeps draining the queue.
        for message in self._queue.receive_messages(visibility_timeout=visibility_timeout_s, max_messages=1):
            body = message.content
            if isinstance(body, bytes):
                body = body.decode("utf-8", "replace")
            return ReceivedMessage(
                id=message.id,
                body=body,
                dequeue_count=int(message.dequeue_count or 1),
                receipt=message.pop_receipt,
                inserted_at=message.inserted_on,
            )
        return None

    def renew(self, msg: ReceivedMessage, visibility_timeout_s: int) -> None:
        # visibility_timeout must always be explicit: the SDK sends 0 (= visible now) when it is omitted.
        with msg.lock:
            try:
                updated = self._queue.update_message(
                    msg.id, pop_receipt=msg.receipt, visibility_timeout=visibility_timeout_s
                )
            except Exception as exc:
                if _is_gone(exc):
                    msg.lost = True
                    raise MessageLost(str(exc)) from exc
                raise
            msg.receipt = updated.pop_receipt

    def release(self, msg: ReceivedMessage) -> None:
        with msg.lock:
            try:
                self._queue.update_message(msg.id, pop_receipt=msg.receipt, visibility_timeout=0)
            except Exception as exc:
                if _is_gone(exc):
                    msg.lost = True
                    raise MessageLost(str(exc)) from exc
                raise

    def delete(self, msg: ReceivedMessage) -> None:
        with msg.lock:
            try:
                self._queue.delete_message(msg.id, pop_receipt=msg.receipt)
            except Exception as exc:
                if _is_gone(exc):
                    msg.lost = True
                    raise MessageLost(str(exc)) from exc
                raise

    def send(self, body: str) -> None:
        self._queue.send_message(body)

    def queue_depth(self) -> int:
        return int(self._queue.get_queue_properties().approximate_message_count)

    # -- blobs ---------------------------------------------------------------------------------------

    def _blob(self, area: str, name: str) -> Any:
        return self._blobs.get_blob_client(container=self.containers[area], blob=name)

    def read_blob(self, area: str, name: str) -> bytes | None:
        try:
            return self._blob(area, name).download_blob().readall()
        except Exception as exc:
            if _is_blob_missing(exc):
                return None
            raise

    def write_blob(self, area: str, name: str, data: bytes, content_type: str = "application/json") -> None:
        self._blob(area, name).upload_blob(data, overwrite=True, content_settings=self._content_settings(content_type))

    def blob_exists(self, area: str, name: str) -> bool:
        return bool(self._blob(area, name).exists())

    def blob_size(self, area: str, name: str) -> int | None:
        try:
            return int(self._blob(area, name).get_blob_properties().size)
        except Exception as exc:
            if _is_blob_missing(exc):
                return None
            raise

    def delete_blob(self, area: str, name: str) -> bool:
        try:
            self._blob(area, name).delete_blob()
        except Exception as exc:
            if _is_blob_missing(exc):
                return False
            raise
        return True

    def list_blobs(self, area: str, prefix: str = "") -> list[BlobInfo]:
        container = self._blobs.get_container_client(self.containers[area])
        return [BlobInfo(b.name, int(b.size)) for b in container.list_blobs(name_starts_with=prefix or None)]

    def download_to(self, area: str, name: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as fh:
            self._blob(area, name).download_blob(max_concurrency=self.blob_concurrency).readinto(fh)

    def upload_from(self, area: str, name: str, src: Path, content_type: str = "application/octet-stream") -> None:
        with open(src, "rb") as fh:
            self._blob(area, name).upload_blob(
                fh,
                length=src.stat().st_size,
                overwrite=True,
                max_concurrency=self.blob_concurrency,
                content_settings=self._content_settings(content_type),
            )


def build_transport(cfg: Config) -> Transport:
    if cfg.transport == "local":
        assert cfg.local_dir is not None
        return LocalTransport(
            cfg.local_dir,
            containers={IN: cfg.in_container, OUT: cfg.out_container, MODELS: cfg.models_container},
        )
    return AzureTransport.from_config(cfg)
