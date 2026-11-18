"""Background job runner with persisted state and live progress (SSE).

Long work (image generation, voice-over, renders, localization, exports) never blocks request handlers:
jobs run as asyncio tasks (CPU-heavy parts hand off to subprocesses/threads) and persist progress to the
repository so any replica can serve status/SSE.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from ..errors import AppError, NotFound
from ..i18n import DEFAULT, current_locale, t
from ..util import new_id, now, now_iso, parse_iso
from .ai.base import reset_ctx, set_ctx

log = logging.getLogger("spotlight.jobs")
TERMINAL = {"succeeded", "failed", "cancelled"}
HEARTBEAT_S = 15.0  # a live job rewrites its heartbeat this often: a long cinematic render (~25 min) must not look dead to the other replicas
STALE_AFTER_S = 120.0  # a job of another replica without a heartbeat for this long is orphaned (that replica was scaled in or restarted)
LANES = {"motion": 1}  # jobs that wait on the GPU worker run in their own lane: a 25-minute render does not use up the general slots


def _jsonable(params: dict[str, Any] | None) -> dict[str, Any]:
    return json.loads(json.dumps(params or {}, default=str))


def _set_message(doc: dict[str, Any], key: str, params: dict[str, Any] | None = None) -> None:
    """Store a progress/state message as catalog key + params (plus its English text) so any viewer can read it in their language."""
    p = _jsonable(params)
    doc["message"], doc["message_key"], doc["message_params"] = t(key, DEFAULT, **p), key, p


def render_job(j: dict[str, Any], locale: str | None = None) -> dict[str, Any]:
    """A job as served to clients: title, message, error and hint rendered in ``locale`` from the stored catalog keys.

    English (the language the text is stored in) and records without keys come back exactly as stored; ids, status and numbers never change."""
    loc = locale or current_locale()
    out = dict(j)
    if loc == DEFAULT:
        return out
    if j.get("title_key"):
        out["title"] = t(j["title_key"], loc, **(j.get("title_params") or {}))
    if j.get("message_key"):
        out["message"] = t(j["message_key"], loc, **(j.get("message_params") or {}))
    if j.get("status") == "failed" and j.get("error_code") and "error_params" in j:
        msg, hint = AppError(j.get("error") or "", code=j["error_code"], hint=j.get("error_hint"), params=j.get("error_params"), key=j.get("error_key") or None).localized(loc)
        out.update(error=msg, error_hint=hint, message=msg)
    return out


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, runner: JobRunner, doc: dict[str, Any]) -> None:
        self._runner = runner
        self.doc = doc
        self.id: str = doc["id"]
        self.campaign_id: str | None = doc.get("campaign_id")
        self._last_flush = 0.0

    async def progress(self, pct: float | None = None, message: str | None = None, step: str | None = None, *, key: str | None = None, params: dict[str, Any] | None = None, force: bool = False) -> None:
        """Report progress. ``key`` (+ ``params``) names a ``job.msg.*`` catalog entry so the message is shown in the viewer's language; a plain ``message`` stays as written."""
        if self.doc.get("cancel_requested"):
            raise JobCancelled()
        if pct is not None:
            self.doc["progress"] = round(max(0.0, min(1.0, pct)), 4)
        if key is not None:
            _set_message(self.doc, key, params)
        elif message is not None:
            self.doc["message"] = message
            self.doc.pop("message_key", None)
            self.doc.pop("message_params", None)
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
    def __init__(
        self, repo: Any, *, max_concurrent: int = 2, instance_id: str = "local", on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        heartbeat_s: float = HEARTBEAT_S, stale_after_s: float = STALE_AFTER_S, lanes: dict[str, int] | None = None,
    ) -> None:
        self.repo = repo
        self.instance_id = instance_id
        self.heartbeat_s = heartbeat_s
        self.stale_after_s = stale_after_s
        self._sem = asyncio.Semaphore(max_concurrent)
        self._lanes = {name: asyncio.Semaphore(n) for name, n in {**LANES, **(lanes or {})}.items()}
        self._live: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._sweeper: asyncio.Task | None = None
        self.on_event = on_event

    async def _persist(self, doc: dict[str, Any]) -> None:
        self._live[doc["id"]] = doc
        await self.repo.upsert("jobs", dict(doc))

    def _alive(self, d: dict[str, Any]) -> bool:
        """Did the replica that owns this job write a heartbeat / progress recently?"""
        ts = parse_iso(d.get("heartbeat_at") or d.get("updated_at") or d.get("created_at"))
        return ts is not None and (now() - ts).total_seconds() < self.stale_after_s

    async def reconcile_startup(self) -> int:
        """Jobs left 'running' by a previous process can never finish — mark them as interrupted.

        A job that another replica is still working on (recent heartbeat) is left alone: a second replica starting up must not fail a long render of the first."""
        n = 0
        for st in ("queued", "running"):
            for d in await self.repo.query("jobs", {"status": st}):
                mine = d.get("owner") == self.instance_id
                if (mine and d["id"] in self._tasks) or (not mine and self._alive(d)):
                    continue
                d.update(status="failed", error="interrupted by restart/scale-in", finished_at=now_iso())
                _set_message(d, "job.state.interrupted")
                await self.repo.upsert("jobs", d)
                n += 1
        return n

    def start_sweeper(self, interval_s: float | None = None) -> None:
        """Periodically fail the jobs of replicas that disappeared (no heartbeat for ``stale_after_s``), so a restarted app never leaves a spinner behind."""
        if self._sweeper is None or self._sweeper.done():
            self._sweeper = asyncio.create_task(self._sweep_loop(interval_s or max(5.0, self.stale_after_s / 2)))

    async def _sweep_loop(self, interval_s: float) -> None:
        while True:
            await asyncio.sleep(interval_s)
            with contextlib.suppress(Exception):
                await self.reconcile_startup()

    async def _beat(self, doc: dict[str, Any]) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_s)
            if doc.get("status") in TERMINAL:
                return
            doc["heartbeat_at"] = now_iso()
            with contextlib.suppress(Exception):
                await self._persist(doc)

    async def submit(self, kind: str, fn: JobFn, *, campaign_id: str | None = None, title: str = "", feature: str | None = None, meta: dict[str, Any] | None = None, title_key: str | None = None, title_params: dict[str, Any] | None = None, lane: str | None = None) -> dict[str, Any]:
        """Queue a job. ``title_key`` (+ ``title_params``) names a ``job.title.*`` catalog entry so the title is shown in the viewer's language.
        ``lane`` puts the job in a dedicated concurrency lane (``motion``: waits on the GPU worker) instead of the general slots."""
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
        if lane:
            doc["lane"] = lane
        if title_key:
            params = _jsonable(title_params)
            doc.update(title=t(title_key, DEFAULT, **params), title_key=title_key, title_params=params)
        _set_message(doc, "job.state.queued")
        await self._persist(doc)
        self._tasks[doc["id"]] = asyncio.create_task(self._run(doc, fn, feature))
        return dict(doc)

    async def _run(self, doc: dict[str, Any], fn: JobFn, feature: str | None) -> None:
        ctx = JobContext(self, doc)
        beat = asyncio.create_task(self._beat(doc))
        try:
            async with self._lanes.get(doc.get("lane") or "", self._sem):
                tok = set_ctx(campaign_id=doc.get("campaign_id"), feature=feature or doc["kind"], ref=doc["id"])
                try:
                    doc.update(status="running", started_at=now_iso())
                    _set_message(doc, "job.state.running")
                    await self._persist(doc)
                    result = await fn(ctx)
                    doc.update(status="succeeded", progress=1.0, result=result or {}, finished_at=now_iso())
                    _set_message(doc, "job.state.done")
                finally:
                    reset_ctx(tok)
        except JobCancelled:
            doc.update(status="cancelled", finished_at=now_iso())
            _set_message(doc, "job.state.cancelled")
        except asyncio.CancelledError:
            beat.cancel()
            doc.update(status="cancelled", finished_at=now_iso())
            _set_message(doc, "job.state.cancelled")
            await self._persist(doc)
            raise
        except AppError as exc:
            doc.update(status="failed", error=exc.message, error_code=exc.code, error_hint=exc.hint, error_key=exc.key or "", error_params=_jsonable(exc.params), message=exc.message, finished_at=now_iso())
            doc.pop("message_key", None)
            doc.pop("message_params", None)
        except Exception as exc:
            log.exception("job %s failed", doc["id"])
            doc.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:500], error_code="internal_error", finished_at=now_iso())
            _set_message(doc, "job.state.failed")
        beat.cancel()
        await self._persist(doc)
        if self.on_event:
            with contextlib.suppress(Exception):
                await self.on_event(f"job.{doc['status']}", {"job_id": doc["id"], "kind": doc["kind"], "campaign_id": doc.get("campaign_id"), "title": render_job(doc)["title"]})
        self._tasks.pop(doc["id"], None)

    async def get(self, job_id: str) -> dict[str, Any] | None:
        if job_id in self._live and self._live[job_id].get("status") not in TERMINAL:
            return dict(self._live[job_id])
        return await self.repo.get("jobs", job_id)

    async def require(self, job_id: str) -> dict[str, Any]:
        j = await self.get(job_id)
        if not j:
            raise NotFound(f"job {job_id} not found", code="job_not_found", params={"id": job_id})
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

    async def stream(self, job_id: str, poll: float = 0.6, keepalive_s: float = 15.0) -> AsyncIterator[dict[str, Any]]:
        """Progress events as they change, plus a ``ping`` every ``keepalive_s`` of silence (a cold GPU start can be quiet for minutes; an idle SSE connection would be cut by proxies)."""
        last = ""
        last_emit = time.monotonic()
        while True:
            j = await self.get(job_id)
            if j is None:
                yield {"event": "error", "data": {"message": "job not found"}}
                return
            snap = f"{j['status']}|{j.get('progress')}|{j.get('message')}|{len(j.get('steps', []))}"
            if snap != last:
                last = snap
                last_emit = time.monotonic()
                yield {"event": "progress", "data": _public(j)}
            elif time.monotonic() - last_emit >= keepalive_s:
                last_emit = time.monotonic()
                yield {"event": "ping", "data": {}}
            if j["status"] in TERMINAL:
                yield {"event": "done", "data": _public(j)}
                return
            await asyncio.sleep(poll)

    async def shutdown(self) -> None:
        if self._sweeper is not None:
            self._sweeper.cancel()
        for task in list(self._tasks.values()):
            task.cancel()
        for task in list(self._tasks.values()):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


def _public(j: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in render_job(j).items() if k not in {"owner", "cancel_requested"}}
