"""Event notifier + Teams/Slack-compatible webhook dispatcher (CS-22) with SSRF protections."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from collections import deque
from typing import Any
from urllib.parse import urlparse

import httpx

from ..errors import ValidationFailed
from ..util import new_id, now_iso

log = logging.getLogger("spotlight.notify")
ALLOWED_HOST_SUFFIXES = (".webhook.office.com", ".office.com", ".logic.azure.com", "hooks.slack.com", ".slack.com")
INTERNAL_SINK = "internal://sink"
EVENTS = ["approval.requested", "approval.approved", "approval.rejected", "approval.changes_requested", "job.failed", "job.succeeded", "budget.alert", "rights.expiring", "rights.revoked"]


async def validate_webhook_url(url: str, allow_internal: bool = True) -> str:
    """SSRF guard: https only, allow-listed hosts, no credentials/IP literals, every resolved address must be public."""
    if url == INTERNAL_SINK:
        if not allow_internal:
            raise ValidationFailed("the internal sink is disabled", code="bad_webhook")
        return url
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if p.scheme != "https" or not host or p.username or p.password or (p.port not in (None, 443)):
        raise ValidationFailed("webhook URLs must be https://<allow-listed host>/… on port 443 without credentials", code="bad_webhook")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValidationFailed("IP-literal webhook hosts are not allowed", code="bad_webhook")
    if not (host.endswith(ALLOWED_HOST_SUFFIXES) or host == "hooks.slack.com"):
        raise ValidationFailed(f"host {host!r} is not on the webhook allow-list ({', '.join(ALLOWED_HOST_SUFFIXES)})", code="bad_webhook")
    infos = await asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValidationFailed("webhook host resolves to a non-public address", code="bad_webhook")
    return url


def title_for(event: str) -> str:
    return {
        "approval.requested": "Approval requested", "approval.approved": "Approved", "approval.rejected": "Rejected", "approval.changes_requested": "Changes requested",
        "job.failed": "Job failed", "job.succeeded": "Job finished", "budget.alert": "Budget alert", "rights.expiring": "Rights expiring", "rights.revoked": "Rights revoked",
    }.get(event, event)


def summary_for(event: str, payload: dict[str, Any]) -> str:
    bits = [f"{k}: {payload[k]}" for k in ("campaign", "stage", "decision", "by", "title", "scope", "spent_usd", "cap_usd", "days_left", "kind") if payload.get(k) is not None]
    return " · ".join(bits) or event


def format_payload(fmt: str, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    title = f"Spotlight · {title_for(event)}"
    text = summary_for(event, payload)
    if fmt == "teams":
        return {"@type": "MessageCard", "@context": "http://schema.org/extensions", "themeColor": "F2A03D", "summary": title, "title": title, "text": text, "sections": [{"facts": [{"name": k, "value": str(v)[:120]} for k, v in list(payload.items())[:6]]}]}
    if fmt == "slack":
        return {"text": f"*{title}* — {text}", "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*\n{text}"}}]}
    return {"event": event, "title": title, "text": text, "payload": payload, "ts": now_iso()}


class WebhookDispatcher:
    def __init__(self, repo: Any, settings: Any) -> None:
        self.repo = repo
        self.settings = settings
        self._http = httpx.AsyncClient(timeout=5.0, follow_redirects=False)

    async def hooks(self) -> list[dict[str, Any]]:
        return await self.repo.query("webhooks", {"type": "webhook", "enabled": True}, pk="tenant")

    async def dispatch(self, event: str, payload: dict[str, Any]) -> None:
        for hook in await self.hooks():
            if "*" in hook["events"] or event in hook["events"]:
                await self.send(hook, event, payload)

    async def send(self, hook: dict[str, Any], event: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = format_payload(hook.get("format", "generic"), event, payload)
        t0 = time.perf_counter()
        status, error = None, None
        try:
            url = await validate_webhook_url(hook["url"], self.settings.allow_internal_webhook_sink)
            if url == INTERNAL_SINK:
                status = 200  # recorded in-app (demo/smoke sink) — no network egress
            else:
                r = await self._http.post(url, json=body)
                status = r.status_code
                if status >= 400:
                    error = r.text[:200]
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:200]}"
        doc = {"id": new_id("dlv"), "pk": "tenant", "type": "delivery", "webhook_id": hook["id"], "webhook": hook["name"], "event": event, "format": hook.get("format"), "status": status, "ok": bool(status and status < 400), "error": error, "ms": round((time.perf_counter() - t0) * 1000, 1), "payload": body, "created_at": now_iso()}
        await self.repo.upsert("webhooks", doc)
        return doc

    async def close(self) -> None:
        await self._http.aclose()


class Notifier:
    def __init__(self, repo: Any = None, settings: Any = None) -> None:
        self.repo = repo
        self.settings = settings
        self.recent: deque[dict[str, Any]] = deque(maxlen=100)
        self.dispatcher: WebhookDispatcher | None = None
        self._tasks: set[asyncio.Task] = set()

    def attach(self) -> None:
        if self.dispatcher is None and self.repo is not None:
            self.dispatcher = WebhookDispatcher(self.repo, self.settings)

    async def emit(self, event: str, payload: dict[str, Any]) -> None:
        rec = {"event": event, "payload": payload, "ts": now_iso()}
        self.recent.appendleft(rec)
        log.info("event %s %s", event, {k: payload[k] for k in list(payload)[:4]})
        if self.dispatcher is not None:
            task = asyncio.create_task(self._safe_dispatch(event, payload))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _safe_dispatch(self, event: str, payload: dict[str, Any]) -> None:
        try:
            await self.dispatcher.dispatch(event, payload)  # type: ignore[union-attr]
        except Exception:
            log.exception("webhook dispatch failed for %s", event)

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def close(self) -> None:
        await self.drain()
        if self.dispatcher is not None:
            await self.dispatcher.close()
