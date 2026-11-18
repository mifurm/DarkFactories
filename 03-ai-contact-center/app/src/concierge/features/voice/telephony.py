"""Telephony (CC-02): a provider-neutral `TelephonyAdapter` interface and one event-driven call state machine, with three adapters:

  * `RealtimeSipAdapter`            - SIP trunk/SBC -> Azure OpenAI Realtime SIP endpoint (default production path; Voice Live SIP is in preview)
  * `TeamsPhoneExtensibilityAdapter`- Teams-aligned estates (strategic path; simulator-backed, event shapes follow Microsoft Graph call notifications)
  * `AcsCallAutomationAdapter`      - Azure Communication Services Call Automation (LEGACY: ACS retires as a standalone offering on 30 Sep 2028)

Every adapter translates native events into the same neutral events (incoming_call, call_connected, play_completed, recognize_completed,
call_disconnected, ...) and renders the machine's neutral actions as native call-control commands. A simulator drives all three; no PSTN
number, carrier or ACS resource is provisioned in this demo - production paths are documented in ARCHITECTURE.md (section 7, ADR-02)."""

from __future__ import annotations

import base64
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

ACS_EVENT_TYPES = {
    "Microsoft.Communication.IncomingCall": "incoming_call",
    "Microsoft.Communication.CallConnected": "call_connected",
    "Microsoft.Communication.PlayCompleted": "play_completed",
    "Microsoft.Communication.PlayFailed": "play_failed",
    "Microsoft.Communication.RecognizeCompleted": "recognize_completed",
    "Microsoft.Communication.RecognizeFailed": "recognize_failed",
    "Microsoft.Communication.CallDisconnected": "call_disconnected",
    "Microsoft.Communication.MediaStreamingStarted": "media_streaming_started",
    "Microsoft.Communication.TransferAccepted": "transfer_accepted",
}


@dataclass
class TelephonyEvent:
    kind: str  # normalised, provider-neutral
    call_id: str
    data: dict[str, Any] = field(default_factory=dict)
    raw_type: str = ""


@dataclass
class Action:
    kind: str  # answer | start_media_streaming | play | recognize_dtmf | bind_voice_session | transfer | hangup | record_consent
    params: dict[str, Any] = field(default_factory=dict)


class TelephonyAdapter(Protocol):
    """Provider-specific edge of the call path; nothing behind it (state machine, voice session, agents, tools, handoff) sees provider types."""

    id: str
    provider: str
    info: dict[str, Any]

    def matches(self, raw: dict[str, Any]) -> bool: ...

    def translate(self, raw: dict[str, Any]) -> TelephonyEvent: ...

    def render(self, action: Action, call: dict[str, Any]) -> dict[str, Any] | None: ...


class State:
    IDLE, RINGING, ANSWERING, CONNECTED, CONSENT, LISTENING, TRANSFERRING, DISCONNECTED = "idle", "ringing", "answering", "connected", "consent", "listening", "transferring", "disconnected"


