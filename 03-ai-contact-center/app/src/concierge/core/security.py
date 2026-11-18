"""HTTP hardening: security headers, request ids, per-IP + global rate limits, request-size limits, WS origin checks."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from contextvars import ContextVar
from typing import Any

from .config import Settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

AI_PREFIXES = (
    "/api/chat", "/api/voice", "/api/evals", "/api/assist", "/api/qa", "/api/wrapup", "/api/kb", "/api/demo",
    "/api/handoff", "/api/i18n", "/api/outbound", "/api/voc", "/api/compliance", "/api/rollout",
)  # fmt: skip
UNLIMITED = ("/healthz",)

CSP = (
    "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self' ws: wss:; worker-src 'self' blob:; font-src 'self' data:; frame-ancestors 'self'; "
    "base-uri 'self'; form-action 'self'"
)
CSP_DOCS = (
    "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; connect-src 'self'; frame-ancestors 'self'"
)


class RateLimiter:
    """Sliding-window limiter (in-process; one replica). Keys idle for > 2 windows are pruned."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._last_prune = time.time()

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = time.time()
        q = self._hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        if now - self._last_prune > 120:
            self._prune(now, window)
        return True

    def _prune(self, now: float, window: float) -> None:
        self._last_prune = now
        for k in [k for k, q in self._hits.items() if not q or now - q[-1] > 2 * window]:
            del self._hits[k]

    def reset(self) -> None:
        self._hits.clear()


def client_ip(scope: dict[str, Any]) -> str:
    for name, value in scope.get("headers", []):
        if name == b"x-forwarded-for":
            return value.decode("latin-1").split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


class BodyTooLarge(Exception):
    pass


class SecurityMiddleware:
    def __init__(self, app: Any, settings: Settings, limiter: RateLimiter | None = None) -> None:
        self.app = app
        self.s = settings
        self.limiter = limiter or RateLimiter()

    async def _reject(self, send: Any, status: int, body: dict[str, Any], extra: list[tuple[bytes, bytes]] | None = None) -> None:
        import json

        payload = json.dumps(body).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode()), *(extra or [])]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": payload})

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "websocket":
            ip = client_ip(scope)
            if not self.limiter.allow(f"ws:{ip}", 60):
                await send({"type": "websocket.close", "code": 1013})
                return
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope["path"]
        method: str = scope["method"]
        ip = client_ip(scope)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        rid = headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request_id_var.set(rid)
        scope.setdefault("state", {})["request_id"] = rid

        if path.startswith("/api") or path == "/readyz":
            retry = [(b"retry-after", b"30"), (b"x-request-id", rid.encode())]
            if not self.limiter.allow("global", self.s.rate_limit_global_per_min):
                await self._reject(send, 429, {"error": "rate_limited", "scope": "global"}, retry)
                return
            if path == "/readyz" and not self.limiter.allow(f"ready:{ip}", 30):
                await self._reject(send, 429, {"error": "rate_limited", "scope": "ip"}, retry)
                return
            mutating = method not in ("GET", "HEAD", "OPTIONS")
            if mutating and not self.limiter.allow(f"mut:{ip}", self.s.rate_limit_ip_per_min):
                await self._reject(send, 429, {"error": "rate_limited", "scope": "ip-mutating"}, retry)
                return
            if mutating and path.startswith(AI_PREFIXES) and not self.limiter.allow(f"ai:{ip}", self.s.rate_limit_ai_ip_per_min):
                await self._reject(send, 429, {"error": "rate_limited", "scope": "ip-ai"}, retry)
                return
            if not mutating and not self.limiter.allow(f"get:{ip}", 900):
                await self._reject(send, 429, {"error": "rate_limited", "scope": "ip-read"}, retry)
                return

        limit = self.s.max_upload_bytes if path.startswith("/api/kb/upload") else self.s.max_body_bytes
        declared = headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            await self._reject(send, 413, {"error": "payload_too_large", "max_bytes": limit})
            return

        seen = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > limit:
                    raise BodyTooLarge
            return msg

        started = False
        csp = CSP_DOCS if path.startswith(("/docs", "/redoc", "/openapi")) else CSP

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                hdrs = list(message.get("headers", []))
                hdrs += [
                    (b"x-request-id", rid.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"SAMEORIGIN"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", b"microphone=(self), camera=(), geolocation=()"),
                    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
                    (b"content-security-policy", csp.encode()),
                    (b"cross-origin-opener-policy", b"same-origin"),
                ]
                if path.startswith("/api"):
                    hdrs.append((b"cache-control", b"no-store"))
                message = {**message, "headers": hdrs}
            await send(message)

        try:
            await self.app(scope, limited_receive, send_wrapper)
        except BodyTooLarge:
            if not started:
                await self._reject(send, 413, {"error": "payload_too_large", "max_bytes": limit})


def ws_origin_ok(headers: dict[str, str]) -> bool:
    """Same-origin check for browser WebSocket clients (non-browser clients send no Origin header)."""
    origin = headers.get("origin")
    if not origin:
        return True
    host = headers.get("host", "")
    return origin.split("://", 1)[-1].split("/", 1)[0] == host
