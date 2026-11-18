"""Background job runner with persisted state and live progress (SSE).

Long work (image generation, voice-over, renders, localization, exports) never blocks request handlers:
jobs run as asyncio tasks (CPU-heavy parts hand off to subprocesses/threads) and persist progress to the
repository so any replica can serve status/SSE.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from ..errors import AppError, NotFound
from ..util import new_id, now_iso
from .ai.base import reset_ctx, set_ctx

log = logging.getLogger("spotlight.jobs")
TERMINAL = {"succeeded", "failed", "cancelled"}


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, runner: JobRunner, doc: dict[str, Any]) -> None:
        self._runner = runner
        self.doc = doc
        self.id: str = doc["id"]
        self.campaign_id: str | None = doc.get("campaign_id")
        self._last_flush = 0.0

    async def progress(self, pct: float | None = None, message: str | None = None, step: str | None = None, *, force: bool = False) -> None:
        if self.doc.get("cancel_requested"):
            raise JobCancelled()
        if pct is not None:
            self.doc["progress"] = round(max(0.0, min(1.0, pct)), 4)
        if message is not None:
            self.doc["message"] = message
        if step is not None:
            self.doc["step"] = step
            self.doc.setdefault("steps", []).append({"name": step, "at": now_iso(), "progress": self.doc.get("progress", 0)})
        self.doc["updated_at"] = now_iso()
        now = time.monotonic()
        if force or step is not None or now - self._last_flush > 0.4:
            self._last_flush = now
            await self._runner._persist(self.doc)

    async def add_cost(self, usd: float) -> None:
        self.doc["cost_usd"] = round(self.doc.get("cost_usd", 0.0) + usd, 6)


JobFn = Callable[[JobContext], Awaitable[dict[str, Any] | None]]


class JobRunner:
    def __init__(self, repo: Any, *, max_concurrent: int = 2, instance_id: str = "local", on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None) -> None:
        self.repo = repo
        self.instance_id = instance_id
        self._sem = asyncio.Semaphore(max_concurrent)
        self._live: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self.on_event = on_event

    async def _persist(self, doc: dict[str, Any]) -> None:
        self._live[doc["id"]] = doc
        await self.repo.upsert("jobs", dict(doc))

    async def reconcile_startup(self) -> int:
        """Jobs left 'running' by a previous process can never finish — mark them as interrupted."""
        n = 0
        for st in ("queued", "running"):
            for d in await self.repo.query("jobs", {"status": st}):
                if d.get("owner") != self.instance_id or d["id"] not in self._tasks:
                    d.update(status="failed", error="interrupted by restart/scale-in", message="Interrupted — please retry", finished_at=now_iso())
                    await self.repo.upsert("jobs", d)
                    n += 1
        return n

    async def submit(self, kind: str, fn: JobFn, *, campaign_id: str | None = None, title: str = "", feature: str | None = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "id": new_id("job"),
            "pk": campaign_id or "global",
            "kind": kind,
            "title": title or kind,
            "campaign_id": campaign_id,
            "feature": feature,
            "status": "queued",
            "progress": 0.0,
            "message": "Queued",
            "steps": [],
            "result": None,
            "error": None,
            "cost_usd": 0.0,
            "owner": self.instance_id,
            "meta": meta or {},
            "created_at": now_iso(),
        }
        await self._persist(doc)
        self._tasks[doc["id"]] = asyncio.create_task(self._run(doc, fn, feature))
        return dict(doc)

    async def _run(self, doc: dict[str, Any], fn: JobFn, feature: str | None) -> None:
        ctx = JobContext(self, doc)
        try:
            async with self._sem:
                tok = set_ctx(campaign_id=doc.get("campaign_id"), feature=feature or doc["kind"], ref=doc["id"])
                try:
                    doc.update(status="running", started_at=now_iso(), message="Running")
                    await self._persist(doc)
                    result = await fn(ctx)
                    doc.update(status="succeeded", progress=1.0, result=result or {}, message="Done", finished_at=now_iso())
                finally:
                    reset_ctx(tok)
        except JobCancelled:
            doc.update(status="cancelled", message="Cancelled", finished_at=now_iso())
        except asyncio.CancelledError:
            doc.update(status="cancelled", message="Cancelled", finished_at=now_iso())
            await self._persist(doc)
            raise
        except AppError as exc:
            doc.update(status="failed", error=exc.message, error_code=exc.code, error_hint=exc.hint, message=exc.message, finished_at=now_iso())
        except Exception as exc:
            log.exception("job %s failed", doc["id"])
            doc.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:500], error_code="internal_error", message="Job failed", finished_at=now_iso())
        await self._persist(doc)
        if self.on_event:
            with contextlib.suppress(Exception):
                await self.on_event(f"job.{doc['status']}", {"job_id": doc["id"], "kind": doc["kind"], "campaign_id": doc.get("campaign_id"), "title": doc.get("title")})
        self._tasks.pop(doc["id"], None)

    async def get(self, job_id: str) -> dict[str, Any] | None:
        if job_id in self._live and self._live[job_id].get("status") not in TERMINAL:
            return dict(self._live[job_id])
        return await self.repo.get("jobs", job_id)

    async def require(self, job_id: str) -> dict[str, Any]:
        j = await self.get(job_id)
        if not j:
            raise NotFound(f"job {job_id} not found", code="job_not_found")
        return j

    async def list(self, campaign_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self.repo.query("jobs", {"campaign_id": campaign_id} if campaign_id else None, order_by="created_at", desc=True, limit=limit)
        return [self._live.get(r["id"], r) if self._live.get(r["id"], {}).get("status") not in TERMINAL else r for r in rows]

    async def cancel(self, job_id: str) -> dict[str, Any]:
        j = await self.require(job_id)
        if j["status"] in TERMINAL:
            return j
        if job_id in self._live:
            self._live[job_id]["cancel_requested"] = True
        t = self._tasks.get(job_id)
        if t and not t.done() and self._live.get(job_id, {}).get("status") == "queued":
            t.cancel()
        return await self.require(job_id)

    async def wait(self, job_id: str, timeout: float = 120.0) -> dict[str, Any]:  # noqa: ASYNC109 - bounded wait for a job to finish
        t = self._tasks.get(job_id)
        if t:
            await asyncio.wait_for(asyncio.shield(t), timeout)
        return await self.require(job_id)

    async def stream(self, job_id: str, poll: float = 0.6) -> AsyncIterator[dict[str, Any]]:
        last = ""
        while True:
            j = await self.get(job_id)
            if j is None:
                yield {"event": "error", "data": {"message": "job not found"}}
                return
            snap = f"{j['status']}|{j.get('progress')}|{j.get('message')}|{len(j.get('steps', []))}"
            if snap != last:
                last = snap
                yield {"event": "progress", "data": _public(j)}
            if j["status"] in TERMINAL:
                yield {"event": "done", "data": _public(j)}
                return
            await asyncio.sleep(poll)

    async def shutdown(self) -> None:
        for t in list(self._tasks.values()):
            t.cancel()
        for t in list(self._tasks.values()):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t


def _public(j: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in j.items() if k not in {"owner", "cancel_requested"}}