class CallMachine:
    """Provider-neutral call state machine: events in -> actions out. Transitions are explicit and table-testable."""

    TRANSITIONS: dict[tuple[str, str], str] = {
        (State.IDLE, "incoming_call"): State.RINGING,
        (State.RINGING, "incoming_call"): State.RINGING,
        (State.ANSWERING, "call_connected"): State.CONNECTED,
        (State.CONNECTED, "media_streaming_started"): State.CONNECTED,
        (State.CONNECTED, "play_completed"): State.CONSENT,
        (State.CONSENT, "recognize_completed"): State.LISTENING,
        (State.CONSENT, "recognize_failed"): State.LISTENING,
        (State.CONSENT, "consent_captured"): State.LISTENING,
        (State.LISTENING, "transfer_requested"): State.TRANSFERRING,
        (State.TRANSFERRING, "transfer_accepted"): State.DISCONNECTED,
    }

    def __init__(self, call_id: str, media_url: str, callback_url: str = "/api/voice/telephony/events", provider: str = "neutral") -> None:
        self.call_id = call_id
        self.provider = provider
        self.state = State.IDLE
        self.media_url = media_url
        self.callback_url = callback_url
        self.log: list[dict[str, Any]] = []
        self.actions: list[Action] = []
        self.consent: str | None = None
        self.caller: str | None = None
        self.context: str | None = None
        self.conv_id: str | None = None
        self.commands: list[dict[str, Any]] = []  # native call-control commands rendered by the adapter

    # events that are only meaningful in certain states (duplicate / late deliveries are logged and ignored, never re-run)
    ALLOWED: dict[str, set[str]] = {
        "incoming_call": {State.IDLE, State.RINGING},
        "call_connected": {State.ANSWERING},
        "media_streaming_started": {State.CONNECTED, State.CONSENT, State.LISTENING},
    }

    def on(self, ev: TelephonyEvent) -> list[Action]:
        prev = self.state
        acts: list[Action] = []
        allowed = self.ALLOWED.get(ev.kind)
        if prev == State.DISCONNECTED or (allowed is not None and prev not in allowed):
            self.log.append({"ts": time.time(), "ignored": ev.kind, "state": prev})
            return []
        if ev.kind == "call_disconnected":
            self.state = State.DISCONNECTED
            acts.append(Action("close_conversation", {"reason": ev.data.get("reason", "caller hung up")}))
        elif ev.kind == "incoming_call":
            self.caller = ev.data.get("from")
            self.context = ev.data.get("incoming_call_context")
            self.state = State.ANSWERING  # answered immediately
            acts.append(Action("answer", {"callback_uri": self.callback_url, "media_streaming": {"transport_url": self.media_url, "content_type": "audio", "audio_channel": "unmixed", "audio_format": "Pcm24KMono", "start_media_streaming": True}}))
        elif ev.kind == "call_connected":
            self.state = State.CONNECTED
            acts.append(Action("bind_voice_session", {"channel": "voice", "caller": self.caller}))
            acts.append(Action("play", {"text_key": "disclosure_and_consent", "prompt": "AI disclosure + recording consent: press 1 to accept, 2 to decline"}))
        elif ev.kind == "media_streaming_started":
            acts.append(Action("attach_media_stream", {"url": self.media_url}))
        elif ev.kind == "play_completed" and self.state == State.CONNECTED:
            self.state = State.CONSENT
            acts.append(Action("recognize_dtmf", {"max_digits": 1, "timeout_s": 8, "prompt_key": "consent"}))
        elif ev.kind in ("recognize_completed", "recognize_failed", "consent_captured") and self.state == State.CONSENT:
            if ev.kind == "consent_captured":  # spoken consent on the SIP path (no DTMF leg)
                self.consent = "granted" if ev.data.get("recording") == "granted" else "declined"
                via = "speech"
            else:
                digit = (ev.data.get("tone") or "").strip()
                self.consent = "granted" if digit == "1" else "declined"  # silence, timeouts and anything but "1" never grant recording consent
                via = "dtmf" if digit else "timeout-declined"
            self.state = State.LISTENING
            acts.append(Action("record_consent", {"recording": self.consent, "via": via}))
            acts.append(Action("hand_audio_to_voice_session", {"mode": "realtime"}))
        elif ev.kind == "transfer_requested" and self.state == State.LISTENING:
            self.state = State.TRANSFERRING
            acts.append(Action("transfer", {"target": ev.data.get("target", "sip:escalations@contoso-home.example")}))
        elif ev.kind == "transfer_accepted" and self.state == State.TRANSFERRING:
            self.state = State.DISCONNECTED
            acts.append(Action("hangup", {"reason": "transferred"}))
        elif (prev, ev.kind) not in self.TRANSITIONS:
            self.log.append({"ts": time.time(), "ignored": ev.kind, "state": prev})
            return []
        self.log.append({"ts": time.time(), "event": ev.kind, "from": prev, "to": self.state, "actions": [a.kind for a in acts]})
        self.actions.extend(acts)
        return acts

    def snapshot(self) -> dict[str, Any]:
        return {"call_id": self.call_id, "provider": self.provider, "state": self.state, "caller": self.caller, "consent": self.consent, "log": self.log, "actions": [asdict(a) for a in self.actions], "commands": self.commands, "conversation_id": self.conv_id}


