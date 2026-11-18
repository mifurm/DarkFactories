"""Immutable, hash-chained audit log (CS-13). Every entry commits to its predecessor; tampering is detectable."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from ..errors import Conflict
from ..i18n import DEFAULT, has
from ..i18n import t as tr
from ..util import canonical_json, now_iso, sha256_hex

GENESIS = "0" * 64


def _normalize_numbers(value: Any) -> Any:
    """Cosmos DB hands an integral number written as ``0.0`` / ``15.0`` back as ``0`` / ``15``: hash both forms identically (bools stay bools).

    Only the audit hash uses this; ``canonical_json`` itself is unchanged because signed provenance manifests depend on its exact output."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _normalize_numbers(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_numbers(v) for v in value]
    return value


def entry_hash(entry: dict[str, Any]) -> str:
    body = {k: _normalize_numbers(v) for k, v in entry.items() if k not in {"hash", "updated_at", "created_at"}}
    return sha256_hex(canonical_json(body))


def entry_message(entry: dict[str, Any], locale: str | None = None) -> str | None:
    """One-line description of an audit entry's action in ``locale`` (None for an action without a catalog label). Display-only: never stored, never hashed."""
    key = f"audit.{entry.get('action', '')}"
    if not has(key, DEFAULT):
        return None
    msg = tr(key, locale)
    stage = (entry.get("subject") or {}).get("stage")
    return tr("audit.with_stage", locale, action=msg, stage=stage) if isinstance(stage, str) and has(f"label.gate.{stage}", DEFAULT) else msg


def render_entry(entry: dict[str, Any], locale: str | None = None) -> dict[str, Any]:
    """An audit entry for display: the stored record plus ``message`` in the viewer's language (the machine ``action`` code is unchanged)."""
    msg = entry_message(entry, locale)
    return {**entry, "message": msg} if msg else dict(entry)


class AuditLog:
    def __init__(self, repo: Any) -> None:
        self.repo = repo
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def _last(self, chain: str) -> dict[str, Any] | None:
        rows = await self.repo.query("audit", pk=chain, order_by="seq", desc=True, limit=1)
        return rows[0] if rows else None

    async def append(self, chain: str, actor: dict[str, Any], action: str, subject: dict[str, Any] | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self._locks[chain]:
            for _ in range(6):
                last = await self._last(chain)
                seq = (last["seq"] + 1) if last else 1
                entry = {
                    "id": f"{chain}:{seq:08d}",
                    "pk": chain,
                    "chain": chain,
                    "seq": seq,
                    "ts": now_iso(),
                    "actor": actor,
                    "action": action,
                    "subject": subject or {},
                    "data": data or {},
                    "prev_hash": last["hash"] if last else GENESIS,
                }
                entry["hash"] = entry_hash(entry)
                try:
                    return await self.repo.create("audit", entry)
                except Conflict:  # another replica appended first -> retry on the new head
                    continue
        raise Conflict("audit chain contention", code="audit_contention")

    async def entries(self, chain: str, limit: int | None = None) -> list[dict[str, Any]]:
        return await self.repo.query("audit", pk=chain, order_by="seq", desc=False, limit=limit)

    async def head(self, chain: str) -> dict[str, Any] | None:
        return await self._last(chain)

    async def verify(self, chain: str) -> dict[str, Any]:
        rows = await self.entries(chain)
        prev = GENESIS
        for i, e in enumerate(rows, start=1):
            if e["seq"] != i:
                return {"chain": chain, "ok": False, "entries": len(rows), "broken_at": i, "reason": "sequence gap (entry missing or reordered)"}
            if e["prev_hash"] != prev:
                return {"chain": chain, "ok": False, "entries": len(rows), "broken_at": i, "reason": "prev_hash does not match previous entry"}
            if entry_hash(e) != e["hash"]:
                return {"chain": chain, "ok": False, "entries": len(rows), "broken_at": i, "reason": "entry content hash mismatch (tampered)"}
            prev = e["hash"]
        return {"chain": chain, "ok": True, "entries": len(rows), "head_hash": prev, "verified_at": now_iso()}
