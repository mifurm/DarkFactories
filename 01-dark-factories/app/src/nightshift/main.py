"""FastAPI application factory with feature auto-discovery and single-container SPA hosting."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.middleware.gzip import GZipMiddleware

from nightshift import APP_NAME, __version__
from nightshift.config import Settings
from nightshift.core import platform
from nightshift.core.http import PlatformMiddleware
from nightshift.core.obs import setup_azure_monitor, setup_logging
from nightshift.core.registry import LoadedFeature, discover_features
from nightshift.core.runtime import Runtime

log = logging.getLogger("nightshift")
STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None, features: list[LoadedFeature] | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    loaded = features if features is not None else discover_features()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if os.getenv("NIGHTSHIFT_JSON_LOGS", "1") != "0":
            setup_logging()
        if settings.is_azure and settings.appinsights_connection_string:  # pragma: no cover
            setup_azure_monitor(settings.appinsights_connection_string, settings.azure_client_id)
        rt = await Runtime.create(settings, loaded)
        from nightshift.plant.fleet import Fleet  # composition root of the domain layer

        rt.fleet = Fleet(rt)
        app.state.rt = rt
        await rt.start()
        if settings.sim_autostart:
            from nightshift.features.df21_value.router import warm_default

            warm_default(rt)
        log.info("nightshift started mode=%s features=%d", settings.mode, len(loaded))
        try:
            yield
        finally:
            await rt.stop()

    app = FastAPI(
        title=APP_NAME,
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        description="Cognitive swarm layer for lights-out manufacturing. Simulated plant, synthetic data.",
    )
    app.add_middleware(PlatformMiddleware, settings=settings, metrics=_metrics_ref(app), features=lambda: loaded)
    # calculator payloads are ~100 KB of JSON; Starlette leaves text/event-stream uncompressed
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=4)
    app.include_router(platform.router)
    for f in loaded:
        if f.router is not None:
            app.include_router(f.router)
        for extra in f.extra_routers:
            app.include_router(extra)

    @app.get("/docs", include_in_schema=False)
    async def docs() -> HTMLResponse:
        local = (STATIC_DIR / "swagger" / "swagger-ui-bundle.js").exists()
        kw = (
            {"swagger_js_url": "/swagger/swagger-ui-bundle.js", "swagger_css_url": "/swagger/swagger-ui.css"}
            if local
            else {}
        )
        return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{APP_NAME} - API", **kw)

    _mount_spa(app)
    return app


class _MetricsProxy:
    """The middleware is created before the runtime exists; forward to the runtime's Metrics once started."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app
        self._fallback = None

    def _m(self):
        rt = getattr(self._app.state, "rt", None)
        if rt is not None:
            return rt.metrics
        if self._fallback is None:
            from nightshift.core.obs import Metrics

            self._fallback = Metrics()
        return self._fallback

    def observe_request(self, *a, **k):
        return self._m().observe_request(*a, **k)


def _metrics_ref(app: FastAPI) -> _MetricsProxy:
    return _MetricsProxy(app)


def _mount_spa(app: FastAPI) -> None:
    index = STATIC_DIR / "index.html"
    if not index.exists():

        @app.get("/", include_in_schema=False)
        async def root() -> JSONResponse:
            return JSONResponse({"name": APP_NAME, "ui": "not built (run `npm run build` in app/web)", "docs": "/docs"})

        return

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith(("api/", "ws/")) or full_path in {"api", "ws"}:
            raise HTTPException(status_code=404, detail="not found")
        if full_path:
            candidate = (STATIC_DIR / full_path).resolve()
            if STATIC_DIR.resolve() in candidate.parents and candidate.is_file():
                cache = "public, max-age=31536000, immutable" if full_path.startswith("assets/") else "no-cache"
                return FileResponse(candidate, headers={"Cache-Control": cache})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