class AcsCallAutomationAdapter:
    """LEGACY path: Azure Communication Services Call Automation CloudEvents / Event Grid events <-> neutral events.
    ACS retires as a standalone offering on 30 Sep 2028 (Call Automation survives only in Teams-aligned scenarios); from 23 Oct 2026 new
    customers cannot acquire PSTN numbers there. Kept for tenants that already run on it."""

    id = "acs"
    provider = "azure-communication-services"
    info = {
        "name": "Azure Communication Services Call Automation", "role": "legacy path (tenants already on ACS)", "strategic": False,
        "status": "Supported until 30 Sep 2028; new PSTN numbers and onboarding of retiring services stop on 23 Oct 2026; Call Automation continues only in Teams-aligned scenarios.",
        "inbound": "Event Grid / CloudEvents webhook (Microsoft.Communication.*)", "media": "WebSocket audio streaming (PCM 24 kHz, unmixed)",
    }  # fmt: skip

    def matches(self, raw: dict[str, Any]) -> bool:
        return str(raw.get("type") or raw.get("eventType") or "").startswith("Microsoft.Communication.")

    def translate(self, raw: dict[str, Any]) -> TelephonyEvent:
        etype = raw.get("type") or raw.get("eventType") or ""
        kind = ACS_EVENT_TYPES.get(etype)
        if kind is None:
            raise ValueError(f"unsupported ACS event type: {etype!r}")
        data = raw.get("data", {})
        call_id = data.get("callConnectionId") or data.get("incomingCallContext", "")[:24] or raw.get("id", "")
        norm: dict[str, Any] = {}
        if kind == "incoming_call":
            norm = {"from": (data.get("from") or {}).get("rawId") or (data.get("from") or {}).get("phoneNumber", {}).get("value"), "to": (data.get("to") or {}).get("rawId"), "incoming_call_context": data.get("incomingCallContext")}
        elif kind == "recognize_completed":
            norm = {"tone": (data.get("dtmfResult") or {}).get("tones", [None])[0] if (data.get("dtmfResult") or {}).get("tones") else (data.get("recognizeResult") or {}).get("tone")}
        elif kind in ("call_disconnected",):
            norm = {"reason": (data.get("resultInformation") or {}).get("message", "")}
        return TelephonyEvent(kind=kind, call_id=call_id, data=norm, raw_type=etype)

    def render(self, action: Action, call: dict[str, Any]) -> dict[str, Any] | None:
        cid, p = call["call_id"], action.params
        base = f"/calling/callConnections/{cid}"
        if action.kind == "answer":
            ms = p["media_streaming"]
            return {"op": "AnswerCall", "method": "POST", "path": "/calling/callConnections:answer", "body": {"incomingCallContext": call.get("context"), "callbackUri": p["callback_uri"], "mediaStreamingOptions": {"transportUrl": ms["transport_url"], "transportType": "websocket", "contentType": "audio", "audioChannelType": ms["audio_channel"], "startMediaStreaming": True, "audioFormat": "pcm24KMono"}}}
        if action.kind == "play":
            return {"op": "Play", "method": "POST", "path": f"{base}:play", "body": {"playSources": [{"kind": "text", "text": {"text": p["prompt"]}}], "playTo": [call.get("caller")]}}
        if action.kind == "recognize_dtmf":
            return {"op": "StartRecognizing", "method": "POST", "path": f"{base}:recognize", "body": {"recognizeInputType": "dtmf", "dtmfOptions": {"maxTonesToCollect": p["max_digits"], "interToneTimeoutInSeconds": p["timeout_s"]}}}
        if action.kind == "transfer":
            return {"op": "TransferCallToParticipant", "method": "POST", "path": f"{base}:transferToParticipant", "body": {"targetParticipant": {"rawId": p["target"]}}}
        if action.kind == "hangup":
            return {"op": "HangUp", "method": "POST", "path": f"{base}:hangup", "body": {"forEveryone": True}}
        return None


