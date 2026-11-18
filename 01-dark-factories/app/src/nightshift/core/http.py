"""Pure-ASGI platform middleware: request ids, size limits, per-IP + global rate limits, security headers, metrics."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nightshift.config import Settings
from nightshift.core.obs import Metrics
from nightshift.core.registry import LoadedFeature, feature_for_path

log = logging.getLogger("nightshift.http")
_RID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)
CSP_DOCS = CSP + "; script-src 'self' 'unsafe-inline'"

# AI-spending endpoints get the tighter bucket
AI_PREFIXES = (
    "/api/copilot/chat",
    "/api/handover/generate",
    "/api/rca/narrate",
    "/api/quality/vision",
    "/api/swarm/explain",
    "/api/value/narrate",
    "/api/readiness/narrate",
    "/api/ledger/explain",
)
# pure calculations (POST only because they take a body): generous bucket, no state is mutated
COMPUTE_PATHS = ("/api/value/calculator/compute",)


class TokenBuckets:
    """Per-key token buckets (LRU-bounded)."""

    def __init__(self, max_keys: int = 5000) -> None:
        self._b: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self.max_keys = max_keys

    def take(self, key: str, per_min: int, now: float | None = None) -> float:
        """Return 0 if allowed else seconds to wait."""
        now = time.monotonic() if now is None else now
        cap = float(max(1, per_min))
        tokens, last = self._b.get(key, (cap, now))
        tokens = min(cap, tokens + (now - last) * cap / 60.0)
        if tokens < 1.0:
            self._b[key] = (tokens, now)
            self._b.move_to_end(key)
            return (1.0 - tokens) * 60.0 / cap
        self._b[key] = (tokens - 1.0, now)
        self._b.move_to_end(key)
        while len(self._b) > self.max_keys:
            self._b.popitem(last=False)
        return 0.0


def client_ip(scope: Scope, headers: Headers) -> str:
    xff = headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()[:64]
    c = scope.get("client")
    return c[0] if c else "unknown"


class PlatformMiddleware:
    def __init__(
        self, app: ASGIApp, settings: Settings, metrics: Metrics, features: Callable[[], list[LoadedFeature]]
    ) -> None:
        self.app, self.s, self.metrics, self._features = app, settings, metrics, features
        self.buckets = TokenBuckets()
        self.limited = 0

    def _category(self, method: str, path: str) -> str:
        if any(path.startswith(p) for p in AI_PREFIXES):
            return "ai"
        if path in COMPUTE_PATHS:
            return "compute"
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            return "mutate"
        return "read"

    def _limits(self, cat: str) -> tuple[int, int]:
        s = self.s
        return {
            "ai": (s.rate_limit_ai_per_min, s.rate_limit_global_ai_per_min),
            "mutate": (s.rate_limit_mutating_per_min, s.rate_limit_global_mutating_per_min),
            "read": (s.rate_limit_get_per_min, s.rate_limit_get_per_min * 4),
            "compute": (s.rate_limit_compute_per_min, s.rate_limit_compute_per_min * 3),
        }[cat]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        t0 = time.perf_counter()
        headers = Headers(scope=scope)
        rid = headers.get("x-request-id", "")
        rid = rid if _RID.match(rid) else uuid.uuid4().hex[:16]
        scope.setdefault("state", {})["request_id"] = rid
        path, method = scope["path"], scope["method"]
        status_box = {"status": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_box["status"] = message["status"]
                h = MutableHeaders(scope=message)
                h["X-Request-ID"] = rid
                h["X-Content-Type-Options"] = "nosniff"
                h["X-Frame-Options"] = "DENY"
                h["Referrer-Policy"] = "no-referrer"
                h["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
                h["Cross-Origin-Opener-Policy"] = "same-origin"
                h["Content-Security-Policy"] = CSP_DOCS if path.startswith(("/docs", "/redoc")) else CSP
                if scope.get("scheme") == "https" or headers.get("x-forwarded-proto") == "https":
                    h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
                if path.startswith("/api") and "cache-control" not in h:
                    h["Cache-Control"] = "no-store"
            await send(message)

        cl = headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > self.s.max_body_bytes:
            resp = JSONResponse({"detail": f"request body exceeds {self.s.max_body_bytes} bytes"}, status_code=413)
            await resp(scope, receive, send_wrapper)
            return

        if path.startswith("/api") and path != "/api/stream/ping":
            cat = self._category(method, path)
            per_ip, global_cap = self._limits(cat)
            ip = client_ip(scope, headers)
            wait = self.buckets.take(f"{cat}:ip:{ip}", per_ip) or self.buckets.take(f"{cat}:global", global_cap)
            if wait:
                self.limited += 1
                resp = JSONResponse(
                    {"detail": f"rate limit exceeded for {cat} requests", "retry_after_s": round(wait, 1)},
                    status_code=429,
                    headers={"Retry-After": str(max(1, int(wait + 0.5)))},
                )
                await resp(scope, receive, send_wrapper)
                self.metrics.observe_request("platform", 429, (time.perf_counter() - t0) * 1000)
                return

        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > self.s.max_body_bytes:
                    raise _TooLarge
            return msg

        try:
            await self.app(scope, counting_receive, send_wrapper)
        except _TooLarge:
            resp = JSONResponse({"detail": "request body too large"}, status_code=413)
            await resp(scope, receive, send_wrapper)
        finally:
            ms = (time.perf_counter() - t0) * 1000
            feature = feature_for_path(self._features(), path)
            st = status_box["status"] or 500
            if path.startswith("/api") or path in {"/healthz", "/readyz"}:
                self.metrics.observe_request(feature, st, ms)
            if path.startswith("/api") and not path.startswith("/api/stream"):
                log.info(
                    "%s %s -> %s",
                    method,
                    path,
                    st,
                    extra={"request_id": rid, "feature": feature, "path": path, "status": st, "ms": round(ms, 1)},
                )


class _TooLarge(Exception):
    pass
