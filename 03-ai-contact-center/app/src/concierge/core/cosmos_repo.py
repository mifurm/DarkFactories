"""Cosmos DB (NoSQL, serverless) repository using Entra RBAC - no keys, no connection strings."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from azure.core.exceptions import ResourceNotFoundError
from azure.cosmos.aio import CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError

from .collections import COLLECTIONS, partition_key
from .repo import Repository, Where, prepare

_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_SYSTEM_KEYS = ("_rid", "_self", "_etag", "_attachments")


def _fld(path: str) -> str:
    if not _FIELD.match(path):
        raise ValueError(f"illegal field path '{path}'")
    return "c" + "".join(f'["{p}"]' for p in path.split("."))


def build_query(where: Where | None, order_by: str | None, desc: bool, limit: int | None) -> tuple[str, list[dict]]:
    clauses: list[str] = []
    params: list[dict] = []

    def param(value: Any) -> str:
        name = f"@p{len(params)}"
        params.append({"name": name, "value": value})
        return name

    for path, cond in (where or {}).items():
        f = _fld(path)
        if isinstance(cond, dict) and cond and all(k.startswith("$") for k in cond):
            for op, arg in cond.items():
                if op == "$ne":
                    clauses.append(f"{f} != {param(arg)}")
                elif op in ("$gt", "$gte", "$lt", "$lte"):
                    sym = {"$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}[op]
                    clauses.append(f"{f} {sym} {param(arg)}")
                elif op == "$in":
                    clauses.append(f"ARRAY_CONTAINS({param(list(arg))}, {f})")
                elif op == "$nin":
                    clauses.append(f"NOT ARRAY_CONTAINS({param(list(arg))}, {f})")
                elif op == "$contains":
                    clauses.append(f"(IS_ARRAY({f}) ? ARRAY_CONTAINS({f}, {param(arg)}) : CONTAINS({f}, {param(arg)}))")
                elif op == "$exists":
                    clauses.append(f"{'IS_DEFINED' if arg else 'NOT IS_DEFINED'}({f})")
                else:
                    raise ValueError(f"unsupported operator {op}")
        else:
            clauses.append(f"{f} = {param(cond)}")
    sql = "SELECT * FROM c"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    if order_by:
        sql += f" ORDER BY {_fld(order_by)} {'DESC' if desc else 'ASC'}"
    if limit is not None:
        sql += f" OFFSET 0 LIMIT {int(limit)}"
    return sql, params


class CosmosRepository(Repository):
    kind = "cosmos"

    def __init__(self, endpoint: str, database: str, credential: Any) -> None:
        self._endpoint = endpoint
        self._dbname = database
        self._client = CosmosClient(endpoint, credential=credential)
        self._db = self._client.get_database_client(database)
        self._containers: dict[str, Any] = {}
        self._sem = asyncio.Semaphore(16)

    def _c(self, coll: str):
        if coll not in COLLECTIONS:
            raise KeyError(f"unknown collection '{coll}'")
        if coll not in self._containers:
            self._containers[coll] = self._db.get_container_client(coll)
        return self._containers[coll]

    @staticmethod
    def _clean(doc: dict) -> dict:
        return {k: v for k, v in doc.items() if k not in _SYSTEM_KEYS}

    async def put(self, coll: str, doc: dict, *, ttl: int | None = None) -> dict:
        body = prepare(coll, doc, ttl)
        async with self._sem:
            res = await self._c(coll).upsert_item(body)
        return self._clean(res)

    async def put_many(self, coll: str, docs) -> int:
        docs = list(docs)
        await asyncio.gather(*(self.put(coll, d) for d in docs))
        return len(docs)

    async def get(self, coll: str, doc_id: str) -> dict | None:
        try:
            res = await self._c(coll).read_item(item=doc_id, partition_key=partition_key(coll, doc_id))
        except (CosmosResourceNotFoundError, ResourceNotFoundError):
            return None
        return self._clean(res)

    async def delete(self, coll: str, doc_id: str) -> bool:
        try:
            await self._c(coll).delete_item(item=doc_id, partition_key=partition_key(coll, doc_id))
            return True
        except (CosmosResourceNotFoundError, ResourceNotFoundError):
            return False

    async def query(
        self,
        coll: str,
        where: Where | None = None,
        *,
        order_by: str | None = None,
        desc: bool = False,
        limit: int | None = None,
    ) -> list[dict]:
        sql, params = build_query(where, order_by, desc, limit)
        kwargs: dict[str, Any] = {"query": sql, "parameters": params}
        if COLLECTIONS[coll] == "const":
            kwargs["partition_key"] = coll
        out: list[dict] = []
        async with self._sem:
            async for item in self._c(coll).query_items(**kwargs):
                out.append(self._clean(item))
        return out

    async def count(self, coll: str, where: Where | None = None) -> int:
        sql, params = build_query(where, None, False, None)
        sql = sql.replace("SELECT * FROM c", "SELECT VALUE COUNT(1) FROM c", 1)
        kwargs: dict[str, Any] = {"query": sql, "parameters": params}
        if COLLECTIONS[coll] == "const":
            kwargs["partition_key"] = coll
        async for item in self._c(coll).query_items(**kwargs):
            return int(item)
        return 0

    async def ping(self) -> dict:
        try:
            props = await self._db.read()
            return {"ok": True, "kind": self.kind, "database": props.get("id", self._dbname)}
        except CosmosHttpResponseError as exc:  # pragma: no cover - network path
            return {"ok": False, "kind": self.kind, "error": f"{exc.status_code} {exc.reason}"}

    async def close(self) -> None:
        await self._client.close()