class TeamsPhoneExtensibilityAdapter:
    """STRATEGIC path for Teams-aligned estates (Teams Phone Extensibility / Microsoft Graph cloud communications). Simulator-backed in this
    demo: the notification shapes follow Graph call resources (state incoming -> established -> terminated, operation completions, tone
    info) in simplified form and must be validated against the live service during the pilot."""

    id = "teams"
    provider = "teams-phone-extensibility"
    info = {
        "name": "Teams Phone Extensibility", "role": "strategic path for Teams-aligned estates", "strategic": True,
        "status": "Simulator-backed adapter; event and command shapes follow Microsoft Graph call notifications and are to be validated against the live service in the pilot.",
        "inbound": "Graph change notifications (call state, operation results, tone info)", "media": "service-hosted prompts; app-hosted media or the Realtime session for the agent conversation",
    }  # fmt: skip

    def matches(self, raw: dict[str, Any]) -> bool:
        return "resourceData" in raw

    @staticmethod
    def _call_id(resource: str) -> str:
        parts = [p for p in resource.split("/") if p]
        return parts[parts.index("calls") + 1] if "calls" in parts and parts.index("calls") + 1 < len(parts) else ""

    def translate(self, raw: dict[str, Any]) -> TelephonyEvent:
        rd = raw.get("resourceData") or {}
        otype = str(rd.get("@odata.type", ""))
        call_id = self._call_id(str(raw.get("resource", ""))) or rd.get("id", "")
        change, state = raw.get("changeType"), rd.get("state")
        if otype.endswith("call"):
            if change == "created" and state == "incoming":
                src = ((rd.get("source") or {}).get("identity") or {})
                caller = (src.get("phone") or {}).get("id") or (src.get("user") or {}).get("id")
                return TelephonyEvent("incoming_call", call_id, {"from": caller, "to": ((rd.get("targets") or [{}])[0].get("identity") or {}).get("user", {}).get("id"), "incoming_call_context": rd.get("callChainId")}, "graph.call.incoming")
            if state == "established":
                return TelephonyEvent("call_connected", call_id, {}, "graph.call.established")
            if state == "transferAccepted":
                return TelephonyEvent("transfer_accepted", call_id, {}, "graph.call.transferAccepted")
            if change == "deleted" or state == "terminated":
                return TelephonyEvent("call_disconnected", call_id, {"reason": (rd.get("resultInfo") or {}).get("message", "")}, "graph.call.terminated")
        if otype.endswith("playPromptOperation"):
            return TelephonyEvent("play_completed" if rd.get("status") == "completed" else "play_failed", call_id, {}, "graph.playPromptOperation")
        if otype.endswith("toneInfo"):
            if rd.get("timedOut"):  # Graph sends nothing when nobody presses a key: the controller's own timer raises this
                return TelephonyEvent("recognize_failed", call_id, {}, "controller.toneTimeout")
            tone = str(rd.get("tone", ""))
            return TelephonyEvent("recognize_completed", call_id, {"tone": tone.removeprefix("tone")}, "graph.toneInfo")
        raise ValueError(f"unsupported Teams/Graph notification: {otype!r} {change!r} {state!r}")

    def render(self, action: Action, call: dict[str, Any]) -> dict[str, Any] | None:
        base = f"/communications/calls/{call['call_id']}"
        p = action.params
        if action.kind == "answer":
            return {"op": "answer", "method": "POST", "path": f"{base}/answer", "body": {"callbackUri": p["callback_uri"], "acceptedModalities": ["audio"], "mediaConfig": {"@odata.type": "#microsoft.graph.serviceHostedMediaConfig"}}}
        if action.kind == "play":
            return {"op": "playPrompt", "method": "POST", "path": f"{base}/playPrompt", "body": {"prompts": [{"@odata.type": "#microsoft.graph.mediaPrompt", "mediaInfo": {"uri": "https://contoso-home.example/prompts/disclosure-consent.wav", "resourceId": "disclosure-consent"}}]}}
        if action.kind == "recognize_dtmf":
            return {"op": "subscribeToTone", "method": "POST", "path": f"{base}/subscribeToTone", "body": {"clientContext": "consent"}}
        if action.kind == "transfer":
            return {"op": "transfer", "method": "POST", "path": f"{base}/transfer", "body": {"transferTarget": {"endpointType": "default", "identity": {"user": {"id": p["target"]}}}}}
        if action.kind == "hangup":
            return {"op": "deleteCall", "method": "DELETE", "path": base, "body": None}
        return None


