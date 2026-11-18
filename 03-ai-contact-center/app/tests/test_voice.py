"""Voice relay protocol (brief §5) against a fake realtime *server*: session.update, audio append / server-VAD commit, response audio deltas, a tool-call
round trip, barge-in cancel + truncate, the fallback pipeline and turn-latency metrics. The relay talks to it through the production upstream class."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json

import pytest
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from concierge.features.voice.session import VoiceSession
from concierge.features.voice.upstream import AzureRealtimeUpstream, FakeRealtimeUpstream

PCM = b"\x10\x00" * 480  # 20 ms of 24 kHz mono PCM16


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


class FakeRealtimeServer:
    """Speaks just enough of the Realtime GA protocol: acks session.update, turns 10 appended frames into a transcribed utterance that triggers a
    tool call, streams audio deltas for responses and honours response.cancel."""

    def __init__(self, *, slow_answer: bool = False, greetings: list[str] | None = None) -> None:
        self.received: list[dict] = []
        self.auth: str | None = None
        self.path = ""
        self.appended = 0
        self.slow_answer = slow_answer
        self.cancelled = asyncio.Event()
        self.streaming: asyncio.Task | None = None
        self.deltas_sent = 0
        self.stage = "greeting"
        self.greetings = list(greetings or ["Hello this is Concierge the AI assistant of Contoso Home how can I help"])  # one text per opening response.create

    async def _stream(self, ws, text: str, frames: int = 3) -> None:
        with contextlib.suppress(ConnectionClosed):
            await self._stream_frames(ws, text, frames)

    async def _stream_frames(self, ws, text: str, frames: int) -> None:
        self.cancelled.clear()
        await ws.send(json.dumps({"type": "response.created", "response": {"id": "resp_x"}}))
        await ws.send(json.dumps({"type": "response.output_item.added", "item": {"id": "item_1", "type": "message"}}))
        for i in range(frames):
            if self.cancelled.is_set():
                return
            await ws.send(json.dumps({"type": "response.output_audio.delta", "delta": b64(PCM * 5)}))
            await ws.send(json.dumps({"type": "response.output_audio_transcript.delta", "delta": text.split()[min(i, len(text.split()) - 1)] + " "}))
            self.deltas_sent += 1
            if self.slow_answer:
                await asyncio.sleep(0.03)
        if self.cancelled.is_set():
            return
        await ws.send(json.dumps({"type": "response.output_audio_transcript.done", "transcript": text}))
        await ws.send(json.dumps({"type": "response.done", "response": {"usage": {"input_token_details": {"text_tokens": 120, "audio_tokens": 40}, "output_token_details": {"text_tokens": 20, "audio_tokens": 90}}}}))

    async def handler(self, ws) -> None:
        self.auth, self.path = ws.request.headers.get("Authorization"), ws.request.path
        await ws.send(json.dumps({"type": "session.created", "session": {"id": "sess_1"}}))
        async for raw in ws:
            ev = json.loads(raw)
            self.received.append(ev)
            t = ev["type"]
            if t == "session.update":
                await ws.send(json.dumps({"type": "session.updated", "session": ev["session"]}))
            elif t == "response.create":
                if self.stage == "greeting":
                    text = self.greetings.pop(0)
                    if not self.greetings:
                        self.stage = "listening"
                    await self._stream(ws, text)
                elif self.stage == "after_tool":
                    self.stage = "done"
                    self.streaming = asyncio.create_task(self._stream(ws, "You can return most items within 30 days of delivery free of charge [K1]", frames=12 if self.slow_answer else 3))
            elif t == "input_audio_buffer.append":
                self.appended += 1
                if self.appended == 10:
                    for e in (
                        {"type": "input_audio_buffer.speech_started"},
                        {"type": "input_audio_buffer.speech_stopped"},
                        {"type": "input_audio_buffer.committed", "item_id": "item_u1"},
                        {"type": "conversation.item.input_audio_transcription.completed", "transcript": "What is your return policy?"},
                        {"type": "response.created", "response": {"id": "resp_t"}},
                        {"type": "response.function_call_arguments.done", "name": "search_knowledge", "call_id": "call_1", "arguments": json.dumps({"query": "return policy window"})},
                    ):
                        await ws.send(json.dumps(e))
                    self.stage = "after_tool"
                    await ws.send(json.dumps({"type": "response.done", "response": {"usage": {}}}))
            elif t == "response.cancel":
                self.cancelled.set()
            elif t == "test.barge_in":  # test hook: the fake's server VAD hears the customer talking over the agent
                await ws.send(json.dumps({"type": "input_audio_buffer.speech_started"}))

    @contextlib.asynccontextmanager
    async def run(self):
        async with serve(self.handler, "127.0.0.1", 0) as server:
            self.url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/openai/v1/realtime?model=gpt-realtime-2.1-mini"
            yield self


class Sink:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.audio = bytearray()

    async def json(self, ev: dict) -> None:
        self.events.append(ev)

    async def bytes(self, b: bytes) -> None:
        self.audio += b

    def of(self, kind: str) -> list[dict]:
        return [e for e in self.events if e.get("type") == kind]

    async def until(self, pred, timeout: float = 6.0) -> None:
        for _ in range(int(timeout / 0.01)):
            if pred():
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"condition not reached; events={[e['type'] for e in self.events]}")


async def open_session(svc, fake: FakeRealtimeServer) -> tuple[VoiceSession, Sink, str]:
    conv = await svc.orchestrator.start(channel="voice", language="en", recording_consent="granted")
    sink = Sink()
    session = VoiceSession(svc, conv.id, sink.json, sink.bytes, upstream_factory=lambda dep: AzureRealtimeUpstream(svc.settings, dep, url=fake.url, token="entra-test-token"))
    await session.start()
    return session, sink, conv.id


async def test_session_update_audio_commit_tool_round_trip_and_transcripts(svc):
    async with FakeRealtimeServer().run() as fake:
        session, sink, conv_id = await open_session(svc, fake)
        try:
            await sink.until(lambda: sink.of("latency"))
            assert fake.auth == "Bearer entra-test-token", "the relay authenticates upstream with a bearer token, never a key"
            update = next(e for e in fake.received if e["type"] == "session.update")["session"]
            assert update["type"] == "realtime" and update["output_modalities"] == ["audio"]
            vad = update["audio"]["input"]["turn_detection"]
            assert vad["type"] == "server_vad" and update["audio"]["input"]["format"]["rate"] == 24000
            assert update["audio"]["input"]["transcription"] and update["audio"]["output"]["voice"]
            names = {t["name"] for t in update["tools"]}
            assert {"search_knowledge", "escalate_to_human"} <= names
            assert all(t["type"] == "function" and "parameters" in t for t in update["tools"]), "flat GA tool schema"
            assert [e["type"] for e in fake.received][:2] == ["session.update", "response.create"], "disclosure is the first thing the agent says"
            assert len(sink.audio) >= 4800 and sink.of("state")

            for _ in range(10):
                await session.feed_audio(PCM)
            await sink.until(lambda: any(e.get("role") == "agent" and e.get("final") and "30 days" in e["text"] for e in sink.events))

            appended = [e for e in fake.received if e["type"] == "input_audio_buffer.append"]
            assert len(appended) == 10 and base64.b64decode(appended[0]["audio"]) == PCM
            out = next(e for e in fake.received if e["type"] == "conversation.item.create" and e["item"]["type"] == "function_call_output")
            assert out["item"]["call_id"] == "call_1" and "30 days" in out["item"]["output"], "tool result is returned to the model"
            assert fake.received[-1]["type"] == "response.create", "the relay asks for the final answer after the tool output"
            assert any(e.get("name") == "search_knowledge" and e["status"] in ("running", "ok") for e in sink.of("tool"))
            cust = [e for e in sink.of("transcript") if e["role"] == "customer"]
            assert cust and cust[-1]["text"] == "What is your return policy?"

            conv = await svc.store.get(conv_id)
            texts = [(m.role, m.text) for m in conv.messages]
            assert ("customer", "What is your return policy?") in texts and any(r == "agent_ai" and "30 days" in t for r, t in texts)
            assert any(t.name == "search_knowledge" for m in conv.messages for t in m.tools)
            lat = [e["first_audio_ms"] for e in sink.of("latency")]
            assert len(lat) >= 2 and all(0 < x < 3000 for x in lat) and svc.meter.latency["voice_turn"]
        finally:
            await session.close()


async def test_barge_in_by_server_vad_clears_playback_and_is_counted(svc):
    async with FakeRealtimeServer(slow_answer=True).run() as fake:
        session, sink, _ = await open_session(svc, fake)
        try:
            await sink.until(lambda: sink.of("latency"))
            for _ in range(10):
                await session.feed_audio(PCM)
            await sink.until(lambda: fake.stage == "done" and fake.deltas_sent > 3)
            clears_before = len(sink.of("audio.clear"))
            await session.up.send({"type": "test.barge_in"})
            await sink.until(lambda: len(sink.of("audio.clear")) > clears_before)
            assert session.barge_ins == 1 and session.speaking is False
            assert sink.of("state")[-1]["state"] == "listening"
        finally:
            await session.close()


async def test_client_interrupt_cancels_the_response_and_truncates_what_was_not_played(svc):
    async with FakeRealtimeServer(slow_answer=True).run() as fake:
        session, sink, _ = await open_session(svc, fake)
        try:
            await sink.until(lambda: sink.of("latency"))
            for _ in range(10):
                await session.feed_audio(PCM)
            await sink.until(lambda: fake.stage == "done" and fake.deltas_sent > 4)
            await session.interrupt()
            await sink.until(lambda: any(e["type"] == "response.cancel" for e in fake.received))
            await sink.until(lambda: any(e["type"] == "conversation.item.truncate" for e in fake.received))
            trunc = next(e for e in fake.received if e["type"] == "conversation.item.truncate")
            assert trunc["item_id"] == "item_1" and trunc["content_index"] == 0 and trunc["audio_end_ms"] >= 0
            assert sink.of("audio.clear"), "the browser is told to flush its playback buffer"
            await asyncio.sleep(0.15)
            sent = fake.deltas_sent
            await asyncio.sleep(0.15)
            assert fake.deltas_sent == sent, "the fake server stopped streaming after the cancel"
        finally:
            await session.close()


async def test_text_input_path_used_by_the_smoke_test_proves_audio_and_transcript_output(svc):
    async with FakeRealtimeServer().run() as fake:
        session, sink, _conv_id = await open_session(svc, fake)
        try:
            await sink.until(lambda: sink.of("latency"))
            fake.stage = "after_tool"
            await session.feed_text("What is your return policy?")
            await sink.until(lambda: any(e["type"] == "conversation.item.create" and e["item"].get("role") == "user" for e in fake.received))
            create = [e for e in fake.received if e["type"] == "conversation.item.create" and e["item"].get("role") == "user"]
            assert create[-1]["item"]["content"][0]["type"] == "input_text"
            await sink.until(lambda: any(e.get("role") == "agent" and e.get("final") and "30 days" in e["text"] for e in sink.events))
            assert len(sink.audio) > 0
        finally:
            await session.close()


async def test_realtime_failure_falls_back_to_the_stt_llm_tts_pipeline(svc):
    conv = await svc.orchestrator.start(channel="voice", language="en", recording_consent="granted")
    sink = Sink()

    def broken(dep: str):
        f = FakeRealtimeUpstream()
        f.fail_connect = True
        return f

    session = VoiceSession(svc, conv.id, sink.json, sink.bytes, upstream_factory=broken)
    await session.start()
    try:
        assert session.mode == "pipeline" and sink.of("fallback") and sink.of("session")[0]["mode"] == "pipeline"
        assert len(sink.audio) > 0, "the pipeline speaks the disclosure with TTS"
        await session.feed_text("What is your return policy?")
        await sink.until(lambda: any(e.get("role") == "agent" and e.get("final") and "30 days" in e["text"] for e in sink.events), timeout=15)
    finally:
        await session.close()


async def test_unknown_conversation_is_rejected(svc):
    sink = Sink()
    session = VoiceSession(svc, "cv_does_not_exist", sink.json, sink.bytes, upstream_factory=None)
    with pytest.raises(KeyError):
        await session.start()
    assert sink.of("error")[0]["error"] == "session_not_found"
