"""Cosmos DB for NoSQL repository (serverless, Entra RBAC — no keys)."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Sequence
from typing import Any

from azure.cosmos import exceptions as cex
from azure.cosmos.aio import CosmosClient

from ...errors import Conflict
from ...util import now_iso
from . import COLLECTIONS, Where, default_pk, validate_field


def _strip(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def build_query(
    where: Where | None, order_by: str | None, desc: bool, limit: int | None, select: str = "*"
) -> tuple[str, list[dict[str, Any]]]:
    clauses: list[str] = []
    params: list[dict[str, Any]] = []

    def p(value: Any) -> str:
        name = f"@p{len(params)}"
        params.append({"name": name, "value": value})
        return name

    for field, cond in (where or {}).items():
        col = "c." + validate_field(field)
        if isinstance(cond, dict) and cond and all(k.startswith("$") for k in cond):
            for op, arg in cond.items():
                if op == "$in":
                    clauses.append(f"ARRAY_CONTAINS({p(list(arg))}, {col})")
                elif op == "$nin":
                    clauses.append(f"NOT ARRAY_CONTAINS({p(list(arg))}, {col})")
                elif op == "$ne":
                    clauses.append(f"{col} != {p(arg)}")
                elif op == "$gte":
                    clauses.append(f"{col} >= {p(arg)}")
                elif op == "$lte":
                    clauses.append(f"{col} <= {p(arg)}")
                elif op == "$gt":
                    clauses.append(f"{col} > {p(arg)}")
                elif op == "$lt":
                    clauses.append(f"{col} < {p(arg)}")
                elif op == "$contains":
                    clauses.append(f"ARRAY_CONTAINS({col}, {p(arg)})")
                elif op == "$exists":
                    clauses.append(f"IS_DEFINED({col})" if arg else f"NOT IS_DEFINED({col})")
                else:
                    raise ValueError(f"unsupported operator {op}")
        else:
            clauses.append(f"{col} = {p(cond)}")
    sql = f"SELECT {'TOP ' + str(int(limit)) + ' ' if limit and not order_by else ''}{select} FROM c"  # noqa: S608 - only validated identifiers and integers are interpolated; values are bound parameters
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    if order_by:
        sql += f" ORDER BY c.{validate_field(order_by)} {'DESC' if desc else 'ASC'}"
        if limit:
            sql += f" OFFSET 0 LIMIT {int(limit)}"
    return sql, params


class CosmosRepository:
    mode = "cosmos"

    def __init__(self, endpoint: str, database: str, credential: Any) -> None:
        self._endpoint = endpoint
        self._database = database
        self._credential = credential
        self._client: CosmosClient | None = None
        self._containers: dict[str, Any] = {}

    def _container(self, name: str) -> Any:
        if self._client is None:
            self._client = CosmosClient(self._endpoint, credential=self._credential)
        if name not in self._containers:
            if name not in COLLECTIONS:
                raise ValueError(f"unknown collection {name!r}")
            self._containers[name] = self._client.get_database_client(self._database).get_container_client(name)
        return self._containers[name]

    async def create(self, collection: str, doc: dict[str, Any]) -> dict[str, Any]:
        doc = copy.deepcopy(doc)
        doc["pk"] = default_pk(doc)
        doc.setdefault("created_at", now_iso())
        try:
            res = await self._container(collection).create_item(doc)
        except cex.CosmosResourceExistsError as exc:
            raise Conflict(f"{collection}/{doc['id']} already exists", params={"collection": collection, "id": doc["id"]}) from exc
        return _strip(res)

    async def upsert(self, collection: str, doc: dict[str, Any]) -> dict[str, Any]:
        doc = copy.deepcopy(doc)
        doc["pk"] = default_pk(doc)
        doc.setdefault("created_at", now_iso())
        doc["updated_at"] = now_iso()
        res = await self._container(collection).upsert_item(doc)
        return _strip(res)

    async def get(self, collection: str, doc_id: str, pk: str | None = None) -> dict[str, Any] | None:
        c = self._container(collection)
        if pk is not None:
            try:
                return _strip(await c.read_item(item=doc_id, partition_key=pk))
            except cex.CosmosResourceNotFoundError:
                return None
        rows = [r async for r in c.query_items("SELECT * FROM c WHERE c.id = @id", parameters=[{"name": "@id", "value": doc_id}])]
        return _strip(rows[0]) if rows else None

    async def delete(self, collection: str, doc_id: str, pk: str | None = None) -> bool:
        c = self._container(collection)
        if pk is None:
            doc = await self.get(collection, doc_id)
            if not doc:
                return False
            pk = doc["pk"]
        try:
            await c.delete_item(item=doc_id, partition_key=pk)
            return True
        except cex.CosmosResourceNotFoundError:
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
        select = ", ".join("c." + validate_field(f) for f in fields) if fields else "*"
        sql, params = build_query(where, order_by, desc, limit, select=select)
        kwargs: dict[str, Any] = {"parameters": params}
        if pk is not None:
            kwargs["partition_key"] = pk
        return [_strip(r) async for r in self._container(collection).query_items(sql, **kwargs)]

    async def count(self, collection: str, where: Where | None = None, *, pk: str | None = None) -> int:
        sql, params = build_query(where, None, False, None, select="VALUE COUNT(1)")
        kwargs: dict[str, Any] = {"parameters": params}
        if pk is not None:
            kwargs["partition_key"] = pk
        rows = [r async for r in self._container(collection).query_items(sql, **kwargs)]
        return int(sum(rows))

    async def upsert_many(self, collection: str, docs: list[dict[str, Any]], concurrency: int = 16) -> int:
        sem = asyncio.Semaphore(concurrency)

        async def one(d: dict[str, Any]) -> None:
            async with sem:
                await self.upsert(collection, d)

        await asyncio.gather(*(one(d) for d in docs))
        return len(docs)

    async def ping(self) -> dict[str, Any]:
        rows = [r async for r in self._container("settings").query_items("SELECT TOP 1 c.id FROM c")]
        return {"ok": True, "backend": "cosmos", "database": self._database, "probe_rows": len(rows)}

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
            self._containers.clear()
