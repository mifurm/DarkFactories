"""Mandatory platform endpoints: /healthz, /readyz, /api/meta, /api/features, /api/usage, jobs + SSE, identity."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import __version__
from .core.jobs import render_job
from .deps import mutate_limit, svc
from .i18n import DEFAULT, LANGUAGE_NAMES, SUPPORTED, current_locale, label, t
from .registry import CATALOG, EPICS, registry_view
from .roles import PERMISSIONS, Role, get_actor, require
from .services import Services

router = APIRouter()


@router.get("/healthz", tags=["platform"])
async def healthz() -> dict[str, Any]:
    return {"status": "ok", "version": __version__}


async def _timed(name: str, coro: Any, timeout: float = 25.0) -> tuple[str, dict[str, Any]]:  # noqa: ASYNC109 - per-probe deadline, enforced with asyncio.wait_for
    t0 = time.perf_counter()
    try:
        detail = await asyncio.wait_for(coro, timeout)
        return name, {"ok": True, "ms": round((time.perf_counter() - t0) * 1000, 1), **(detail or {})}
    except Exception as exc:
        return name, {"ok": False, "ms": round((time.perf_counter() - t0) * 1000, 1), "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


async def _ffmpeg() -> dict[str, Any]:
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("ffmpeg not found on PATH")
    out = (await asyncio.to_thread(subprocess.run, [path, "-version"], capture_output=True, text=True, timeout=10)).stdout.splitlines()[0]
    return {"binary": path, "version": out[:60]}


@router.get("/readyz", tags=["platform"])
async def readyz(request: Request, deep: bool = False) -> JSONResponse:
    s = svc(request)
    cached = s.ready_cache.get("v")
    if cached and not deep and time.time() - cached["at"] < 45:
        return JSONResponse(cached["body"], status_code=cached["code"])
    results = dict(
        await asyncio.gather(
            _timed("repository", s.repo.ping()),
            _timed("blob_storage", s.blobs.ping()),
            _timed("openai_chat", s.llm.ping()),
            _timed("content_safety", s.safety.ping()),
            _timed("speech", s.speech.ping()),
            _timed("ffmpeg", _ffmpeg()),
        )
    )
    ok = all(v["ok"] for v in results.values())
    body = {"status": "ready" if ok else "degraded", "mode": s.settings.mode, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dependencies": results}
    code = 200 if ok else 503
    s.ready_cache["v"] = {"at": time.time(), "body": body, "code": code}
    return JSONResponse(body, status_code=code)


@router.get("/api/meta", tags=["platform"])
async def meta(request: Request) -> dict[str, Any]:
    s = svc(request)
    st = s.settings
    return {
        "name": st.app_name,
        "product": "Spotlight",
        "version": __version__,
        "build_id": st.build_id,
        "mode": st.mode,
        "region": st.azure_region,
        "instance": st.instance_id,
        "uptime_s": round(time.time() - s.started_at, 1),
        "languages": list(SUPPORTED),
        "default_language": DEFAULT,
        "language": current_locale(),
        "language_names": dict(LANGUAGE_NAMES),
        "backends": {
            "repository": s.repo.mode,
            "blob_storage": s.blobs.mode,
            "llm": s.llm.mode,
            "image": s.image.mode,
            "speech": s.speech.mode,
            "embeddings": s.embeddings.mode,
            "content_safety": s.safety.mode,
            "video_provider": st.video_provider,
        },
        "models": st.models if st.mode == "azure" else {k: f"{v} (simulated)" for k, v in st.models.items()},
        "synthetic_data": True,
        "limits": {
            "daily_ai_budget_usd": st.daily_ai_budget_usd,
            "campaign_ai_budget_usd": st.campaign_ai_budget_usd,
            "max_body_bytes": st.max_body_bytes,
        },
        "disclaimer": t("meta.disclaimer"),
    }


@router.get("/api/features", tags=["platform"])
async def features(request: Request) -> list[dict[str, Any]]:
    return registry_view(request.app.state.features)


@router.get("/api/features/epics", tags=["platform"])
async def epics() -> dict[str, Any]:
    return {"epics": EPICS, "total": len(CATALOG)}


@router.get("/api/me", tags=["platform"])
async def me(request: Request) -> dict[str, Any]:
    actor = get_actor(request)
    return {
        "actor": {**actor.to_dict(), "label": label("label.role", actor.role.value)},
        "permissions": sorted(p for p, roles in PERMISSIONS.items() if actor.role in roles),
        "roles": [{"id": r.value, "label": label("label.role", r.value)} for r in Role],
        "auth": t("me.auth"),
    }


@router.get("/api/usage", tags=["platform"])
async def usage(request: Request, campaign_id: str | None = None) -> dict[str, Any]:
    s = svc(request)
    summary = await s.meter.summary(campaign_id=campaign_id)
    caps = await s.guard.caps(campaign_id)
    return {**summary, "budget": caps, "cache": s.cache.stats(), "guard_refusals": s.guard.refusals}


@router.get("/api/jobs", tags=["platform"])
async def list_jobs(request: Request, campaign_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    return [render_job(j) for j in await svc(request).jobs.list(campaign_id, min(limit, 100))]


@router.get("/api/jobs/{job_id}", tags=["platform"])
async def get_job(request: Request, job_id: str) -> dict[str, Any]:
    return render_job(await svc(request).jobs.require(job_id))


@router.post("/api/jobs/{job_id}/cancel", tags=["platform"], dependencies=[Depends(mutate_limit)])
async def cancel_job(request: Request, job_id: str, _: Any = Depends(require("generate"))) -> dict[str, Any]:
    return render_job(await svc(request).jobs.cancel(job_id))


@router.get("/api/stream/jobs/{job_id}", tags=["platform"])
async def stream_job(request: Request, job_id: str) -> StreamingResponse:
    s: Services = svc(request)
    await s.jobs.require(job_id)

    async def gen():
        async for ev in s.jobs.stream(job_id):
            if await request.is_disconnected():
                return
            yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'], default=str)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