class RealtimeSipAdapter:
    """DEFAULT production path: SIP trunk / SBC -> Azure OpenAI Realtime SIP endpoint. The control service receives the `realtime.call.incoming`
    webhook, accepts the call with the session configuration, opens the control WebSocket by call_id and REFERs on escalation. The media never
    touches this app, so there is no DTMF leg: the agent asks for recording consent in speech (`consent.captured`). Controller-normalised events
    (`realtime.call.connected` after a successful accept, `realtime.call.ended` on BYE / socket close) complete the contract. Voice Live SIP is in preview."""

    id = "sip"
    provider = "azure-openai-realtime-sip"
    info = {
        "name": "SIP trunk -> Azure OpenAI Realtime SIP", "role": "default production path", "strategic": True,
        "status": "Realtime SIP is supported in Sweden Central and France Central; Voice Live SIP is in public preview. Simulator-backed here (no SIP trunk, no phone number).",
        "inbound": "realtime.call.incoming webhook + control WebSocket by call_id", "media": "carried inside the Realtime session (no media hop of our own)",
    }  # fmt: skip

    def matches(self, raw: dict[str, Any]) -> bool:
        return str(raw.get("type", "")).startswith(("realtime.", "response.", "consent."))

    def translate(self, raw: dict[str, Any]) -> TelephonyEvent:
        etype, data = str(raw.get("type", "")), raw.get("data") or {}
        call_id = data.get("call_id", "")
        if etype == "realtime.call.incoming":
            hdr = {h.get("name", "").lower(): h.get("value", "") for h in data.get("sip_headers", [])}
            return TelephonyEvent("incoming_call", call_id, {"from": hdr.get("from"), "to": hdr.get("to"), "incoming_call_context": hdr.get("call-id")}, etype)
        if etype == "realtime.call.connected":
            return TelephonyEvent("call_connected", call_id, {}, etype)
        if etype == "response.done":  # the spoken disclosure + consent question finished (control WebSocket)
            return TelephonyEvent("play_completed", call_id, {}, etype)
        if etype == "consent.captured":
            return TelephonyEvent("consent_captured", call_id, {"recording": data.get("recording", "declined")}, etype)
        if etype == "realtime.call.refer.accepted":
            return TelephonyEvent("transfer_accepted", call_id, {}, etype)
        if etype == "realtime.call.ended":
            return TelephonyEvent("call_disconnected", call_id, {"reason": data.get("reason", "")}, etype)
        raise ValueError(f"unsupported realtime SIP event type: {etype!r}")

    def render(self, action: Action, call: dict[str, Any]) -> dict[str, Any] | None:
        base = f"/openai/v1/realtime/calls/{call['call_id']}"
        if action.kind == "answer":
            return {"op": "accept", "method": "POST", "path": f"{base}/accept", "body": {"type": "realtime", "model": call.get("model", "gpt-realtime-2.1-mini"), "instructions": "<resolved by the control service: persona, language, policy>", "audio": {"input": {"turn_detection": {"type": "server_vad"}}, "output": {"voice": "marin"}}, "tools": "<tool schemas from the policy engine>"}}
        if action.kind == "play":
            return {"op": "response.create", "method": "WS", "path": f"wss://<resource>/openai/v1/realtime?call_id={call['call_id']}", "body": {"type": "response.create", "response": {"instructions": "Say the AI disclosure, then ask whether the call may be recorded."}}}
        if action.kind == "transfer":
            return {"op": "refer", "method": "POST", "path": f"{base}/refer", "body": {"target_uri": action.params["target"]}}
        if action.kind == "hangup":
            return {"op": "hangup", "method": "POST", "path": f"{base}/hangup", "body": None}
        return None


ADAPTERS: dict[str, Any] = {a.id: a for a in (RealtimeSipAdapter(), TeamsPhoneExtensibilityAdapter(), AcsCallAutomationAdapter())}


def adapter_for(raw: dict[str, Any], provider: str | None = None) -> Any:
    """Pick the adapter explicitly (provider id) or by payload shape."""
    if provider:
        if provider not in ADAPTERS:
            raise ValueError(f"unknown telephony provider {provider!r}; choose from {sorted(ADAPTERS)}")
        return ADAPTERS[provider]
    for a in ADAPTERS.values():
        if a.matches(raw):
            return a
    raise ValueError("unrecognised telephony event (expected Microsoft.Communication.*, Graph resourceData or realtime.* payloads)")


