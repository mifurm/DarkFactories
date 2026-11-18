"""Realtime upstream connections: Azure OpenAI Realtime over WebSocket (Entra bearer token, GA protocol) and an in-process fake
(scripted for protocol tests, brain-driven for offline demos)."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import re
import struct
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Protocol

from ...core.azure_auth import get_token
from ...core.config import Settings

SAMPLE_RATE = 24000


class RealtimeUpstream(Protocol):
    name: str
    model: str

    async def connect(self) -> None: ...

    async def send(self, event: dict[str, Any]) -> None: ...

    def events(self) -> AsyncIterator[dict[str, Any]]: ...

    async def close(self) -> None: ...


class AzureRealtimeUpstream:
    name = "azure-openai-realtime"

    def __init__(self, settings: Settings, deployment: str, *, url: str | None = None, token: str | None = None) -> None:
        self.s = settings
        self.model = deployment
        self._url, self._token = url, token  # overrides let protocol tests talk to a local fake realtime server
        self._ws: Any = None

    async def connect(self) -> None:
        from websockets.asyncio.client import connect

        token = self._token or await get_token(self.s.client_id)
        host = self.s.openai_endpoint.replace("https://", "")
        self._ws = await connect(self._url or f"wss://{host}/openai/v1/realtime?model={self.model}", additional_headers={"Authorization": f"Bearer {token}"}, max_size=None, open_timeout=15, ping_interval=20)

    async def send(self, event: dict[str, Any]) -> None:
        await self._ws.send(json.dumps(event))

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        async for raw in self._ws:
            yield json.loads(raw)

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()


def tone_pcm(seconds: float, freq: float = 330.0) -> bytes:
    n = int(seconds * SAMPLE_RATE)
    return b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * (freq + 40 * math.sin(i / 900)) * i / SAMPLE_RATE))) for i in range(n))


Script = Callable[[dict[str, Any], "FakeRealtimeUpstream"], Awaitable[None]]


class FakeRealtimeUpstream:
    """In-process stand-in for the Realtime API. `script(event, fake)` is invoked for every client event and may `await fake.emit(...)`."""

    name = "fake-realtime"
    model = "fake-realtime"

    def __init__(self, script: Script | None = None) -> None:
        self.script = script
        self.sent: list[dict[str, Any]] = []
        self._q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self.connected = False
        self.fail_connect = False
        self.response_open = False

    async def connect(self) -> None:
        if self.fail_connect:
            raise ConnectionError("fake realtime upstream refused the connection")
        self.connected = True
        await self.emit({"type": "session.created", "session": {"id": "sess_fake"}})

    async def emit(self, event: dict[str, Any]) -> None:
        await self._q.put(event)

    async def send(self, event: dict[str, Any]) -> None:
        self.sent.append(event)
        if event.get("type") == "session.update":
            await self.emit({"type": "session.updated", "session": event.get("session", {})})
        if self.script:
            await self.script(event, self)

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            ev = await self._q.get()
            if ev is None:
                return
            yield ev

    async def close(self) -> None:
        self.connected = False
        await self._q.put(None)

    # helpers for scripts
    async def speak(self, text: str, *, seconds: float = 0.4, response_id: str = "resp_1", tool_calls: list[dict[str, Any]] | None = None) -> None:
        self.response_open = True
        await self.emit({"type": "response.created", "response": {"id": response_id}})
        for word in text.split():
            await self.emit({"type": "response.output_audio_transcript.delta", "response_id": response_id, "delta": word + " "})
        for _ in range(3):
            await self.emit({"type": "response.output_audio.delta", "response_id": response_id, "delta": base64.b64encode(tone_pcm(seconds / 3)).decode()})
            await asyncio.sleep(0)
        await self.emit({"type": "response.output_audio_transcript.done", "response_id": response_id, "transcript": text})
        for tc in tool_calls or []:
            await self.emit({"type": "response.function_call_arguments.done", "response_id": response_id, "call_id": tc["call_id"], "name": tc["name"], "arguments": json.dumps(tc["arguments"])})
        await self.emit({"type": "response.done", "response": {"id": response_id, "status": "completed", "usage": {"input_tokens": 120, "output_tokens": 60, "input_token_details": {"text_tokens": 100, "audio_tokens": 20, "cached_tokens": 0}, "output_token_details": {"text_tokens": 30, "audio_tokens": 30}}}})
        self.response_open = False


async def brain_script(event: dict[str, Any], fake: FakeRealtimeUpstream) -> None:
    """Offline demo model: answers text turns with the deterministic stub brain and emits spoken audio + transcript."""
    from ...engine.stub_brain import brain

    kind = event.get("type")
    state = fake.__dict__.setdefault("state", {"history": [], "n": 0, "tools": []})
    if kind == "session.update":
        state["tools"] = [t["name"] for t in event.get("session", {}).get("tools", [])]
        state["instructions"] = event.get("session", {}).get("instructions", "")
    elif kind == "conversation.item.create":
        item = event["item"]
        if item.get("type") == "message":
            text = "".join(c.get("text", "") for c in item.get("content", []))
            state["history"].append({"role": "user", "content": text})
        elif item.get("type") == "function_call_output":
            state["history"].append({"role": "tool", "tool_call_id": item["call_id"], "content": item["output"]})
    elif kind == "response.create":
        extra = (event.get("response") or {}).get("instructions")
        if extra and not state["history"]:
            lang = state.get("lang", "en")
            quoted = re.search(r'"([^"]{20,600})"', extra)
            if lang != "en" and quoted:  # greet in the caller's language: the disclosure the relay asked for, then the opening question (unless the relay already quoted it)
                from ...engine.guard import GREETING

                opening = GREETING.get(lang, GREETING["en"])
                spoken = quoted.group(1)
                await fake.speak(spoken if spoken.endswith(opening) else f"{spoken} {opening}")
                return
            await fake.speak(extra[:240] if len(extra) < 260 else "Hello, how can I help you today?")
            return
        tools = [{"function": {"name": n}} for n in state["tools"]]
        msgs = [{"role": "system", "content": state.get("instructions", "")}, *state["history"]]
        res = brain(msgs, tools, {"agent": "resolution", "state": state.get("hints", {"lang": "en", "intent": "other"})})
        state["n"] += 1
        if res.tool_calls:
            tc = res.tool_calls[0]
            state["history"].append({"role": "assistant", "content": None, "tool_calls": [{"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}]})
            await fake.speak("", seconds=0.0, response_id=f"resp_{state['n']}", tool_calls=[{"call_id": tc.id, "name": tc.name, "arguments": tc.arguments}])
        else:
            state["history"].append({"role": "assistant", "content": res.text})
            await fake.speak(res.text, response_id=f"resp_{state['n']}")


def offline_script(svc: Any, conv_id: str) -> Script:
    """Brain-driven fake that sees the same conversation state hints as the chat orchestrator (understanding, identity, steps)."""

    async def script(event: dict[str, Any], fake: FakeRealtimeUpstream) -> None:
        if event.get("type") == "response.create":
            from ...engine.understanding import analyze

            conv = await svc.store.get(conv_id)
            last = next((m for m in reversed(conv.messages) if m.role == "customer"), None) if conv else None
            if conv is not None:
                fake.__dict__.setdefault("state", {"history": [], "n": 0, "tools": []})["lang"] = conv.language
            if conv is not None and last is not None:
                u = analyze(last.text, lang_hint=conv.language, prior=conv.understanding)
                verdict = svc.guard.inspect_input_fast(last.text, conv.language)
                fake.__dict__.setdefault("state", {"history": [], "n": 0, "tools": []})["hints"] = svc.orchestrator._hints(conv, "resolution", u, verdict, {})["state"]
        await brain_script(event, fake)

    return script
