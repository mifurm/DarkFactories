"""CC-01 Omnichannel chat agent: REST + SSE + WebSocket API, channel adapters (web chat, generic webhook, SMS / WhatsApp / e-mail stubs)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...core.registry import EPIC_A, FeatureInfo
from ...core.security import ws_origin_ok
from ...engine.orchestrator import ConversationClosed
from .adapters import ADAPTERS

FEATURES = [
    FeatureInfo(
        "CC-01", "Omnichannel chat agent", EPIC_A, "P0", "/widget", "/api/chat",
        "Web chat widget with token streaming, session memory (persisted), multilingual replies; REST/SSE/WebSocket API; channel adapters for web chat, generic webhook and SMS/WhatsApp/e-mail stubs.",
    ),
]  # fmt: skip

router = APIRouter(tags=["chat (CC-01)"])


class StartBody(BaseModel):
    language: str = Field("en", max_length=8)
    channel: Literal["web_chat", "voice"] = "web_chat"
    recording_consent: Literal["pending", "granted", "declined"] = "pending"


class MessageBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ConfirmBody(BaseModel):
    accept: bool = True
    action_id: str | None = None


class ConsentBody(BaseModel):
    granted: bool


def view(svc: Any, conv: Any) -> dict[str, Any]:
    d = conv.public_view()
    h = conv.handoff
    d["handoff"] = {"state": h.get("state"), "queue": h.get("routing", {}).get("queue"), "est_wait_min": h.get("est_wait_min"), "trigger": h.get("trigger", {}).get("code")} if h else None
    w = next((w for w in svc.ext.get("workers", []) if w["id"] == conv.assigned_agent), None)
    d["agent"] = {"id": conv.assigned_agent, "name": w["name"] if w else conv.assigned_agent} if conv.assigned_agent else None
    return d


async def _get(request: Request, conv_id: str) -> tuple[Any, Any]:
    svc = request.app.state.services
    conv = await svc.store.get(conv_id)
    if conv is None:
        raise HTTPException(404, {"error": "session_not_found", "message": "Unknown or expired session."})
    return svc, conv


@router.post("/api/chat/sessions")
async def start_session(body: StartBody, request: Request) -> dict[str, Any]:
    svc = request.app.state.services
    conv = await svc.orchestrator.start(channel=body.channel, language=body.language, recording_consent=body.recording_consent)
    return {"session": view(svc, conv)}


@router.get("/api/chat/sessions/{conv_id}")
async def get_session(conv_id: str, request: Request) -> dict[str, Any]:
    svc, conv = await _get(request, conv_id)
    return {"session": view(svc, conv)}


@router.post("/api/chat/sessions/{conv_id}/messages")
async def post_message(conv_id: str, body: MessageBody, request: Request) -> dict[str, Any]:
    svc, conv = await _get(request, conv_id)
    try:
        res = await svc.orchestrator.handle_message(conv_id, body.text)
    except ConversationClosed:
        raise HTTPException(409, {"error": "conversation_closed", "message": "This conversation has ended."}) from None
    conv = await svc.store.get(conv_id)
    return {**res, "session": view(svc, conv)}


def _sse(ev: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(ev, default=str)}\n\n".encode()


@router.post("/api/chat/sessions/{conv_id}/stream")
async def stream_message(conv_id: str, body: MessageBody, request: Request) -> StreamingResponse:
    svc, _ = await _get(request, conv_id)
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def emit(ev: dict[str, Any]) -> None:
        await queue.put(ev)

    async def run() -> None:
        try:
            await svc.orchestrator.handle_message(conv_id, body.text, emit)
        except ConversationClosed:
            await queue.put({"type": "error", "error": "conversation_closed"})
        except Exception as exc:
            await queue.put({"type": "error", "error": type(exc).__name__})
        finally:
            await queue.put(None)

    task = asyncio.create_task(run())

    async def gen() -> AsyncIterator[bytes]:
        try:
            while True:
                ev = await queue.get()
                if ev is None:
                    break
                yield _sse(ev)
        finally:
            await task

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/api/chat/sessions/{conv_id}/confirm")
async def confirm(conv_id: str, body: ConfirmBody, request: Request) -> dict[str, Any]:
    svc, _ = await _get(request, conv_id)
    conv = await svc.orchestrator.confirm(conv_id, accept=body.accept, action_id=body.action_id)
    return {"session": view(svc, conv)}


@router.post("/api/chat/sessions/{conv_id}/consent")
async def consent(conv_id: str, body: ConsentBody, request: Request) -> dict[str, Any]:
    svc, _ = await _get(request, conv_id)
    conv = await svc.orchestrator.set_consent(conv_id, body.granted)
    return {"session": view(svc, conv)}


@router.post("/api/chat/sessions/{conv_id}/close")
async def close(conv_id: str, request: Request) -> dict[str, Any]:
    svc, _ = await _get(request, conv_id)
    conv = await svc.orchestrator.close(conv_id, by="customer")
    return {"session": view(svc, conv)}


@router.get("/api/chat/sessions/{conv_id}/outbox")
async def outbox(conv_id: str, request: Request) -> dict[str, Any]:
    """The customer's simulated phone / mailbox (OTP codes, confirmations, payment links) - synthetic delivery."""
    _, conv = await _get(request, conv_id)
    return {"simulated": True, "messages": conv.outbox}


@router.get("/api/chat/channels")
async def channels() -> list[dict[str, Any]]:
    return [{"name": a.name, "description": a.description, "simulated": a.simulated, "sample_inbound": a.sample_inbound(), "sample_outbound": a.render_outbound("Hello from Concierge", "key", {})} for a in ADAPTERS.values()]


