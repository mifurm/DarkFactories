"""Security plumbing: request ids, security headers, body-size limit, rate limits, JSON logging with PII redaction."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections import defaultdict
from contextvars import ContextVar
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .errors import PayloadTooLarge, RateLimited
from .i18n import t

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

CSP = (
    "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; font-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)
SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "content-security-policy": CSP,
    "cross-origin-opener-policy": "same-origin",
}
# Swagger UI needs inline scripts/styles; keep the strict CSP everywhere else.
DOCS_CSP = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'"


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        rid = re.sub(r"[^A-Za-z0-9_.-]", "", headers.get("x-request-id", ""))[:64] or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        scope.setdefault("state", {})["request_id"] = rid
        path = scope.get("path", "")
        started = time.perf_counter()

        declared = headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self.max_body:
            await self._reject(send, rid)
            request_id_var.reset(token)
            return

        seen = 0

        async def limited_receive() -> Message:
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.max_body:
                    raise PayloadTooLarge(f"request body exceeds {self.max_body} bytes", key="err.payload_too_large.body", params={"limit": self.max_body})
            return msg

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                hdrs = list(message.get("headers", []))
                existing = {k.lower() for k, _ in hdrs}
                for k, v in SECURITY_HEADERS.items():
                    if k.encode() not in existing:
                        val = DOCS_CSP if (k == "content-security-policy" and path in ("/docs", "/redoc")) else v
                        hdrs.append((k.encode(), val.encode()))
                hdrs.append((b"x-request-id", rid.encode()))
                hdrs.append((b"server-timing", f"app;dur={(time.perf_counter() - started) * 1000:.1f}".encode()))
                if path.startswith("/api/") and b"cache-control" not in existing:
                    hdrs.append((b"cache-control", b"no-store"))
                message = {**message, "headers": hdrs}
            await send(message)

        try:
            await self.app(scope, limited_receive, send_wrapper)
        finally:
            request_id_var.reset(token)

    async def _reject(self, send: Send, rid: str) -> None:
        body = json.dumps({"error": {"code": "payload_too_large", "message": t("err.payload_too_large.body", limit=self.max_body), "request_id": rid}}, ensure_ascii=False).encode()
        await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class RateLimiter:
    """In-process token buckets: per-IP and global (per replica). Spend endpoints are tighter than plain mutations."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._buckets: dict[str, tuple[float, float]] = {}
        self.rejections: dict[str, int] = defaultdict(int)

    def check(self, scope: str, key: str, per_min: int) -> None:
        if not self.enabled or per_min <= 0:
            return
        now = time.monotonic()
        bkey = f"{scope}:{key}"
        tokens, ts = self._buckets.get(bkey, (float(per_min), now))
        tokens = min(float(per_min), tokens + (now - ts) * per_min / 60.0)
        if tokens < 1.0:
            self.rejections[scope] += 1
            retry = max(1, int((1.0 - tokens) * 60.0 / per_min) + 1)
            raise RateLimited(
                f"Rate limit reached for {scope} requests ({per_min}/min). Retry in ~{retry}s.", hint=f"Retry-After: {retry}", details={"retry_after_s": retry}, params={"scope": scope, "per_min": per_min, "retry": retry}
            )
        self._buckets[bkey] = (tokens - 1.0, now)
        if len(self._buckets) > 20000:
            self._buckets.clear()


def client_ip(headers: Any, fallback: str | None) -> str:
    xff = headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()[:64]
    return (fallback or "unknown")[:64]


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(\+?\d[\d\s().-]{8,}\d)(?!\d)")
_IPV4 = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.\d{1,3}\.\d{1,3}\b")


def redact(text: str) -> str:
    text = _EMAIL.sub("[email]", text)
    text = _IPV4.sub(r"\1.\2.x.x", text)
    return _PHONE.sub("[phone]", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))[:2000]
        for k in ("feature", "latency_ms", "status", "path", "method"):
            if hasattr(record, k):
                payload[k] = getattr(record, k)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    for h in list(root.handlers):
        root.removeHandler(h)
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter())
    root.addHandler(h)
    for noisy in ("azure", "azure.core.pipeline.policies.http_logging_policy", "azure.cosmos", "azure.identity", "httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
