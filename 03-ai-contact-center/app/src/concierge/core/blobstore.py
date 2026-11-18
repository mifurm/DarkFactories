"""Blob storage abstraction: Azure Blob (Entra only, shared-key access disabled) or in-memory."""

from __future__ import annotations

import time
from typing import Any


class MemoryBlobStore:
    kind = "memory"

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], tuple[bytes, str, float]] = {}

    async def put(self, container: str, name: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._data[(container, name)] = (data, content_type, time.time())
        return f"memory://{container}/{name}"

    async def get(self, container: str, name: str) -> bytes | None:
        item = self._data.get((container, name))
        return item[0] if item else None

    async def list(self, container: str, prefix: str = "") -> list[dict[str, Any]]:
        return [
            {"name": n, "size": len(v[0]), "content_type": v[1], "ts": v[2]}
            for (c, n), v in sorted(self._data.items())
            if c == container and n.startswith(prefix)
        ]

    async def ping(self) -> dict[str, Any]:
        return {"ok": True, "kind": self.kind}

    async def close(self) -> None:
        return None


class AzureBlobStore:  # pragma: no cover - needs Azure
    kind = "azure-blob"

    def __init__(self, account_url: str, credential: Any) -> None:
        from azure.storage.blob.aio import BlobServiceClient

        self._svc = BlobServiceClient(account_url, credential=credential)
        self.account_url = account_url

    async def put(self, container: str, name: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        from azure.storage.blob import ContentSettings

        blob = self._svc.get_blob_client(container, name)
        await blob.upload_blob(data, overwrite=True, content_settings=ContentSettings(content_type=content_type))
        return blob.url

    async def get(self, container: str, name: str) -> bytes | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            stream = await self._svc.get_blob_client(container, name).download_blob()
            return await stream.readall()
        except ResourceNotFoundError:
            return None

    async def list(self, container: str, prefix: str = "") -> list[dict[str, Any]]:
        out = []
        async for b in self._svc.get_container_client(container).list_blobs(name_starts_with=prefix):
            out.append({"name": b.name, "size": b.size, "content_type": b.content_settings.content_type, "ts": b.last_modified.timestamp()})
        return out

    async def ping(self) -> dict[str, Any]:
        try:
            container = self._svc.get_container_client("exports")
            async for _ in container.list_blobs(results_per_page=1):
                break
            return {"ok": True, "kind": self.kind, "account": self.account_url, "container": "exports"}
        except Exception as exc:
            return {"ok": False, "kind": self.kind, "error": str(exc)[:160]}

    async def close(self) -> None:
        await self._svc.close()
