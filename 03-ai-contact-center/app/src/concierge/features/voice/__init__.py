"""CC-02 Real-time voice agent: browser voice via WebSocket relay to Azure OpenAI Realtime (server VAD, barge-in, tools, transcripts,
latency metrics), STT -> LLM -> TTS fallback, and provider-neutral telephony adapters (SIP to Realtime, Teams Phone Extensibility,
ACS Call Automation legacy) behind one interface with a simulator - no PSTN number is provisioned."""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ...core import i18n
from ...core.ai.base import BudgetExceededError
from ...core.money import speakable_pl
from ...core.registry import EPIC_A, FeatureInfo
from ...core.security import ws_origin_ok
from .session import VoiceSession
from .telephony import (
    ADAPTERS,
    CallMachine,
    SimulatedCallControl,
    TelephonyEvent,
    acs_event,
    acs_media_to_pcm,
    acs_metadata_frame,
    adapter_for,
    caller_language,
    pcm_to_acs_media,
    sip_event,
    teams_event,
)
from .upstream import AzureRealtimeUpstream, FakeRealtimeUpstream, offline_script

FEATURES = [
    FeatureInfo(
        "CC-02", "Real-time voice agent", EPIC_A, "P0", "/call", "/api/voice",
        "Browser voice over a WebSocket relay to Azure OpenAI Realtime (gpt-realtime-2.1-mini, fallback gpt-realtime-mini): server VAD, barge-in, tool calling, live transcripts, turn-latency metrics; STT->LLM->TTS fallback; telephony adapters (SIP to Realtime, Teams Phone extensibility, ACS Call Automation legacy) behind one interface - simulated, PSTN not provisioned.",
    ),
]  # fmt: skip

router = APIRouter(tags=["voice (CC-02)"])
MAX_VOICE = 3


def upstream_factory(svc: Any, conv_id: str):
    if svc.settings.is_azure:
        return lambda dep: AzureRealtimeUpstream(svc.settings, dep)
    return lambda dep: FakeRealtimeUpstream(offline_script(svc, conv_id))


class VoiceStart(BaseModel):
    language: str | None = Field(None, max_length=8, description="Conversation language; omitted = the request locale")
    recording_consent: str = Field("granted", pattern="^(pending|granted|declined)$")


