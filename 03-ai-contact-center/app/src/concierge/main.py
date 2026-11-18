"""FastAPI application factory: feature auto-discovery, mandatory endpoints, hardening, SPA hosting."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .core.ai.base import BudgetExceededError
from .core.config import APP_NAME, APP_VERSION, STARTED_AT, Settings, load_settings
from .core.rbac import require
from .core.registry import discover_features
from .core.security import SecurityMiddleware
from .core.telemetry import configure_azure_monitor_if_enabled, configure_logging, instrument_app
from .services import Services, build_services

log = logging.getLogger("concierge")
SEED_VERSION = "1"


async def run_seed(svc: Services, force: bool = False) -> dict[str, Any]:
    """Run every feature seeder. Seeders are idempotent upserts and skip heavy work when their data already exists."""
    state = svc.seed_state
    state.update({"status": "running", "started": time.time(), "finished": None, "steps": {}})
    try:
        for order, name, fn in svc.registry.seeders if svc.registry else []:
            t0 = time.time()
            try:
                result = await fn(svc, force)
                state["steps"][name] = {"ok": True, "order": order, "seconds": round(time.time() - t0, 2), "result": result}
            except Exception as exc:  # keep going: one failing seeder must not take the app down
                log.exception("seeder %s failed", name)
                state["steps"][name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        ok = all(s.get("ok") for s in state["steps"].values())
        await svc.repo.put("seed_meta", {"id": "seed", "version": SEED_VERSION, "ts": time.time(), "ok": ok, "steps": list(state["steps"])})
        state.update({"status": "done" if ok else "degraded", "finished": time.time()})
    except Exception as exc:
        log.exception("seed failed")
        state.update({"status": "error", "error": str(exc)[:300], "finished": time.time()})
    return state


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging()
    otel_on = configure_azure_monitor_if_enabled(settings)
    registry = discover_features()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc = services or build_services(settings)
        svc.registry = registry
        svc.traces.export_otel = otel_on
        app.state.services = svc
        await svc.start()
        for _name, fn in registry.startups:
            await fn(svc)
        if settings.seed_on_start:
            svc.spawn(run_seed(svc))
        else:
            svc.seed_state["status"] = "disabled"
        svc.spawn(_flusher(svc))
        log.info("concierge started", extra={"mode": settings.mode, "features": len(registry.features), "build": settings.build_id})
        yield
        await svc.stop()

    app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan, docs_url="/docs", redoc_url=None)
    app.add_middleware(SecurityMiddleware, settings=settings)
    # tests build the app without running lifespan; keep a handle either way
    if services is not None:
        services.registry = registry
        app.state.services = services

    @app.exception_handler(BudgetExceededError)
    async def _budget(_: Request, exc: BudgetExceededError) -> JSONResponse:
        return JSONResponse(status_code=429, content={"error": "daily_ai_budget_exceeded", "message": str(exc), "cap_usd": exc.cap, "spent_usd": round(exc.spent, 4)})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", extra={"path": request.url.path})
        return JSONResponse(status_code=500, content={"error": "internal_error", "request_id": getattr(request.state, "request_id", "-")})

    def svc_of(request: Request) -> Services:
        return request.app.state.services

    # ---- mandatory endpoints --------------------------------------------------------------
    @app.get("/healthz", tags=["platform"])
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "uptime_s": round(time.time() - STARTED_AT, 1)}

    @app.get("/readyz", tags=["platform"])
    async def readyz(request: Request, fresh: bool = False) -> JSONResponse:
        svc = svc_of(request)
        cached = svc.ready_cache.get("v")
        if cached and not fresh and time.time() - cached[0] < 30:
            return JSONResponse(status_code=cached[1], content=cached[2])

        async def timed(name: str, coro: Any) -> tuple[str, dict[str, Any]]:
            t0 = time.perf_counter()
            try:
                res = await asyncio.wait_for(coro, timeout=25)
                res = {**res, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
            except Exception as exc:
                res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200], "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
            return name, res

        results = dict(
            await asyncio.gather(
                timed("cosmos", svc.repo.ping()),
                timed("storage", svc.blobs.ping()),
                timed("openai", svc.llm.ping()),
                timed("cognitive", getattr(svc.cognitive, "ping", _noop_ping)()),
            )
        )
        results["seed"] = {"ok": svc.seed_state.get("status") in ("done", "disabled", "degraded"), "status": svc.seed_state.get("status")}
        ok = all(r.get("ok") for r in results.values())
        body = {"status": "ready" if ok else "degraded", "mode": svc.settings.mode, "checks": results}
        code = 200 if ok else 503
        svc.ready_cache["v"] = (time.time(), code, body)
        return JSONResponse(status_code=code, content=body)

    @app.get("/api/meta", tags=["platform"])
    async def meta(request: Request) -> dict[str, Any]:
        svc = svc_of(request)
        s = svc.settings
        return {
            "name": APP_NAME,
            "product": "Concierge",
            "version": APP_VERSION,
            "build_id": s.build_id,
            "mode": s.mode,
            "region": s.region,
            "resource_group": s.resource_group,
            "deployments": {k: v for k, v in s.deployments.items() if v},
            "repository": svc.repo.kind,
            "llm": svc.llm.name,
            "auth_mode": s.auth_mode,
            "uptime_s": round(time.time() - STARTED_AT, 1),
            "features": len(svc.registry.features) if svc.registry else 0,
            "seed": {"status": svc.seed_state.get("status"), "finished": svc.seed_state.get("finished")},
            "daily_budget_usd": s.daily_budget_usd,
            "synthetic_data": True,
            "simulated": ["PSTN telephony (no number, carrier or ACS resource: adapters for SIP to Realtime, Teams Phone Extensibility and ACS Call Automation (legacy) sit behind one interface and are exercised by a simulator)", "SMS/e-mail/WhatsApp delivery", "back-office (CRM/OMS) systems"],
        }

    @app.get("/api/features", tags=["platform"])
    async def features(request: Request) -> list[dict[str, Any]]:
        return svc_of(request).registry.listing()

    @app.get("/api/usage", tags=["platform"])
    async def usage(request: Request) -> dict[str, Any]:
        return svc_of(request).meter.snapshot()

    @app.post("/api/admin/reseed", tags=["platform"])
    async def reseed(request: Request, _: Any = Depends(require("admin"))) -> dict[str, Any]:
        svc = svc_of(request)
        if svc.seed_state.get("status") == "running":
            raise HTTPException(409, "seed already running")
        state = await run_seed(svc, force=True)
        return {"status": state["status"], "steps": state["steps"]}

    @app.post("/api/admin/reset-backoffice", tags=["platform"])
    async def reset_backoffice(request: Request, actor: Any = Depends(require("admin"))) -> dict[str, Any]:
        """Clears the returns, refunds, credits, tickets and appointments created by journeys and re-creates the synthetic customers and orders
        (makes the demo journeys repeatable; the smoke test calls it first)."""
        svc = svc_of(request)
        counts = await svc.backoffice.reset()
        await svc.audit.log("admin.reset_backoffice", actor=f"{actor.role}:{actor.user}", detail={"collections": len(counts)})
        return {"status": "ok", "counts": counts}

    for _name, router in registry.routers:
        app.include_router(router)

    instrument_app(app)
    _mount_spa(app, settings)
    return app


async def _noop_ping() -> dict[str, Any]:
    return {"ok": True}


async def _flusher(svc: Services) -> None:
    while True:
        await asyncio.sleep(15)
        try:
            await svc.meter.flush()
        except Exception as exc:  # pragma: no cover
            log.warning("usage flush failed: %s", exc)


def _mount_spa(app: FastAPI, settings: Settings) -> None:
    root = settings.static_dir
    if not root or not os.path.isdir(root):
        return
    root = os.path.realpath(root)
    index = os.path.join(root, "index.html")
    assets = os.path.join(root, "assets")
    if os.path.isdir(assets):
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> Any:
        if full_path.startswith(("api/", "ws/")) or full_path in ("api", "ws"):
            raise HTTPException(404, "not found")
        candidate = os.path.realpath(os.path.join(root, full_path))
        if full_path and candidate.startswith(root + os.sep) and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = None  # created lazily by `uvicorn concierge.main:create_app --factory`
