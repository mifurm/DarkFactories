"""Repository abstraction (Cosmos DB for NoSQL in Azure, in-memory for tests / offline).

Every document has ``id`` and ``pk`` (partition key). ``pk`` defaults to the campaign / brand the
document belongs to, so per-campaign reads stay single-partition (serverless friendly).
"""

from __future__ import annotations

import copy
import re
from collections.abc import Sequence
from typing import Any, Protocol

from ...errors import Conflict, NotFound
from ...util import now_iso

# Keep in sync with infra/modules/data.bicep (unit-tested).
COLLECTIONS: tuple[str, ...] = (
    "brands",
    "brand_chunks",
    "learnings",
    "claims",
    "rights",
    "campaigns",
    "briefs",
    "artifacts",
    "assets",
    "reports",
    "approvals",
    "audit",
    "provenance",
    "experiments",
    "performance",
    "usage",
    "jobs",
    "aicache",
    "webhooks",
    "settings",
    "collections",
    "plans",
)

_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
Where = dict[str, Any]


def default_pk(doc: dict[str, Any]) -> str:
    return str(doc.get("pk") or doc.get("campaign_id") or doc.get("brand_id") or "global")


def validate_field(name: str) -> str:
    if not _FIELD_RE.match(name):
        raise ValueError(f"invalid field name: {name!r}")
    return name


class Repository(Protocol):
    mode: str

    async def create(self, collection: str, doc: dict[str, Any]) -> dict[str, Any]: ...
    async def upsert(self, collection: str, doc: dict[str, Any]) -> dict[str, Any]: ...
    async def get(self, collection: str, doc_id: str, pk: str | None = None) -> dict[str, Any] | None: ...
    async def delete(self, collection: str, doc_id: str, pk: str | None = None) -> bool: ...
    async def query(
        self,
        collection: str,
        where: Where | None = None,
        *,
        pk: str | None = None,
        order_by: str | None = None,
        desc: bool = False,
        limit: int | None = None,
        fields: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]: ...
    async def count(self, collection: str, where: Where | None = None, *, pk: str | None = None) -> int: ...
    async def upsert_many(self, collection: str, docs: list[dict[str, Any]], concurrency: int = 16) -> int: ...
    async def ping(self) -> dict[str, Any]: ...
    async def close(self) -> None: ...


def _get_path(doc: dict[str, Any], dotted: str) -> Any:
    cur: Any = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _match(doc: dict[str, Any], where: Where | None) -> bool:
    for field, cond in (where or {}).items():
        val = _get_path(doc, field)
        if isinstance(cond, dict) and cond and all(k.startswith("$") for k in cond):
            for op, arg in cond.items():
                if op == "$in" and val not in arg:
                    return False
                if op == "$nin" and val in arg:
                    return False
                if op == "$ne" and val == arg:
                    return False
                if op == "$gte" and not (val is not None and val >= arg):
                    return False
                if op == "$lte" and not (val is not None and val <= arg):
                    return False
                if op == "$gt" and not (val is not None and val > arg):
                    return False
                if op == "$lt" and not (val is not None and val < arg):
                    return False
                if op == "$contains" and not (isinstance(val, list) and arg in val):
                    return False
                if op == "$exists" and (val is not None) != bool(arg):
                    return False
        elif val != cond:
            return False
    return True


class MemoryRepository:
    """Process-local repository used for unit tests and the offline demo mode."""

    mode = "memory"

    def __init__(self) -> None:
        self._data: dict[str, dict[tuple[str, str], dict[str, Any]]] = {c: {} for c in COLLECTIONS}

    def _coll(self, name: str) -> dict[tuple[str, str], dict[str, Any]]:
        if name not in self._data:
            raise NotFound(f"unknown collection {name!r}", code="unknown_collection")
        return self._data[name]

    async def create(self, collection: str, doc: dict[str, Any]) -> dict[str, Any]:
        coll = self._coll(collection)
        doc = copy.deepcopy(doc)
        doc["pk"] = default_pk(doc)
        key = (doc["pk"], doc["id"])
        if key in coll:
            raise Conflict(f"{collection}/{doc['id']} already exists")
        doc.setdefault("created_at", now_iso())
        coll[key] = doc
        return copy.deepcopy(doc)

    async def upsert(self, collection: str, doc: dict[str, Any]) -> dict[str, Any]:
        coll = self._coll(collection)
        doc = copy.deepcopy(doc)
        doc["pk"] = default_pk(doc)
        doc.setdefault("created_at", now_iso())
        doc["updated_at"] = now_iso()
        coll[(doc["pk"], doc["id"])] = doc
        return copy.deepcopy(doc)

    async def get(self, collection: str, doc_id: str, pk: str | None = None) -> dict[str, Any] | None:
        coll = self._coll(collection)
        if pk is not None:
            d = coll.get((pk, doc_id))
            return copy.deepcopy(d) if d else None
        for (_, did), d in coll.items():
            if did == doc_id:
                return copy.deepcopy(d)
        return None

    async def delete(self, collection: str, doc_id: str, pk: str | None = None) -> bool:
        coll = self._coll(collection)
        for key in [k for k in coll if k[1] == doc_id and (pk is None or k[0] == pk)]:
            del coll[key]
            return True
        return False

    async def query(
        self,
        collection: str,
        where: Where | None = None,
        *,
        pk: str | None = None,
        order_by: str | None = None,
        desc: bool = False,
        limit: int | None = None,
        fields: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        coll = self._coll(collection)
        rows = [d for (p, _), d in coll.items() if (pk is None or p == pk) and _match(d, where)]
        if order_by:
            validate_field(order_by)
            rows.sort(key=lambda d: (_get_path(d, order_by) is None, _get_path(d, order_by)), reverse=desc)
            if desc:  # keep None last when descending
                rows.sort(key=lambda d: _get_path(d, order_by) is None)
        if limit is not None:
            rows = rows[:limit]
        if fields:
            return [{f: copy.deepcopy(r[f]) for f in fields if f in r} for r in rows]
        return [copy.deepcopy(r) for r in rows]

    async def count(self, collection: str, where: Where | None = None, *, pk: str | None = None) -> int:
        coll = self._coll(collection)
        return sum(1 for (p, _), d in coll.items() if (pk is None or p == pk) and _match(d, where))

    async def upsert_many(self, collection: str, docs: list[dict[str, Any]], concurrency: int = 16) -> int:
        for d in docs:
            await self.upsert(collection, d)
        return len(docs)

    async def ping(self) -> dict[str, Any]:
        return {"ok": True, "backend": "memory", "collections": len(self._data)}

    async def close(self) -> None:
        return None
