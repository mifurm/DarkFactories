"""Persistence ports: document Repository (Cosmos DB for NoSQL | in-memory) and BlobStore (Azure Blob | in-memory).

Every document carries ``id`` and ``pk`` (partition key value; usually the plant id). Containers are fixed names created by Bicep.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger("nightshift.repo")

CONTAINERS = ("ledger", "approvals", "kpi", "reports", "audit", "state", "jobs", "telemetry")
_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_OPS = {"=": "=", "!=": "!=", ">": ">", ">=": ">=", "<": "<", "<=": "<="}
_SYSTEM_FIELDS = ("_rid", "_self", "_etag", "_attachments", "_ts")

Where = dict[str, Any]


def _normalise(where: Where | None) -> list[tuple[str, str, Any]]:
    out: list[tuple[str, str, Any]] = []
    for key, cond in (where or {}).items():
        if not _FIELD.match(key):
            raise ValueError(f"invalid field name {key!r}")
        if isinstance(cond, tuple):
            op, val = cond
            if op not in _OPS:
                raise ValueError(f"invalid operator {op!r}")
            out.append((key, _OPS[op], val))
        else:
            out.append((key, "=", cond))
    return out


def _get(doc: dict[str, Any], path: str) -> Any:
    cur: Any = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _match(doc: dict[str, Any], conds: list[tuple[str, str, Any]]) -> bool:
    for path, op, val in conds:
        v = _get(doc, path)
        if v is None and op != "!=":
            return False
        try:
            ok = {"=": v == val, "!=": v != val, ">": v > val, ">=": v >= val, "<": v < val, "<=": v <= val}[op]
        except TypeError:
            return False
        if not ok:
            return False
    return True


class Repository(ABC):
    name = "abstract"

    @abstractmethod
    async def upsert(self, container: str, doc: dict[str, Any]) -> None: ...

    @abstractmethod
    async def get(self, container: str, id: str, pk: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def query(
        self,
        container: str,
        *,
        pk: str | None = None,
        where: Where | None = None,
        order_by: str | None = None,
        desc: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def delete(self, container: str, id: str, pk: str) -> None: ...

    @abstractmethod
    async def ping(self) -> dict[str, Any]: ...

    async def count(self, container: str, *, pk: str | None = None, where: Where | None = None) -> int:
        return len(await self.query(container, pk=pk, where=where))

    async def upsert_many(self, container: str, docs: Iterable[dict[str, Any]]) -> None:
        for d in docs:
            await self.upsert(container, d)

    async def close(self) -> None:  # pragma: no cover
        return None


class MemoryRepository(Repository):
    name = "memory"

    def __init__(self) -> None:
        self._data: dict[str, dict[tuple[str, str], dict[str, Any]]] = {c: {} for c in CONTAINERS}

    def _c(self, container: str) -> dict[tuple[str, str], dict[str, Any]]:
        return self._data.setdefault(container, {})

    async def upsert(self, container: str, doc: dict[str, Any]) -> None:
        if "id" not in doc or "pk" not in doc:
            raise ValueError("document needs 'id' and 'pk'")
        self._c(container)[(str(doc["pk"]), str(doc["id"]))] = copy.deepcopy(doc)

    async def get(self, container: str, id: str, pk: str) -> dict[str, Any] | None:
        d = self._c(container).get((pk, id))
        return copy.deepcopy(d) if d else None

    async def query(
        self,
        container: str,
        *,
        pk: str | None = None,
        where: Where | None = None,
        order_by: str | None = None,
        desc: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        conds = _normalise(where)
        rows = [d for (p, _), d in self._c(container).items() if (pk is None or p == pk) and _match(d, conds)]
        if order_by:
            if not _FIELD.match(order_by):
                raise ValueError("invalid order_by")
            rows.sort(key=lambda d: (_get(d, order_by) is None, _get(d, order_by)), reverse=desc)
        if limit is not None:
            rows = rows[:limit]
        return copy.deepcopy(rows)

    async def delete(self, container: str, id: str, pk: str) -> None:
        self._c(container).pop((pk, id), None)

    async def ping(self) -> dict[str, Any]:
        t = time.perf_counter()
        await self.upsert("state", {"id": "ready-probe", "pk": "_probe", "ts": datetime.now(UTC).isoformat()})
        ok = (await self.get("state", "ready-probe", "_probe")) is not None
        return {
            "status": "ok" if ok else "fail",
            "backend": "memory",
            "latency_ms": round((time.perf_counter() - t) * 1000, 2),
        }


class CosmosRepository(Repository):  # pragma: no cover - exercised against real Azure by the smoke test
    name = "cosmos"

    def __init__(self, endpoint: str, database: str, credential: Any) -> None:
        from azure.cosmos.aio import CosmosClient

        self.endpoint = endpoint
        self._client = CosmosClient(endpoint, credential=credential)
        self._db = self._client.get_database_client(database)
        self._containers: dict[str, Any] = {}

    def _c(self, name: str) -> Any:
        if name not in self._containers:
            self._containers[name] = self._db.get_container_client(name)
        return self._containers[name]

    @staticmethod
    def _clean(doc: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in doc.items() if k not in _SYSTEM_FIELDS}

    async def upsert(self, container: str, doc: dict[str, Any]) -> None:
        if "id" not in doc or "pk" not in doc:
            raise ValueError("document needs 'id' and 'pk'")
        await self._c(container).upsert_item(doc)

    async def get(self, container: str, id: str, pk: str) -> dict[str, Any] | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            return self._clean(await self._c(container).read_item(id, partition_key=pk))
        except CosmosResourceNotFoundError:
            return None

    @staticmethod
    def _path(field: str) -> str:
        return "c" + "".join(f'["{p}"]' for p in field.split("."))

    def _sql(
        self,
        where: Where | None,
        pk: str | None,
        order_by: str | None,
        desc: bool,
        limit: int | None,
        select: str = "*",
    ) -> tuple[str, list[dict[str, Any]]]:
        conds = _normalise(where)
        params: list[dict[str, Any]] = []
        clauses: list[str] = []
        for i, (path, op, val) in enumerate(conds):
            clauses.append(f"{self._path(path)} {op} @p{i}")
            params.append({"name": f"@p{i}", "value": val})
        sql = f"SELECT {select} FROM c"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        if order_by:
            if not _FIELD.match(order_by):
                raise ValueError("invalid order_by")
            sql += f" ORDER BY {self._path(order_by)} {'DESC' if desc else 'ASC'}"
        if limit is not None:
            sql += f" OFFSET 0 LIMIT {int(limit)}"
        return sql, params

    async def query(
        self,
        container: str,
        *,
        pk: str | None = None,
        where: Where | None = None,
        order_by: str | None = None,
        desc: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        sql, params = self._sql(where, pk, order_by, desc, limit)
        kw: dict[str, Any] = {"query": sql, "parameters": params}
        if pk is not None:
            kw["partition_key"] = pk
        return [self._clean(item) async for item in self._c(container).query_items(**kw)]

    async def delete(self, container: str, id: str, pk: str) -> None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            await self._c(container).delete_item(id, partition_key=pk)
        except CosmosResourceNotFoundError:
            return

    async def ping(self) -> dict[str, Any]:
        t = time.perf_counter()
        doc = {"id": "ready-probe", "pk": "_probe", "ts": datetime.now(UTC).isoformat()}
        await self.upsert("state", doc)
        got = await self.get("state", "ready-probe", "_probe")
        return {
            "status": "ok" if got and got.get("ts") == doc["ts"] else "fail",
            "backend": "cosmos",
            "endpoint": self.endpoint,
            "latency_ms": round((time.perf_counter() - t) * 1000, 2),
        }

    async def close(self) -> None:
        await self._client.close()


# Documents per container per UTC day (Cosmos DB serverless cost guard: a demo left at a high simulation speed must not run up RU charges).
DAILY_DOC_CAPS: dict[str, int] = {"telemetry": 60_000, "kpi": 12_000, "default": 40_000}


class WriteBehind:
    """Batched, non-blocking persistence for high-rate producers (ledger, KPI snapshots, telemetry aggregates)."""

    def __init__(
        self,
        repo: Repository,
        max_queue: int = 20000,
        batch: int = 40,
        concurrency: int = 6,
        caps: dict[str, int] | None = None,
    ) -> None:
        self.repo = repo
        self.queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=max_queue)
        self.batch, self.concurrency = batch, concurrency
        self.written = self.failed = self.dropped = self.capped = 0
        self.caps = DAILY_DOC_CAPS if caps is None else caps
        self._day = ""
        self._today: dict[str, int] = {}
        self._task: asyncio.Task | None = None
        self._stopping = False

    def _within_cap(self, container: str) -> bool:
        if not self.caps:
            return True
        day = time.strftime("%Y-%m-%d", time.gmtime())
        if day != self._day:
            self._day, self._today = day, {}
        n = self._today.get(container, 0)
        if n >= self.caps.get(container, self.caps.get("default", 10**9)):
            return False
        self._today[container] = n + 1
        return True

    def enqueue(self, container: str, doc: dict[str, Any]) -> None:
        if not self._within_cap(container):
            self.capped += 1
            return
        if self.queue.full():
            try:
                self.queue.get_nowait()
                self.dropped += 1
            except asyncio.QueueEmpty:  # pragma: no cover
                pass
        self.queue.put_nowait((container, doc))

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="write-behind")

    async def _write(self, sem: asyncio.Semaphore, container: str, doc: dict[str, Any]) -> None:
        async with sem:
            for attempt in range(3):
                try:
                    await self.repo.upsert(container, doc)
                    self.written += 1
                    return
                except Exception as exc:
                    if attempt == 2:
                        self.failed += 1
                        log.warning("write-behind drop %s/%s: %s", container, doc.get("id"), exc)
                    else:
                        await asyncio.sleep(0.3 * (attempt + 1))

    async def _drain_once(self) -> int:
        items: list[Any] = []
        while len(items) < self.batch and not self.queue.empty():
            items.append(self.queue.get_nowait())
        if items:
            sem = asyncio.Semaphore(self.concurrency)
            await asyncio.gather(*(self._write(sem, c, d) for c, d in items))
        return len(items)

    async def _run(self) -> None:
        while not self._stopping:
            n = await self._drain_once()
            if n == 0:
                await asyncio.sleep(0.5)

    async def flush(self, timeout: float = 10.0) -> None:
        end = time.monotonic() + timeout
        while not self.queue.empty() and time.monotonic() < end:
            await self._drain_once()

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.flush(5.0)

    def stats(self) -> dict[str, int]:
        return {
            "queued": self.queue.qsize(),
            "written": self.written,
            "failed": self.failed,
            "dropped": self.dropped,
            "capped": self.capped,
        }


class BlobStore(ABC):
    name = "abstract"

    @abstractmethod
    async def put(
        self, container: str, name: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str: ...

    @abstractmethod
    async def get(self, container: str, name: str) -> bytes | None: ...

    @abstractmethod
    async def list(self, container: str, prefix: str = "", limit: int = 100) -> list[str]: ...

    @abstractmethod
    async def ping(self) -> dict[str, Any]: ...

    async def close(self) -> None:  # pragma: no cover
        return None


class MemoryBlobStore(BlobStore):
    name = "memory"

    def __init__(self) -> None:
        self._b: dict[tuple[str, str], tuple[bytes, str]] = {}

    async def put(self, container: str, name: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._b[(container, name)] = (data, content_type)
        return f"memory://{container}/{name}"

    async def get(self, container: str, name: str) -> bytes | None:
        v = self._b.get((container, name))
        return v[0] if v else None

    async def list(self, container: str, prefix: str = "", limit: int = 100) -> list[str]:
        return sorted(n for (c, n) in self._b if c == container and n.startswith(prefix))[:limit]

    async def ping(self) -> dict[str, Any]:
        t = time.perf_counter()
        await self.put("exports", "ready-probe.txt", b"ok", "text/plain")
        ok = await self.get("exports", "ready-probe.txt") == b"ok"
        return {
            "status": "ok" if ok else "fail",
            "backend": "memory",
            "latency_ms": round((time.perf_counter() - t) * 1000, 2),
        }


class AzureBlobStore(BlobStore):  # pragma: no cover - exercised against real Azure by the smoke test
    name = "azure-blob"

    def __init__(self, account_url: str, credential: Any) -> None:
        from azure.storage.blob.aio import BlobServiceClient

        self.account_url = account_url
        self._svc = BlobServiceClient(account_url, credential=credential)

    async def put(self, container: str, name: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        from azure.storage.blob import ContentSettings

        bc = self._svc.get_blob_client(container, name)
        await bc.upload_blob(data, overwrite=True, content_settings=ContentSettings(content_type=content_type))
        return bc.url

    async def get(self, container: str, name: str) -> bytes | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            stream = await self._svc.get_blob_client(container, name).download_blob()
            return await stream.readall()
        except ResourceNotFoundError:
            return None

    async def list(self, container: str, prefix: str = "", limit: int = 100) -> list[str]:
        out: list[str] = []
        async for b in self._svc.get_container_client(container).list_blobs(name_starts_with=prefix or None):
            out.append(b.name)
            if len(out) >= limit:
                break
        return out

    async def ping(self) -> dict[str, Any]:
        t = time.perf_counter()
        payload = datetime.now(UTC).isoformat().encode()
        await self.put("exports", "ready-probe.txt", payload, "text/plain")
        ok = await self.get("exports", "ready-probe.txt") == payload
        return {
            "status": "ok" if ok else "fail",
            "backend": "azure-blob",
            "account": self.account_url,
            "latency_ms": round((time.perf_counter() - t) * 1000, 2),
        }

    async def close(self) -> None:
        await self._svc.close()