@router.post("/api/chat/channels/{channel}/inbound")
async def channel_inbound(channel: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    """Inbound message from a channel provider: normalise -> idempotency on the provider message id -> agent -> render replies."""
    svc = request.app.state.services
    adapter = ADAPTERS.get(channel)
    if adapter is None or channel == "web_chat":
        raise HTTPException(404, {"error": "unknown_channel", "channels": [c for c in ADAPTERS if c != "web_chat"]})
    try:
        inbound = adapter.parse_inbound(payload)
    except ValueError as exc:
        raise HTTPException(422, {"error": "invalid_payload", "message": str(exc)}) from exc
    idem_id = hashlib.sha1(f"msg:{channel}:{inbound.external_id}".encode()).hexdigest()
    prior = await svc.repo.get("idempotency", idem_id)
    if prior:
        return {**prior["result"], "duplicate": True}
    map_id = hashlib.sha1(f"chan:{channel}:{inbound.conversation_key}".encode()).hexdigest()
    link = await svc.repo.get("settings", f"chan-{map_id}")
    conv = await svc.store.get(link["conv_id"]) if link else None
    if conv is None or conv.status in ("closed", "resolved"):
        conv = await svc.orchestrator.start(channel="web_chat", language=inbound.language or "en", recording_consent="granted", tags=[f"channel:{channel}"])
        await svc.repo.put("settings", {"id": f"chan-{map_id}", "conv_id": conv.id, "channel": channel, "key_hash": map_id, "ts": time.time()})
    before = len(conv.messages)
    res = await svc.orchestrator.handle_message(conv.id, inbound.text, source=channel)
    conv = await svc.store.get(conv.id)
    new = [m for m in conv.messages[before:] if m.role in ("agent_ai", "agent_human", "system_notice") and m.visible_to_customer]
    rendered = [adapter.render_outbound(m.text, inbound.conversation_key, {**inbound.meta, "message_id": inbound.external_id}) for m in new]
    for m in new:
        conv.outbox.append({"kind": "channel_message", "channel": channel, "to": inbound.conversation_key[-4:].rjust(8, "•"), "body": m.text[:160], "ts": m.ts, "simulated": adapter.simulated})
    await svc.store.save(conv, publish=False)
    result = {"conversation_id": conv.id, "message_id": inbound.external_id, "replies": rendered, "status": res.get("status"), "duplicate": False}
    await svc.repo.put("idempotency", {"id": idem_id, "key": f"msg:{channel}:{inbound.external_id}", "result": result, "ts": time.time()}, ttl=7 * 86400)
    return result


@router.post("/api/chat/channels/{channel}/receipt")
async def channel_receipt(channel: str, payload: dict[str, Any]) -> dict[str, Any]:
    adapter = ADAPTERS.get(channel)
    if adapter is None:
        raise HTTPException(404, {"error": "unknown_channel"})
    return adapter.delivery_receipt(payload)


@router.websocket("/ws/chat/{conv_id}")
async def ws_chat(ws: WebSocket, conv_id: str) -> None:
    svc = ws.app.state.services
    if not ws_origin_ok({k.lower(): v for k, v in ws.headers.items()}):
        await ws.close(code=1008)
        return
    conv = await svc.store.get(conv_id)
    if conv is None:
        await ws.close(code=4404)
        return
    await ws.accept()
    sub = svc.bus.subscribe([f"conv:{conv_id}"])
    busy = asyncio.Event()
    send_lock = asyncio.Lock()

    async def send(ev: dict[str, Any]) -> None:
        async with send_lock:
            await ws.send_text(json.dumps(ev, default=str))

    async def forward() -> None:
        while True:
            ev = await sub.get(timeout=20)
            if ev is None:
                await send({"type": "ping"})
                continue
            if busy.is_set():
                continue
            if (ev.get("type") == "message" and ev["message"]["role"] in ("agent_human", "system_notice", "supervisor")) or ev.get("type") == "status":
                await send(ev)

    fwd = asyncio.create_task(forward())
    try:
        await send({"type": "state", "session": view(svc, conv)})
        sent_times: list[float] = []
        while True:
            raw = await ws.receive_text()
            if len(raw) > 6000:
                await send({"type": "error", "error": "payload_too_large"})
                continue
            now = time.time()
            sent_times = [t for t in sent_times if now - t < 60]
            if len(sent_times) >= 30:
                await send({"type": "error", "error": "rate_limited"})
                continue
            sent_times.append(now)
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = msg.get("type")
            if kind == "ping":
                await send({"type": "pong"})
            elif kind == "message" and isinstance(msg.get("text"), str):
                busy.set()
                try:
                    await svc.orchestrator.handle_message(conv_id, msg["text"][:2000], send)
                except ConversationClosed:
                    await send({"type": "error", "error": "conversation_closed"})
                except Exception as exc:
                    await send({"type": "error", "error": type(exc).__name__})
                finally:
                    busy.clear()
                    c = await svc.store.get(conv_id)
                    if c:
                        await send({"type": "state", "session": view(svc, c)})
            elif kind == "confirm":
                c = await svc.orchestrator.confirm(conv_id, accept=bool(msg.get("accept", True)), action_id=msg.get("action_id"))
                await send({"type": "state", "session": view(svc, c)})
    except WebSocketDisconnect:
        pass
    finally:
        fwd.cancel()
        sub.close()
