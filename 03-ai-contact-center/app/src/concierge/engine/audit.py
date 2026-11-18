"""Append-only, hash-chained audit log (tamper-evident). Detail payloads are PII/PCI-redacted before storage."""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import time
import uuid
from typing import Any

from ..core.redaction import redact_obj
from ..core.repo import Repository

GENESIS = "GENESIS"


def _digest(prev: str, body: dict[str, Any]) -> str:
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True, default=str)).encode()).hexdigest()


class AuditLog:
    def __init__(self, repo: Repository, collection: str = "audit", retention_days: int = 400) -> None:
        self.repo = repo
        self.collection = collection
        self.ttl = retention_days * 86400
        self._lock = asyncio.Lock()
        self._last = GENESIS
        self._seq = 0
        self._ready = False

    async def init(self) -> None:
        latest = await self.repo.query(self.collection, order_by="seq", desc=True, limit=1)
        if latest:
            self._last = latest[0]["hash"]
            self._seq = int(latest[0]["seq"])
        self._ready = True

    async def log(
        self,
        action: str,
        *,
        actor: str = "system",
        resource: str = "",
        detail: dict[str, Any] | None = None,
        conv_id: str | None = None,
        outcome: str = "ok",
    ) -> dict[str, Any]:
        if not self._ready:
            await self.init()
        async with self._lock:
            self._seq += 1
            body = {
                "seq": self._seq,
                "ts": time.time(),
                "actor": actor,
                "action": action,
                "resource": resource,
                "outcome": outcome,
                "conv_id": conv_id,
                "detail": redact_obj(detail or {}),
            }
            h = _digest(self._last, body)
            doc = {"id": f"{self._seq:010d}-{uuid.uuid4().hex[:6]}", **body, "prev_hash": self._last, "hash": h}
            await self.repo.put(self.collection, doc, ttl=self.ttl)
            self._last = h
            return doc

    async def recent(self, limit: int = 100, where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return await self.repo.query(self.collection, where, order_by="seq", desc=True, limit=limit)

    async def verify(self, limit: int = 1000) -> dict[str, Any]:
        rows = await self.repo.query(self.collection, order_by="seq", desc=False)
        rows = rows[-limit:]
        broken = None
        for prev, cur in itertools.pairwise(rows):
            body = {k: cur[k] for k in ("seq", "ts", "actor", "action", "resource", "outcome", "conv_id", "detail")}
            if cur["prev_hash"] != prev["hash"] or _digest(cur["prev_hash"], body) != cur["hash"]:
                broken = cur["seq"]
                break
        return {"ok": broken is None, "checked": len(rows), "broken_at_seq": broken, "head": rows[-1]["hash"] if rows else GENESIS}
