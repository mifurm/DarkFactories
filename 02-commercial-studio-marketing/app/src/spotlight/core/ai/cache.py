"""Prompt-hash cache for AI outputs (avoids repeated spend). Small JSON in Cosmos, binaries in Blob."""

from __future__ import annotations

from typing import Any

from ...util import now_iso


class AICache:
    def __init__(self, repo: Any, blobs: Any) -> None:
        self.repo = repo
        self.blobs = blobs
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _pk(key: str) -> str:
        return key[:2]

    async def get_json(self, key: str) -> dict[str, Any] | None:
        doc = await self.repo.get("aicache", key, pk=self._pk(key))
        if doc is None:
            self.misses += 1
            return None
        self.hits += 1
        return doc.get("data")

    async def put_json(self, key: str, data: dict[str, Any]) -> None:
        await self.repo.upsert("aicache", {"id": key, "pk": self._pk(key), "kind": "json", "data": data, "ts": now_iso(), "ttl": 14 * 86400})

    async def get_bytes(self, key: str) -> tuple[bytes, dict[str, Any]] | None:
        doc = await self.repo.get("aicache", key, pk=self._pk(key))
        if doc is None or "blob" not in doc:
            self.misses += 1
            return None
        try:
            data = await self.blobs.get(doc["blob"])
        except Exception:
            self.misses += 1
            return None
        self.hits += 1
        return data, doc.get("meta", {})

    async def put_bytes(self, key: str, data: bytes, meta: dict[str, Any], mime: str) -> None:
        path = f"cache/{key}"
        await self.blobs.put(path, data, mime)
        await self.repo.upsert(
            "aicache", {"id": key, "pk": self._pk(key), "kind": "bytes", "blob": path, "meta": meta, "ts": now_iso(), "ttl": 14 * 86400}
        )

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}
