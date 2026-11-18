"""Mandatory platform endpoints: /healthz, /readyz, /api/meta, /api/features, /api/usage."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from nightshift.core.deps import get_rt

router = APIRouter()


@router.get("/healthz", tags=["platform"])
async def healthz(request: Request) -> dict[str, Any]:
    rt = get_rt(request)
    return {"status": "ok", "uptime_s": round(__import__("time").time() - rt.started_at, 1)}


@router.get("/readyz", tags=["platform"])
async def readyz(request: Request, fresh: bool = False) -> JSONResponse:
    rt = get_rt(request)
    body = await rt.readiness(fresh=fresh)
    return JSONResponse(body, status_code=200 if body["status"] == "ready" else 503)


@router.get("/api/meta", tags=["platform"])
async def meta(request: Request) -> dict[str, Any]:
    return get_rt(request).meta()


@router.get("/api/features", tags=["platform"])
async def features(request: Request) -> list[dict[str, Any]]:
    return [f.spec.public() for f in get_rt(request).features]


@router.get("/api/usage", tags=["platform"])
async def usage(request: Request) -> dict[str, Any]:
    rt = get_rt(request)
    snap = rt.usage.snapshot()
    snap["mode"] = rt.settings.mode
    snap["write_behind"] = rt.writer.stats()
    return snap
