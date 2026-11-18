"""Blob store abstraction (Entra-only Azure Blob Storage, or in-memory / local-dir for offline)."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..errors import NotFound
from ..util import sha256_hex


@dataclass
class BlobInfo:
    path: str
    size: int
    content_type: str = "application/octet-stream"
    sha256: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


class BlobStore(Protocol):
    mode: str

    async def put(self, path: str, data: bytes, content_type: str | None = None, metadata: dict[str, str] | None = None) -> BlobInfo: ...
    async def get(self, path: str) -> bytes: ...
    async def exists(self, path: str) -> bool: ...
    async def delete(self, path: str) -> bool: ...
    async def list(self, prefix: str = "") -> list[BlobInfo]: ...
    async def ping(self) -> dict[str, Any]: ...
    async def close(self) -> None: ...


def guess_type(path: str, given: str | None = None) -> str:
    return given or mimetypes.guess_type(path)[0] or "application/octet-stream"


def _check_path(path: str) -> str:
    if not path or path.startswith("/") or ".." in path.split("/") or "\\" in path:
        raise ValueError(f"invalid blob path {path!r}")
    return path


class MemoryBlobStore:
    mode = "memory"

    def __init__(self) -> None:
        self._blobs: dict[str, tuple[bytes, BlobInfo]] = {}

    async def put(self, path: str, data: bytes, content_type: str | None = None, metadata: dict[str, str] | None = None) -> BlobInfo:
        _check_path(path)
        info = BlobInfo(path, len(data), guess_type(path, content_type), sha256_hex(data), dict(metadata or {}))
        self._blobs[path] = (bytes(data), info)
        return info

    async def get(self, path: str) -> bytes:
        _check_path(path)
        if path not in self._blobs:
            raise NotFound(f"blob {path} not found", code="blob_not_found")
        return self._blobs[path][0]

    async def exists(self, path: str) -> bool:
        return path in self._blobs

    async def delete(self, path: str) -> bool:
        return self._blobs.pop(path, None) is not None

    async def list(self, prefix: str = "") -> list[BlobInfo]:
        return [i for p, (_, i) in sorted(self._blobs.items()) if p.startswith(prefix)]

    async def ping(self) -> dict[str, Any]:
        return {"ok": True, "backend": "memory", "blobs": len(self._blobs)}

    async def close(self) -> None:
        return None


class LocalDirBlobStore(MemoryBlobStore):
    """File-backed store for local offline runs that should survive restarts."""

    mode = "localdir"

    def __init__(self, root: str | Path) -> None:
        super().__init__()
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    async def put(self, path: str, data: bytes, content_type: str | None = None, metadata: dict[str, str] | None = None) -> BlobInfo:
        _check_path(path)
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return BlobInfo(path, len(data), guess_type(path, content_type), sha256_hex(data), dict(metadata or {}))

    async def get(self, path: str) -> bytes:
        _check_path(path)
        f = self.root / path
        if not f.is_file():
            raise NotFound(f"blob {path} not found", code="blob_not_found")
        return f.read_bytes()

    async def exists(self, path: str) -> bool:
        return (self.root / _check_path(path)).is_file()

    async def delete(self, path: str) -> bool:
        f = self.root / _check_path(path)
        if f.is_file():
            f.unlink()
            return True
        return False

    async def list(self, prefix: str = "") -> list[BlobInfo]:
        out = []
        for f in sorted(self.root.rglob("*")):
            if f.is_file():
                rel = f.relative_to(self.root).as_posix()
                if rel.startswith(prefix):
                    out.append(BlobInfo(rel, f.stat().st_size, guess_type(rel)))
        return out

    async def ping(self) -> dict[str, Any]:
        return {"ok": True, "backend": "localdir", "root": str(self.root)}


class AzureBlobStore:
    mode = "azure"

    def __init__(self, account_url: str, container: str, credential: Any) -> None:
        from azure.storage.blob.aio import BlobServiceClient

        self._svc = BlobServiceClient(account_url, credential=credential)
        self._container = self._svc.get_container_client(container)
        self._container_name = container

    async def put(self, path: str, data: bytes, content_type: str | None = None, metadata: dict[str, str] | None = None) -> BlobInfo:
        from azure.storage.blob import ContentSettings

        _check_path(path)
        ct = guess_type(path, content_type)
        await self._container.upload_blob(
            path, data, overwrite=True, content_settings=ContentSettings(content_type=ct), metadata=metadata or None
        )
        return BlobInfo(path, len(data), ct, sha256_hex(data), dict(metadata or {}))

    async def get(self, path: str) -> bytes:
        from azure.core.exceptions import ResourceNotFoundError

        _check_path(path)
        try:
            stream = await self._container.download_blob(path)
            return await stream.readall()
        except ResourceNotFoundError as exc:
            raise NotFound(f"blob {path} not found", code="blob_not_found") from exc

    async def exists(self, path: str) -> bool:
        return await self._container.get_blob_client(_check_path(path)).exists()

    async def delete(self, path: str) -> bool:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            await self._container.delete_blob(_check_path(path))
            return True
        except ResourceNotFoundError:
            return False

    async def list(self, prefix: str = "") -> list[BlobInfo]:
        out: list[BlobInfo] = []
        async for b in self._container.list_blobs(name_starts_with=prefix or None):
            ct = b.content_settings.content_type if b.content_settings else None
            out.append(BlobInfo(b.name, b.size or 0, ct or guess_type(b.name)))
        return out

    async def ping(self) -> dict[str, Any]:
        props = await self._container.get_container_properties()
        return {"ok": True, "backend": "azure-blob", "container": self._container_name, "public_access": props.public_access}

    async def close(self) -> None:
        await self._container.close()
        await self._svc.close()
