"""Repository abstraction: Cosmos DB (production) and in-memory (tests / offline). Documents are plain dicts."""

from __future__ import annotations

import asyncio
import copy
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from .collections import COLLECTIONS, partition_key

Where = dict[str, Any]


def _get_path(doc: dict, path: str) -> Any:
    cur: Any = doc
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def matches(doc: dict, where: Where | None) -> bool:
    if not where:
        return True
    for path, cond in where.items():
        val = _get_path(doc, path)
        if isinstance(cond, dict) and cond and all(k.startswith("$") for k in cond):
            for op, arg in cond.items():
                if op == "$ne" and val == arg:
                    return False
                if op == "$in" and val not in arg:
                    return False
                if op == "$nin" and val in arg:
                    return False
                if op in ("$gt", "$gte", "$lt", "$lte"):
                    if val is None:
                        return False
                    if (
                        (op == "$gt" and not val > arg)
                        or (op == "$gte" and not val >= arg)
                        or (op == "$lt" and not val < arg)
                        or (op == "$lte" and not val <= arg)
                    ):
                        return False
                if op == "$contains" and not (isinstance(val, list | str) and arg in val):
                    return False
                if op == "$exists" and (val is not None) != bool(arg):
                    return False
        elif val != cond:
            return False
    return True


class Repository(ABC):
    kind = "abstract"

    @abstractmethod
    async def put(self, coll: str, doc: dict, *, ttl: int | None = None) -> dict: ...

    @abstractmethod
    async def get(self, coll: str, doc_id: str) -> dict | None: ...

    @abstractmethod
    async def delete(self, coll: str, doc_id: str) -> bool: ...

    @abstractmethod
    async def query(
        self,
        coll: str,
        where: Where | None = None,
        *,
        order_by: str | None = None,
        desc: bool = False,
        limit: int | None = None,
    ) -> list[dict]: ...

    @abstractmethod
    async def ping(self) -> dict: ...

    async def close(self) -> None:  # pragma: no cover - default no-op
        return None

    async def count(self, coll: str, where: Where | None = None) -> int:
        return len(await self.query(coll, where))

    async def put_many(self, coll: str, docs: Iterable[dict]) -> int:
        n = 0
        for d in docs:
            await self.put(coll, d)
            n += 1
        return n

    async def clear(self, coll: str) -> int:
        n = 0
        for d in await self.query(coll):
            if await self.delete(coll, d["id"]):
                n += 1
        return n


def prepare(coll: str, doc: dict, ttl: int | None) -> dict:
    if coll not in COLLECTIONS:
        raise KeyError(f"unknown collection '{coll}'")
    if "id" not in doc or not isinstance(doc["id"], str) or not doc["id"]:
        raise ValueError("document needs a non-empty string 'id'")
    if any(ch in doc["id"] for ch in "/\\?#"):
        raise ValueError("Id contains illegal chars.")  # same rule as Cosmos DB, enforced for every repository so offline tests catch it
    body = dict(doc)
    body["pk"] = partition_key(coll, body["id"])
    if ttl is not None:
        body["ttl"] = int(ttl)
    return body


class InMemoryRepository(Repository):
    kind = "memory"

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict]] = {c: {} for c in COLLECTIONS}
        self._lock = asyncio.Lock()

    def _live(self, coll: str) -> dict[str, dict]:
        store = self._data[coll]
        now = time.time()
        dead = [k for k, v in store.items() if v.get("ttl") and v["ttl"] > 0 and now > v.get("_ts", now) + v["ttl"]]
        for k in dead:
            del store[k]
        return store

    async def put(self, coll: str, doc: dict, *, ttl: int | None = None) -> dict:
        body = prepare(coll, doc, ttl)
        body["_ts"] = time.time()
        self._data[coll][body["id"]] = copy.deepcopy(body)
        return body

    async def get(self, coll: str, doc_id: str) -> dict | None:
        found = self._live(coll).get(doc_id)
        return copy.deepcopy(found) if found else None

    async def delete(self, coll: str, doc_id: str) -> bool:
        return self._data[coll].pop(doc_id, None) is not None

    async def query(
        self,
        coll: str,
        where: Where | None = None,
        *,
        order_by: str | None = None,
        desc: bool = False,
        limit: int | None = None,
    ) -> list[dict]:
        rows = [d for d in self._live(coll).values() if matches(d, where)]
        if order_by:
            rows.sort(key=lambda d: (_get_path(d, order_by) is None, _get_path(d, order_by)), reverse=desc)
            if desc:  # keep None-valued rows last when descending
                rows.sort(key=lambda d: _get_path(d, order_by) is None)
        if limit is not None:
            rows = rows[:limit]
        return copy.deepcopy(rows)

    async def count(self, coll: str, where: Where | None = None) -> int:
        return sum(1 for d in self._live(coll).values() if matches(d, where))

    async def ping(self) -> dict:
        return {"ok": True, "kind": self.kind}

    def snapshot(self, colls: Iterable[str]) -> dict[str, dict[str, dict]]:
        return {c: copy.deepcopy(self._data[c]) for c in colls}

    def load_snapshot(self, snap: dict[str, dict[str, dict]]) -> None:
        for c, docs in snap.items():
            self._data[c] = copy.deepcopy(docs)