def acs_event(etype: str, call_id: str, **data: Any) -> dict[str, Any]:
    """Builds a minimal ACS-shaped event (used by the simulator and tests)."""
    return {"id": uuid.uuid4().hex, "type": f"Microsoft.Communication.{etype}", "source": "calling/callConnections/" + call_id, "data": {"callConnectionId": call_id, **data}}


def teams_event(kind: str, call_id: str, **data: Any) -> dict[str, Any]:
    """Minimal Graph-style call notification. kind: incoming | established | play_completed | tone | transfer_accepted | terminated."""
    res = f"/app/calls/{call_id}"

    def call(state: str, change: str) -> dict[str, Any]:
        return {"changeType": change, "resource": res, "resourceData": {"@odata.type": "#microsoft.graph.call", "id": call_id, "state": state, **data}}

    if kind == "incoming":
        return call("incoming", "created")
    if kind == "established":
        return call("established", "updated")
    if kind == "transfer_accepted":
        return call("transferAccepted", "updated")
    if kind == "terminated":
        return call("terminated", "deleted")
    if kind == "play_completed":
        return {"changeType": "updated", "resource": f"{res}/operations/{uuid.uuid4().hex[:8]}", "resourceData": {"@odata.type": "#microsoft.graph.playPromptOperation", "status": "completed"}}
    if kind == "tone":
        return {"changeType": "created", "resource": res, "resourceData": {"@odata.type": "#microsoft.graph.toneInfo", "tone": f"tone{data.get('digit', '1')}"}}
    if kind == "tone_timeout":
        return {"changeType": "deleted", "resource": res, "resourceData": {"@odata.type": "#microsoft.graph.toneInfo", "timedOut": True}}
    raise ValueError(f"unknown teams event kind {kind!r}")


def sip_event(kind: str, call_id: str, **data: Any) -> dict[str, Any]:
    """Minimal Realtime-SIP webhook / controller events. kind: incoming | connected | prompt_done | consent | refer_accepted | ended."""
    types = {"incoming": "realtime.call.incoming", "connected": "realtime.call.connected", "prompt_done": "response.done", "consent": "consent.captured", "refer_accepted": "realtime.call.refer.accepted", "ended": "realtime.call.ended"}
    if kind not in types:
        raise ValueError(f"unknown sip event kind {kind!r}")
    body: dict[str, Any] = {"call_id": call_id, **data}
    if kind == "incoming":
        frm, to = body.pop("from", "+4915550001234"), body.pop("to", "+49305550000")
        body["sip_headers"] = [{"name": "From", "value": f"<sip:{frm}@carrier.example>"}, {"name": "To", "value": f"<sip:{to}@carrier.example>"}, {"name": "Call-ID", "value": f"{uuid.uuid4().hex}@carrier.example"}]
    return {"id": f"evt_{uuid.uuid4().hex[:12]}", "type": types[kind], "created_at": int(time.time()), "data": body}


class SimulatedCallControl:
    """Records the native call-control commands the machine asked the provider for (no network)."""

    def __init__(self) -> None:
        self.executed: list[dict[str, Any]] = []

    def execute(self, commands: list[dict[str, Any]]) -> list[str]:
        self.executed.extend(commands)
        return [c["op"] for c in commands]


def acs_media_to_pcm(frame: dict[str, Any]) -> bytes | None:
    """ACS media streaming frame -> PCM16 bytes ('AudioData' frames only)."""
    if frame.get("kind") == "AudioData":
        data = frame.get("audioData", {})
        if data.get("silent"):
            return b"\x00\x00" * 480
        return base64.b64decode(data.get("data", ""))
    return None


def pcm_to_acs_media(pcm: bytes) -> dict[str, Any]:
    return {"kind": "AudioData", "audioData": {"data": base64.b64encode(pcm).decode(), "timestamp": None, "participantRawID": None, "silent": False}}


STOP_AUDIO = {"kind": "StopAudio", "stopAudio": {}}


def acs_metadata_frame(rate: int = 24000) -> dict[str, Any]:
    return {"kind": "AudioMetadata", "audioMetadata": {"subscriptionId": uuid.uuid4().hex, "encoding": "PCM", "sampleRate": rate, "channels": 1, "length": 960}}
