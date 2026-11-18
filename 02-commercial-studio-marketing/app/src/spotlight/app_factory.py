"""Application factory: feature auto-discovery, middleware, error handling, SPA hosting."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import __version__
from .api_core import router as core_router
from .config import Settings, get_settings
from .errors import AppError
from .i18n import LocaleMiddleware, t
from .i18n.validation import localize_validation_errors
from .registry import CATALOG, discover
from .security import SecurityMiddleware, request_id_var, setup_logging
from .services import Services, build_services

log = logging.getLogger("spotlight")
_ID_SEG = re.compile(r"/[A-Za-z]{2,5}_[0-9a-f]{8,16}|/[0-9a-f]{12,64}")


class MetricsMiddleware:
    """Per-route latency / error counters (feeds /api/ops/metrics; OpenTelemetry covers the rest)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status = 500
        t0 = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            if path.startswith("/api/"):
                svc: Services | None = getattr(scope.get("app"), "state", None) and getattr(scope["app"].state, "services", None)
                if svc is not None:
                    key = f"{scope['method']} {_ID_SEG.sub('/{id}', path)}"
                    st = svc.route_stats.setdefault(key, {"count": 0, "errors": 0, "total_ms": 0.0, "max_ms": 0.0})
                    ms = (time.perf_counter() - t0) * 1000
                    st["count"] += 1
                    st["total_ms"] += ms
                    st["max_ms"] = max(st["max_ms"], ms)
                    if status >= 500:
                        st["errors"] += 1


class ImmutableStatic(StaticFiles):
    async def get_response(self, path: str, scope: Scope):
        resp = await super().get_response(path, scope)
        if resp.status_code == 200:
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)
    features = discover()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc = services or await build_services(settings)
        app.state.services = svc
        interrupted = await svc.jobs.reconcile_startup()
        svc.jobs.start_sweeper()  # jobs of replicas that went away (no heartbeat) are failed within a couple of minutes, never left spinning
        if settings.seed_on_start:
            from .seed import ensure_seeded

            await ensure_seeded(svc)
        svc.extras["reseed_hooks"] = list(app.state.startup_hooks)

        async def run_hooks() -> None:  # heavier seeding (performance history) runs in the background; the app is already serving
            for hook in app.state.startup_hooks:
                try:
                    await hook(svc)
                except Exception:
                    log.exception("startup hook failed")

        hooks_task = asyncio.create_task(run_hooks())
        app.state.hooks_task = hooks_task
        log.info("Spotlight started: mode=%s repo=%s blobs=%s ai=%s interrupted_jobs=%d", settings.mode, svc.repo.mode, svc.blobs.mode, svc.llm.mode, interrupted)
        yield
        hooks_task.cancel()
        await svc.close()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Brief-to-broadcast AI commercial studio: brand-safe, localized, personalized, measurable. Synthetic sample data.",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.features = features
    app.state.startup_hooks = []
    app.state.build_hooks = []
    app.state.telemetry_enabled = False

    @app.get("/docs", include_in_schema=False)
    async def docs() -> HTMLResponse:
        # Swagger UI assets are bundled with the SPA (web/public/swagger) — no CDN fetches.
        return get_swagger_ui_html(
            openapi_url="/openapi.json",
            title=f"{settings.app_name} — API",
            swagger_js_url="/swagger/swagger-ui-bundle.js",
            swagger_css_url="/swagger/swagger-ui.css",
            swagger_favicon_url="/swagger/favicon-32x32.png",
        )

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse({"error": {**exc.to_dict(), "request_id": request_id_var.get()}}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errs = localize_validation_errors(list(exc.errors()))
        return JSONResponse({"error": {"code": "validation_failed", "message": t("err.validation_failed"), "details": errs, "request_id": request_id_var.get()}}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"error": {"code": "internal_error", "message": t("err.internal_error"), "request_id": request_id_var.get()}}, status_code=500)

    app.add_middleware(MetricsMiddleware)
    app.add_middleware(SecurityMiddleware, max_body_bytes=settings.max_body_bytes)
    app.add_middleware(LocaleMiddleware)  # outermost: every handler, error response and background job sees the request locale

    app.include_router(core_router)
    for feat in features.values():
        if feat.router is not None:
            app.include_router(feat.router)
        hook = feat.extra.get("startup")
        if hook:
            app.state.startup_hooks.append(hook)

    static = settings.static_path
    if static is not None:
        if (static / "assets").is_dir():
            app.mount("/assets", ImmutableStatic(directory=static / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> Any:
            if full_path.startswith(("api/", "docs", "openapi", "healthz", "readyz", "redoc")):
                return JSONResponse({"error": {"code": "not_found", "message": t("err.not_found")}}, status_code=404)
            target = (static / full_path).resolve()
            if full_path and target.is_file() and target.is_relative_to(static.resolve()):
                return FileResponse(target)
            return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    app.state.catalog_size = len(CATALOG)
    return app