class TextTurn(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    conversation_id: str | None = None
    language: str | None = Field(None, max_length=8, description="Conversation language; omitted = the request locale")
    mode: str = Field("auto", pattern="^(auto|realtime|pipeline)$")
    wait_s: float = Field(40, ge=5, le=60)


@router.get("/api/voice/config")
async def voice_config(request: Request) -> dict[str, Any]:
    svc = request.app.state.services
    s = svc.settings
    return {
        "mode": "azure-realtime" if s.is_azure else "offline-fake-realtime", "realtime_model": s.deployment("realtime"), "fallback_model": s.deployment("realtime_fallback"),
        "audio": {"format": "pcm16", "sample_rate": 24000, "channels": 1, "worklet": "/worklets/pcm-capture.js"}, "vad": "server_vad (threshold 0.5, 500 ms silence, interrupt_response)",
        "fallback_pipeline": "Azure AI Speech fast transcription -> chat model + tools -> Azure AI Speech neural TTS" if s.is_azure else "offline stub",
        "telephony": {"provisioned": False, "adapters": [{"id": a.id, "name": a.info["name"], "role": a.info["role"]} for a in ADAPTERS.values()], "note": "PSTN is NOT provisioned in this demo: telephony adapters (SIP to Realtime, Teams Phone Extensibility, ACS Call Automation legacy) sit behind one provider-neutral interface and are exercised by a simulator."},
        "max_concurrent": MAX_VOICE, "active": svc.ext.get("voice_active", 0),
    }


@router.post("/api/voice/sessions")
async def start(body: VoiceStart, request: Request) -> dict[str, Any]:
    svc = request.app.state.services
    conv = await svc.orchestrator.start(channel="voice", language=body.language or i18n.current_locale(), recording_consent=body.recording_consent)
    return {"conversation_id": conv.id, "ws": f"/ws/voice/{conv.id}", "language": conv.language}


@router.get("/api/voice/metrics")
async def metrics(request: Request) -> dict[str, Any]:
    svc = request.app.state.services
    docs = await svc.repo.query("conversations", {"channel": "voice"}, limit=300)
    lat = sorted(x for d in docs for x in (d.get("metrics") or {}).get("voice_latency_ms", []))
    live = list(svc.meter.latency.get("voice_turn", []))
    series = sorted(lat + live)

    def pct(q: float) -> float | None:
        return round(series[int(q * (len(series) - 1))], 1) if series else None

    return {"turns_measured": len(series), "turn_latency_ms": {"p50": pct(0.5), "p95": pct(0.95), "min": series[0] if series else None, "max": series[-1] if series else None}, "target_p95_ms": 800, "definition": "end of user speech (server VAD) -> first audio delta; text turns: text sent -> first audio delta", "voice_conversations": len(docs)}


class _Sink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.audio = 0
        self.done = asyncio.Event()

    async def json(self, ev: dict[str, Any]) -> None:
        self.events.append(ev)
        if ev.get("type") == "state" and ev.get("state") == "listening" and any(e.get("type") == "transcript" and e.get("role") == "agent" and e.get("final") for e in self.events):
            self.done.set()
        if ev.get("type") == "error":
            self.done.set()

    async def bytes(self, b: bytes) -> None:
        self.audio += len(b)


@router.post("/api/voice/text-turn")
async def text_turn(body: TextTurn, request: Request) -> dict[str, Any]:
    """Prove the voice path without a human: text in -> (realtime session | STT->LLM->TTS fallback) -> audio + transcript out."""
    svc = request.app.state.services
    if svc.ext.get("voice_active", 0) >= MAX_VOICE:
        raise HTTPException(503, {"error": "voice_busy", "message": "All demo voice lines are busy; try again in a moment."})
    conv_id = body.conversation_id
    if conv_id is None:
        conv_id = (await svc.orchestrator.start(channel="voice", language=body.language or i18n.current_locale(), recording_consent="granted")).id
    sink = _Sink()
    session = VoiceSession(svc, conv_id, sink.json, sink.bytes, upstream_factory=upstream_factory(svc, conv_id), mode=body.mode)
    svc.ext["voice_active"] = svc.ext.get("voice_active", 0) + 1
    t0 = time.perf_counter()
    try:
        await session.start()
        await asyncio.wait_for(sink.done.wait(), timeout=body.wait_s)  # greeting (disclosure) first
        sink.done.clear()
        sink.events.append({"type": "marker", "name": "text-input"})
        await session.feed_text(body.text)
        await asyncio.wait_for(sink.done.wait(), timeout=body.wait_s)
        await asyncio.sleep(0.3)
    except BudgetExceededError as exc:
        raise HTTPException(429, {"error": "daily_ai_budget_exceeded", "message": str(exc)}) from exc
    except TimeoutError:
        pass
    finally:
        await session.close()
        svc.ext["voice_active"] = max(0, svc.ext.get("voice_active", 1) - 1)
    marker = next((i for i, e in enumerate(sink.events) if e.get("name") == "text-input"), 0)
    after = sink.events[marker:]
    transcript = [e["text"] for e in after if e.get("type") == "transcript" and e.get("role") == "agent" and e.get("final")]
    tools = [{"name": e["name"], "status": e["status"]} for e in after if e.get("type") == "tool" and e.get("status") != "running"]
    lat = [e["first_audio_ms"] for e in sink.events if e.get("type") == "latency"]
    await svc.meter.flush(force=True)
    return {
        "conversation_id": conv_id, "mode": session.mode, "model": session.model_used or "pipeline", "greeting": [e["text"] for e in sink.events[:marker] if e.get("type") == "transcript" and e.get("role") == "agent" and e.get("final")][:1],
        "transcript": transcript, "audio_bytes": sink.audio, "audio_seconds": round(sink.audio / 2 / 24000, 2), "tools": tools, "first_audio_ms": lat[-1] if lat else None, "total_ms": round((time.perf_counter() - t0) * 1000), "events": len(sink.events),
    }  # fmt: skip


@router.post("/api/voice/pipeline-audio")
async def pipeline_audio(request: Request, file: UploadFile = File(...), conversation_id: str = Form(...), language: str = Form("en")) -> dict[str, Any]:
    """Fallback pipeline with an uploaded utterance (wav): STT -> agent loop (tools) -> TTS."""
    svc = request.app.state.services
    data = await file.read(3_000_000)
    stt = await svc.speech.transcribe(data, mime=file.content_type or "audio/wav", language=language)
    if not stt.text:
        raise HTTPException(422, {"error": "no_speech", "message": "No speech was recognised."})
    res = await svc.orchestrator.handle_message(conversation_id, stt.text, source="voice-pipeline")
    reply = (res.get("message") or {}).get("text", "")
    spoken = reply.replace("[K1]", "")
    audio, mime = await svc.speech.synthesize(speakable_pl(spoken) if language == "pl" else spoken, language=language)
    return {"transcript": stt.text, "reply": reply, "audio_b64": base64.b64encode(audio).decode(), "mime": mime, "status": res.get("status")}


@router.websocket("/ws/voice/{conv_id}")
async def ws_voice(ws: WebSocket, conv_id: str, mode: str = "auto") -> None:
    svc = ws.app.state.services
    if not ws_origin_ok({k.lower(): v for k, v in ws.headers.items()}):
        await ws.close(code=1008)
        return
    conv = await svc.store.get(conv_id)
    if conv is None:
        await ws.close(code=4404)
        return
    await ws.accept()
    lock = asyncio.Lock()

    async def send_json(ev: dict[str, Any]) -> None:
        async with lock:
            await ws.send_text(json.dumps(ev, default=str))

    async def send_audio(b: bytes) -> None:
        async with lock:
            await ws.send_bytes(b)

    if svc.ext.get("voice_active", 0) >= MAX_VOICE:
        await send_json({"type": "error", "error": "voice_busy", "message": "All demo voice lines are busy; try again shortly or use chat."})
        await ws.close(code=1013)
        return
    svc.ext["voice_active"] = svc.ext.get("voice_active", 0) + 1
    session = VoiceSession(svc, conv_id, send_json, send_audio, upstream_factory=upstream_factory(svc, conv_id), mode=mode)
    try:
        try:
            await session.start()
        except BudgetExceededError as exc:
            await send_json({"type": "error", "error": "daily_ai_budget_exceeded", "message": str(exc)})
            return
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes"):
                await session.feed_audio(msg["bytes"])
            elif msg.get("text"):
                try:
                    cmd = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue
                kind = cmd.get("type")
                if kind == "text" and isinstance(cmd.get("text"), str):
                    try:
                        await session.feed_text(cmd["text"])
                    except BudgetExceededError as exc:
                        await send_json({"type": "error", "error": "daily_ai_budget_exceeded", "message": str(exc)})
                elif kind == "interrupt":
                    await session.interrupt()
                elif kind == "dtmf" and isinstance(cmd.get("digit"), str):
                    await session.dtmf(cmd["digit"][:1])
                elif kind == "mute":
                    session.muted = bool(cmd.get("muted"))
                elif kind == "end":
                    await session.end()
                    break
    except Exception:
        pass
    finally:
        await session.close()
        svc.ext["voice_active"] = max(0, svc.ext.get("voice_active", 1) - 1)


# ------------------------------------------------------------------------------------------ telephony (provider-neutral adapters)
def _machines(svc: Any) -> dict[str, CallMachine]:
    return svc.ext.setdefault("calls", {})


def _caller_language(caller: str | None) -> str:
    """Conversation language of an inbound call: Polish for Polish numbers (+48 / 0048, any provider notation), English otherwise (as before)."""
    return caller_language(caller)


async def apply_event(svc: Any, adapter: Any, ev: TelephonyEvent, base_url: str = "") -> dict[str, Any]:
    """Neutral event -> state machine -> native commands (rendered by the adapter) -> side effects on the conversation."""
    machines = _machines(svc)
    machine = machines.get(ev.call_id) or CallMachine(ev.call_id, f"{base_url.replace('http', 'ws')}/ws/telephony/{ev.call_id}", provider=adapter.id)
    machines[ev.call_id] = machine
    actions = machine.on(ev)
    call = {"call_id": ev.call_id, "context": machine.context, "caller": machine.caller, "model": svc.settings.deployment("realtime")}
    commands = [c for c in (adapter.render(a, call) for a in actions) if c]
    machine.commands.extend(commands)
    svc.ext.setdefault("call_control", SimulatedCallControl()).execute(commands)
    for a in actions:
        if a.kind == "bind_voice_session":
            conv = await svc.orchestrator.start(channel="voice", language=_caller_language(machine.caller), recording_consent="pending", tags=["telephony", adapter.provider])
            machine.conv_id = conv.id
        elif a.kind == "record_consent" and machine.conv_id:
            await svc.orchestrator.set_consent(machine.conv_id, a.params["recording"] == "granted")
        elif a.kind == "close_conversation" and machine.conv_id:
            await svc.orchestrator.close(machine.conv_id, by="telephony", resolved=None)
    snap = machine.snapshot() | {"adapter": adapter.info["name"]}
    await svc.repo.put("telephony_calls", {"id": ev.call_id, **snap}, ttl=30 * 86400)
    return snap


async def process_telephony_event(svc: Any, raw: dict[str, Any], base_url: str = "", provider: str | None = None) -> dict[str, Any]:
    adapter = adapter_for(raw, provider)
    return await apply_event(svc, adapter, adapter.translate(raw), base_url)


@router.get("/api/voice/telephony/adapters")
async def telephony_adapters() -> dict[str, Any]:
    return {
        "pstn_provisioned": False,
        "adapters": [{"id": a.id, "provider": a.provider, **a.info} for a in ADAPTERS.values()],
        "interface": "TelephonyAdapter: matches(raw) / translate(raw) -> neutral event / render(action) -> native command; one CallMachine behind all adapters",
        "states": ["idle", "ringing", "answering", "connected", "consent", "listening", "transferring", "disconnected"],
        "production": "SIP trunk or SBC -> Azure OpenAI Realtime SIP (default); Teams Phone Extensibility for Teams-aligned estates; ACS Call Automation only for tenants that already run on it (retires 30 Sep 2028).",
    }


@router.post("/api/voice/telephony/events")
async def telephony_events(request: Request, provider: str | None = None) -> Any:
    """Provider webhook (Event Grid / CloudEvents, Graph change notifications, Realtime SIP webhook); the adapter is chosen by payload shape or `provider`."""
    svc = request.app.state.services
    token = request.query_params.get("validationToken")  # Graph subscription validation handshake
    if token:
        return PlainTextResponse(token)
    body = await request.json()
    events = body.get("value", [body]) if isinstance(body, dict) and isinstance(body.get("value"), list) else (body if isinstance(body, list) else [body])
    results = []
    for raw in events:
        if raw.get("eventType") == "Microsoft.EventGrid.SubscriptionValidationEvent":
            return {"validationResponse": raw["data"]["validationCode"]}
        try:
            results.append(await process_telephony_event(svc, raw, str(request.base_url).rstrip("/"), provider))
        except ValueError as exc:
            raise HTTPException(422, {"error": "unsupported_event", "message": str(exc)}) from exc
    return {"processed": len(results), "calls": results}


class SimulateBody(BaseModel):
    scenario: str = Field("damaged_sofa", pattern="^(damaged_sofa|decline_consent|hangup_early|silent_consent|transfer)$")
    provider: str = Field("sip", pattern="^(sip|teams|acs)$")
    consent_digit: str | None = None
    language: str = Field("en", pattern="^(en|pl)$", description="pl simulates a Polish caller (+48 number): the call is answered in Polish")


SIM_CALLERS = {"en": ("+4915550001234", "+49305550000"), "pl": ("+48225550190", "+48225550000")}
SIM_UTTERANCES = {
    "en": ("Hello, my sofa arrived damaged, order CH-100231.", "What is your return policy?"),
    "pl": ("Dzień dobry, moja sofa dotarła uszkodzona, zamówienie CH-100350.", "Jakie są zasady zwrotów?"),
}


def _script(provider: str, call_id: str, digit: str | None, language: str = "en") -> list[tuple[str, dict[str, Any]]]:
    """(label, native event) sequence for the first four steps of a simulated inbound call; the fourth is the consent answer."""
    caller, callee = SIM_CALLERS.get(language, SIM_CALLERS["en"])
    if provider == "acs":
        steps = [("IncomingCall", acs_event("IncomingCall", call_id, **{"from": {"rawId": f"4:{caller}"}, "to": {"rawId": f"4:{callee}"}, "incomingCallContext": "ctx-" + call_id})), ("CallConnected", acs_event("CallConnected", call_id)), ("PlayCompleted", acs_event("PlayCompleted", call_id))]
        steps.append(("RecognizeCompleted", acs_event("RecognizeCompleted", call_id, dtmfResult={"tones": [digit]})) if digit else ("RecognizeFailed", acs_event("RecognizeFailed", call_id)))
        return steps
    if provider == "teams":
        steps = [("call incoming", teams_event("incoming", call_id, source={"identity": {"phone": {"id": caller}}})), ("call established", teams_event("established", call_id)), ("playPrompt completed", teams_event("play_completed", call_id))]
        steps.append(("tone received", teams_event("tone", call_id, digit=digit)) if digit else ("no tone (timer)", teams_event("tone_timeout", call_id)))
        return steps
    steps = [("realtime.call.incoming", sip_event("incoming", call_id, **{"from": caller, "to": callee})), ("realtime.call.connected", sip_event("connected", call_id)), ("response.done (consent question)", sip_event("prompt_done", call_id))]
    steps.append(("consent.captured", sip_event("consent", call_id, recording="granted" if digit == "1" else "declined")))
    return steps


def _end_event(provider: str, call_id: str) -> tuple[str, dict[str, Any]]:
    if provider == "acs":
        return "CallDisconnected", acs_event("CallDisconnected", call_id)
    if provider == "teams":
        return "call terminated", teams_event("terminated", call_id)
    return "realtime.call.ended", sip_event("ended", call_id, reason="bye")


def _transfer_accepted(provider: str, call_id: str) -> dict[str, Any]:
    return {"sip": lambda: sip_event("refer_accepted", call_id), "teams": lambda: teams_event("transfer_accepted", call_id), "acs": lambda: acs_event("TransferAccepted", call_id)}[provider]()


@router.post("/api/voice/telephony/simulate")
async def simulate_call(body: SimulateBody, request: Request) -> dict[str, Any]:
    """Drives a complete simulated inbound call through the chosen provider's event contract, the neutral state machine and the voice session (text input)."""
    svc = request.app.state.services
    call_id = f"sim-{uuid.uuid4().hex[:8]}"
    base = str(request.base_url).rstrip("/")
    adapter = ADAPTERS[body.provider]
    timeline: list[dict[str, Any]] = []
    seen = [0]

    async def feed(label: str, ev: TelephonyEvent) -> dict[str, Any]:
        snap = await apply_event(svc, adapter, ev, base)
        timeline.append({"event": label, "state": snap["state"], "actions": [a["kind"] for a in snap["actions"][-3:]], "commands": [c["op"] for c in snap["commands"][seen[0]:]]})
        seen[0] = len(snap["commands"])
        return snap

    async def fire(label: str, raw: dict[str, Any]) -> dict[str, Any]:
        return await feed(label, adapter.translate(raw))

    digit = body.consent_digit or {"decline_consent": "2", "silent_consent": None}.get(body.scenario, "1")
    script = _script(body.provider, call_id, digit, body.language)
    for label, raw in script[:3]:
        await fire(label, raw)
    if body.scenario == "hangup_early":
        snap = await fire(*_end_event(body.provider, call_id))
        return {"call_id": call_id, "provider": body.provider, "timeline": timeline, "final": snap, "provisioned_pstn": False}
    snap = await fire(*script[3])
    exchange: dict[str, Any] = {}
    if snap["conversation_id"]:
        sink = _Sink()
        session = VoiceSession(svc, snap["conversation_id"], sink.json, sink.bytes, upstream_factory=upstream_factory(svc, snap["conversation_id"]), mode="auto")
        try:
            await session.start()
            await asyncio.wait_for(sink.done.wait(), timeout=40)
            sink.done.clear()
            damaged, policy = SIM_UTTERANCES.get(body.language, SIM_UTTERANCES["en"])
            await session.feed_text(damaged if body.scenario in ("damaged_sofa", "transfer") else policy)
            await asyncio.wait_for(sink.done.wait(), timeout=40)
        except (TimeoutError, BudgetExceededError):
            pass
        finally:
            await session.close()
        exchange = {"agent_lines": [e["text"] for e in sink.events if e.get("type") == "transcript" and e.get("role") == "agent" and e.get("final")], "audio_seconds": round(sink.audio / 2 / 24000, 2), "mode": session.mode}
    if body.scenario == "transfer":
        await feed("transfer requested (escalation)", TelephonyEvent("transfer_requested", call_id, {"target": "sip:escalations@contoso-home.example"}))
        await fire("transfer accepted", _transfer_accepted(body.provider, call_id))
    machine = _machines(svc)[call_id]
    final = machine.snapshot() | {"adapter": adapter.info["name"]} if machine.state == "disconnected" else await fire(*_end_event(body.provider, call_id))
    return {"call_id": call_id, "provider": body.provider, "timeline": timeline, "exchange": exchange, "final": final, "provisioned_pstn": False}


@router.get("/api/voice/telephony/calls")
async def calls(request: Request) -> list[dict[str, Any]]:
    rows = await request.app.state.services.repo.query("telephony_calls", order_by="_ts", desc=True, limit=20)
    return [{k: v for k, v in r.items() if k not in ("pk", "_ts", "ttl")} for r in rows]


@router.websocket("/ws/telephony/{call_id}")
async def ws_telephony(ws: WebSocket, call_id: str) -> None:
    """ACS-format media-streaming bridge (legacy path): AudioMetadata/AudioData frames in, AudioData / StopAudio frames out, bridged to a voice session. The SIP path carries media inside the Realtime session and needs no bridge."""
    svc = ws.app.state.services
    machine = _machines(svc).get(call_id)
    conv_id = getattr(machine, "conv_id", None) if machine else None
    if not conv_id:
        await ws.close(code=4404)
        return
    await ws.accept()
    lock = asyncio.Lock()

    async def send_json(ev: dict[str, Any]) -> None:
        if ev.get("type") == "audio.clear":
            async with lock:
                await ws.send_text(json.dumps({"kind": "StopAudio", "stopAudio": {}}))

    async def send_audio(b: bytes) -> None:
        async with lock:
            await ws.send_text(json.dumps(pcm_to_acs_media(b)))

    session = VoiceSession(svc, conv_id, send_json, send_audio, upstream_factory=upstream_factory(svc, conv_id))
    try:
        await session.start()
        await ws.send_text(json.dumps(acs_metadata_frame()))
        while True:
            raw = await ws.receive_text()
            pcm = acs_media_to_pcm(json.loads(raw))
            if pcm:
                await session.feed_audio(pcm)
    except Exception:
        pass
    finally:
        await session.close()
