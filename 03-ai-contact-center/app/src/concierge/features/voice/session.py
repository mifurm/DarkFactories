"""Voice session relay (CC-02): browser audio <-> Azure OpenAI Realtime (server VAD, barge-in, tool calling, live transcripts,
latency metrics) with an STT -> LLM -> TTS fallback. The same ToolExecutor / policy / guard / audit as chat."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import struct
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ...core.ai.azure_cognitive import wav_from_pcm16
from ...core.ai.base import Usage
from ...engine import handoff as handoff_mod
from ...engine.guard import AI_DISCLOSURE
from ...engine.models import Conversation, ToolRecord, now
from ...engine.prompts import build_system_prompt
from ...engine.routing import Trigger
from ...engine.tools import ToolContext
from .upstream import SAMPLE_RATE, RealtimeUpstream

log = logging.getLogger("concierge.voice")
SendJson = Callable[[dict[str, Any]], Awaitable[None]]
SendAudio = Callable[[bytes], Awaitable[None]]
MAX_SESSION_S = 600


def pcm_rms(pcm: bytes) -> float:
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", pcm[: n * 2])
    return (sum(s * s for s in samples) / n) ** 0.5


class VoiceSession:
    def __init__(self, svc: Any, conv_id: str, send_json: SendJson, send_audio: SendAudio, *, upstream_factory: Callable[[str], RealtimeUpstream] | None, mode: str = "auto") -> None:
        self.svc = svc
        self.conv_id = conv_id
        self.send_json = send_json
        self.send_audio = send_audio
        self.upstream_factory = upstream_factory
        self.requested_mode = mode
        self.mode = "realtime"
        self.up: RealtimeUpstream | None = None
        self.conv: Conversation | None = None
        self.cfg: Any = None
        self.tasks: list[asyncio.Task] = []
        self.closed = asyncio.Event()
        self.records: list[ToolRecord] = []
        self.tool_outputs_pending = False
        self.speaking = False
        self.agent_buf = ""
        self.t_ref: float | None = None
        self.first_audio_done = True
        self.sent_audio_bytes = 0
        self.current_item: str | None = None
        self.payment_token: str | None = None
        self.muted = False
        self.turn_tools: list[dict[str, Any]] = []
        self.close_after_response = False
        self.model_used = ""
        self.started = time.time()
        self.barge_ins = 0
        self.transcript_event = asyncio.Event()
        self.awaiting_transcript = False
        self._utt = bytearray()
        self._silence_ms = 0.0
        self._speech_ms = 0.0
        self._pipeline_busy = False

    # ------------------------------------------------------------------ setup
    def _voice_cfg(self) -> Any:
        cfg = self.cfg
        union = sorted(set(cfg.tools.get("authentication", [])) | set(cfg.tools.get("resolution", [])))
        return cfg.model_copy(update={"tools": {**cfg.tools, "voice": union}})

    def _session_config(self) -> dict[str, Any]:
        assert self.conv is not None
        auth = self.cfg.prompts.get("authentication", "")
        sys = build_system_prompt(self.cfg, self.conv, "resolution", voice=True) + "\n\nAUTHENTICATION (also yours on this call):\n" + auth
        tools = self.svc.tools.schemas(self._voice_cfg().tools["voice"], realtime=True)
        transcription: dict[str, Any] = {"model": "gpt-4o-mini-transcribe"}
        if self.conv.language and len(self.conv.language) == 2:
            transcription["language"] = self.conv.language
        return {
            "type": "realtime", "instructions": sys, "output_modalities": ["audio"],
            "audio": {
                "input": {"format": {"type": "audio/pcm", "rate": SAMPLE_RATE}, "transcription": transcription, "turn_detection": {"type": "server_vad", "threshold": 0.5, "prefix_padding_ms": 300, "silence_duration_ms": 500, "create_response": True, "interrupt_response": True}},
                "output": {"format": {"type": "audio/pcm", "rate": SAMPLE_RATE}, "voice": "marin"},
            },
            "tools": tools, "tool_choice": "auto",
        }  # fmt: skip

    async def start(self) -> None:
        self.conv = await self.svc.store.get(self.conv_id)
        if self.conv is None:
            await self.send_json({"type": "error", "error": "session_not_found"})
            raise KeyError(self.conv_id)
        self.cfg = await self.svc.configs.get(self.conv.config_version) or await self.svc.configs.active()
        self.svc.meter.check_budget()
        if self.requested_mode != "pipeline" and self.upstream_factory is not None:
            try:
                dep = self.svc.settings.deployment("realtime")
                self.up = self.upstream_factory(dep)
                await asyncio.wait_for(self.up.connect(), timeout=20)
                self.model_used = self.up.model
            except Exception as exc:
                log.warning("realtime connect failed (%s) - trying fallback model", type(exc).__name__)
                fb = self.svc.settings.deployment("realtime_fallback")
                self.up = None
                if fb and self.requested_mode != "pipeline":
                    try:
                        self.up = self.upstream_factory(fb)
                        await asyncio.wait_for(self.up.connect(), timeout=20)
                        self.model_used = self.up.model
                    except Exception:
                        self.up = None
        if self.up is None:
            self.mode = "pipeline"
            await self.send_json({"type": "fallback", "reason": "realtime unavailable - using STT -> LLM -> TTS pipeline"})
        else:
            self.tasks.append(asyncio.create_task(self._upstream_reader()))
            await self.up.send({"type": "session.update", "session": self._session_config()})
        await self.send_json({"type": "session", "mode": self.mode, "model": self.model_used or "pipeline", "language": self.conv.language, "conversation_id": self.conv_id})
        self.tasks.append(asyncio.create_task(self._watchdog()))
        disclosure = AI_DISCLOSURE.get(self.conv.language, AI_DISCLOSURE["en"])
        if self.mode == "realtime":
            self._mark_turn()
            await self.up.send({"type": "response.create", "response": {"instructions": f"Begin the call. First say exactly this disclosure in the caller's language: \"{disclosure}\" Then greet warmly and ask how you can help. Keep it to 3 short sentences."}})  # type: ignore[union-attr]
            await self.send_json({"type": "state", "state": "thinking"})
        else:
            await self._pipeline_speak(disclosure + " " + {"de": "Wie kann ich helfen?", "en": "How can I help you today?"}.get(self.conv.language, "How can I help you today?"))

    async def _watchdog(self) -> None:
        while not self.closed.is_set():
            await asyncio.sleep(5)
            if time.time() - self.started > MAX_SESSION_S:
                await self.send_json({"type": "error", "error": "max_duration"})
                await self.close()
                return

    # ------------------------------------------------------------------ browser -> server
    def _mark_turn(self) -> None:
        self.t_ref = time.perf_counter()
        self.first_audio_done = False

    async def feed_audio(self, pcm: bytes) -> None:
        if self.muted or self.payment_token:
            return
        if self.mode == "realtime" and self.up is not None:
            await self.up.send({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm).decode()})
            return
        await self._pipeline_audio(pcm)

    async def feed_text(self, text: str) -> None:
        """Text input path (smoke test / accessibility): the model still answers with audio + transcript."""
        text = text.strip()[:1000]
        if not text:
            return
        self.svc.meter.check_budget()
        await self.send_json({"type": "transcript", "role": "customer", "text": self.svc.guard.inspect_input_fast(text).redaction.text, "final": True, "source": "text"})
        if self.mode == "realtime" and self.up is not None:
            out = await self.svc.orchestrator.record_customer_utterance(self.conv_id, text, source="voice-text")
            await self.up.send({"type": "conversation.item.create", "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": out["message"].text}]}})
            self._mark_turn()
            extra = await self._handoff_instruction(out)
            await self.up.send({"type": "response.create", **({"response": {"instructions": extra}} if extra else {})})
            await self.send_json({"type": "state", "state": "thinking"})
        else:
            self._mark_turn()
            await self._pipeline_text_turn(text)

    async def interrupt(self) -> None:
        """Barge-in initiated by the client: cancel the response and truncate what was not yet played."""
        self.barge_ins += 1
        await self.send_json({"type": "audio.clear"})
        if self.up is not None and self.speaking:
            await self.up.send({"type": "response.cancel"})
            if self.current_item:
                await self.up.send({"type": "conversation.item.truncate", "item_id": self.current_item, "content_index": 0, "audio_end_ms": int(self.sent_audio_bytes / 2 / SAMPLE_RATE * 1000 * 0.5)})
        self.speaking = False

    async def dtmf(self, digit: str) -> None:
        if not self.payment_token:
            return
        from ...core.redaction import luhn_ok
        from ..identity import _complete

        buf: dict[str, str] = self.svc.ext.setdefault("dtmf", {})
        if digit == "#":
            pan = buf.pop(self.payment_token, "")
            if not luhn_ok(pan):
                await self.send_json({"type": "payment", "status": "invalid"})
                return
            res = await _complete(self.svc, self.payment_token, pan)
            self.payment_token = None
            await self.send_json({"type": "payment", "status": "paid", "brand": res.get("brand"), "last4": res.get("last4")})
            await self._inject_system(f"The caller completed the secure keypad payment ({res.get('brand')} ending {res.get('last4')}). Confirm it briefly; never repeat card digits.")
        elif digit == "*":
            buf.pop(self.payment_token, None)
            await self.send_json({"type": "payment", "status": "cleared", "digits": 0})
        elif digit.isdigit():
            buf[self.payment_token] = (buf.get(self.payment_token, "") + digit)[:19]
            await self.send_json({"type": "payment", "status": "capturing", "digits": len(buf[self.payment_token])})

    async def _inject_system(self, text: str) -> None:
        if self.mode == "realtime" and self.up is not None:
            await self.up.send({"type": "conversation.item.create", "item": {"type": "message", "role": "system", "content": [{"type": "input_text", "text": text}]}})
            self._mark_turn()
            await self.up.send({"type": "response.create"})

    async def _handoff_instruction(self, out: dict[str, Any]) -> str | None:
        h = out.get("handoff")
        if not h:
            return None
        await self.send_json({"type": "handoff", "handoff": {"id": h["id"], "queue": h["routing"]["queue"], "trigger": h["trigger"], "est_wait_min": h["est_wait_min"]}})
        return "The customer needs a human colleague (reason: " + h["trigger"]["code"] + "). Tell them warmly that you are bringing in a colleague who can already see everything discussed, so they need not repeat anything. Stay on the line."

    # ------------------------------------------------------------------ upstream -> browser
    async def _upstream_reader(self) -> None:
        assert self.up is not None
        try:
            async for ev in self.up.events():
                try:
                    await self._on_event(ev)
                except Exception:
                    log.exception("voice event handling failed")
        except Exception as exc:
            log.warning("upstream closed: %s", type(exc).__name__)
            if not self.closed.is_set():
                self.mode = "pipeline"
                self.up = None
                await self.send_json({"type": "fallback", "reason": "realtime session ended unexpectedly - continuing with STT -> LLM -> TTS"})

    async def _on_event(self, ev: dict[str, Any]) -> None:
        t = ev.get("type", "")
        if t == "input_audio_buffer.speech_started":
            if self.speaking:
                self.barge_ins += 1
            self.speaking = False
            self.awaiting_transcript = True
            self.transcript_event.clear()
            await self.send_json({"type": "audio.clear"})
            await self.send_json({"type": "state", "state": "listening"})
        elif t == "input_audio_buffer.speech_stopped":
            self._mark_turn()
        elif t == "conversation.item.input_audio_transcription.completed":
            text = ev.get("transcript", "").strip()
            if text:
                await self.send_json({"type": "transcript", "role": "customer", "text": self.svc.guard.inspect_input_fast(text).redaction.text, "final": True, "source": "speech"})
                out = await self.svc.orchestrator.record_customer_utterance(self.conv_id, text)
                extra = await self._handoff_instruction(out)
                if extra:
                    await self._inject_system(extra)
            self.awaiting_transcript = False
            self.transcript_event.set()
        elif t == "response.created":
            self.speaking = True
            self.agent_buf = ""
            self.current_item = None
            self.sent_audio_bytes = 0
        elif t in ("response.output_item.added",):
            item = ev.get("item", {})
            if item.get("type") == "message":
                self.current_item = item.get("id")
        elif t in ("response.output_audio.delta", "response.audio.delta"):
            pcm = base64.b64decode(ev.get("delta", ""))
            if not self.first_audio_done and self.t_ref is not None:
                self.first_audio_done = True
                ms = round((time.perf_counter() - self.t_ref) * 1000, 1)
                assert self.conv is not None
                self.conv.metrics.setdefault("voice_latency_ms", []).append(ms)
                self.svc.meter.latency["voice_turn"].append(ms)
                tid = f"{self.conv_id}:v{len(self.conv.metrics['voice_latency_ms'])}"
                root = self.svc.traces.record(tid, "voice.turn", time.time() - ms / 1000, ms, conv=self.conv_id, model=self.model_used, mode=self.mode)
                self.svc.traces.record(tid, "voice.relay.upstream_first_audio", time.time() - ms / 1000, ms, parent=root, hop="browser ws -> relay -> azure openai realtime -> first audio delta")
                for rec in self.turn_tools:
                    self.svc.traces.record(tid, f"voice.tool.{rec['name']}", rec["ts"], rec["ms"], parent=root, status=rec["status"])
                self.turn_tools.clear()
                await self.send_json({"type": "latency", "first_audio_ms": ms})
            self.sent_audio_bytes += len(pcm)
            await self.send_json({"type": "state", "state": "speaking"})
            await self.send_audio(pcm)
        elif t in ("response.output_audio_transcript.delta", "response.audio_transcript.delta"):
            self.agent_buf += ev.get("delta", "")
            await self.send_json({"type": "transcript", "role": "agent", "text": self.agent_buf, "final": False})
        elif t in ("response.output_audio_transcript.done", "response.audio_transcript.done"):
            text = (ev.get("transcript") or self.agent_buf).strip()
            if text:
                msg = await self.svc.orchestrator.record_agent_utterance(self.conv_id, text, tools=list(self.records), meta={"mode": "realtime", "model": self.model_used})
                self.records.clear()
                await self.send_json({"type": "transcript", "role": "agent", "text": msg.text, "final": True, "flags": msg.flags})
            self.agent_buf = ""
        elif t == "response.function_call_arguments.done":
            await self._tool_call(ev)
        elif t == "response.done":
            self.speaking = False
            resp = ev.get("response", {})
            self._meter(resp.get("usage") or {})
            if self.tool_outputs_pending and self.up is not None:
                self.tool_outputs_pending = False
                self._mark_turn()
                await self.up.send({"type": "response.create"})
            else:
                await self.send_json({"type": "state", "state": "listening"})
                if self.close_after_response:
                    await self.end()
        elif t == "error":
            err = ev.get("error", {})
            if err.get("code") in ("response_cancel_not_active", "conversation_already_has_active_response"):
                return
            await self.send_json({"type": "error", "error": err.get("code") or err.get("type") or "upstream_error", "message": str(err.get("message", ""))[:200]})

    def _meter(self, usage: dict[str, Any]) -> None:
        if not usage:
            return
        ind, outd = usage.get("input_token_details") or {}, usage.get("output_token_details") or {}
        u = Usage(input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0), cached_tokens=ind.get("cached_tokens", 0), audio_in_tokens=ind.get("audio_tokens", 0), audio_out_tokens=outd.get("audio_tokens", 0))
        self.svc.meter.record(model=self.model_used or "gpt-realtime-2.1-mini", feature="voice", usage=u, conv_id=self.conv_id, simulated=self.up is None or self.up.name == "fake-realtime", audio_seconds=(u.audio_in_tokens / 10 + u.audio_out_tokens / 20))

    async def _wait_transcript(self) -> None:
        if self.awaiting_transcript:
            try:
                await asyncio.wait_for(self.transcript_event.wait(), timeout=2.5)
            except TimeoutError:
                pass

    async def _tool_call(self, ev: dict[str, Any]) -> None:
        assert self.conv is not None and self.up is not None
        name, call_id = ev.get("name", ""), ev.get("call_id", "")
        try:
            args = json.loads(ev.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        await self.send_json({"type": "tool", "name": name, "status": "running"})
        self.conv = await self.svc.store.get(self.conv_id) or self.conv
        ctx = ToolContext(svc=self.svc, conv=self.conv, agent="voice", actor="ai", cfg=self._voice_cfg(), wait_for_input=self._wait_transcript)
        t_tool = time.perf_counter()
        out = await self.svc.tools.execute(ctx, name, args)
        self.turn_tools.append({"name": name, "ts": time.time() - (time.perf_counter() - t_tool), "ms": (time.perf_counter() - t_tool) * 1000, "status": out.status})
        self.records.append(out.record)
        await self.up.send({"type": "conversation.item.create", "item": {"type": "function_call_output", "call_id": call_id, "output": out.for_model()}})
        self.tool_outputs_pending = True
        await self.send_json({"type": "tool", "name": name, "status": out.status, "summary": out.record.error or str(out.data.get("status") or out.data.get("plan") or "")[:120]})
        if out.status == "confirmation_required":
            await self.send_json({"type": "pending", "pending": [p.model_dump() for p in self.conv.pending]})
        if out.switch_agent:
            self.conv.agent_trace.append({"ts": now(), "agent": out.switch_agent, "event": "switched", "after": name})
            await self.send_json({"type": "agent", "agent": out.switch_agent})
        if name == "request_payment" and out.status == "ok":
            self.payment_token = out.data["secure_link"].rsplit("/", 1)[-1]
            await self.send_json({"type": "payment", "status": "keypad", "link": out.data["secure_link"], "note": "Microphone muted - enter the card digits on the keypad, then #."})
        if out.escalate and self.conv.handler == "ai":
            esc = out.escalate
            h = await handoff_mod.initiate(self.svc, self.conv, Trigger(esc.get("code", "agent_decision"), esc.get("reason", "")), notify=False)
            await self.send_json({"type": "handoff", "handoff": {"id": h["id"], "queue": h["routing"]["queue"], "trigger": h["trigger"], "est_wait_min": h["est_wait_min"]}})
        if out.end:
            self.close_after_response = True
        await self.svc.store.save(self.conv)

    # ------------------------------------------------------------------ STT -> LLM -> TTS fallback
    async def _pipeline_audio(self, pcm: bytes) -> None:
        frame_ms = len(pcm) / 2 / SAMPLE_RATE * 1000
        loud = pcm_rms(pcm) > 450
        if loud:
            self._speech_ms += frame_ms
            self._silence_ms = 0.0
            self._utt += pcm
        elif self._speech_ms > 0:
            self._silence_ms += frame_ms
            self._utt += pcm
            if self._silence_ms >= 700 and self._speech_ms >= 300 and not self._pipeline_busy:
                data, self._utt = bytes(self._utt), bytearray()
                self._speech_ms = self._silence_ms = 0.0
                self._pipeline_busy = True
                self.tasks.append(asyncio.create_task(self._pipeline_utterance(data)))

    async def _pipeline_utterance(self, pcm: bytes) -> None:
        try:
            await self.send_json({"type": "state", "state": "thinking"})
            self._mark_turn()
            stt = await self.svc.speech.transcribe(wav_from_pcm16(pcm, SAMPLE_RATE), mime="audio/wav", language=self.conv.language if self.conv else None)
            if stt.text:
                await self.send_json({"type": "transcript", "role": "customer", "text": self.svc.guard.inspect_input_fast(stt.text).redaction.text, "final": True, "source": "stt"})
                await self._pipeline_text_turn(stt.text)
        except Exception as exc:
            await self.send_json({"type": "error", "error": type(exc).__name__})
        finally:
            self._pipeline_busy = False
            await self.send_json({"type": "state", "state": "listening"})

    async def _pipeline_text_turn(self, text: str) -> None:
        assert self.conv is not None
        res = await self.svc.orchestrator.handle_message(self.conv_id, text, source="voice-pipeline")
        msg = res.get("message")
        if msg:
            await self.send_json({"type": "transcript", "role": "agent", "text": msg["text"], "final": True})
            await self._pipeline_speak(msg["text"])
        if res.get("status") in ("resolved", "closed"):
            await self.send_json({"type": "ended", "reason": res["status"]})

    async def _pipeline_speak(self, text: str) -> None:
        clean = text.replace("[K1]", "").replace("[K2]", "").replace("[K3]", "")
        audio, _mime = await self.svc.speech.synthesize(clean, language=self.conv.language if self.conv else "en")
        pcm = audio[44:] if audio[:4] == b"RIFF" else audio
        if self.t_ref is not None and not self.first_audio_done:
            self.first_audio_done = True
            ms = round((time.perf_counter() - self.t_ref) * 1000, 1)
            if self.conv:
                self.conv.metrics.setdefault("voice_latency_ms", []).append(ms)
            self.svc.meter.latency["voice_turn"].append(ms)
            await self.send_json({"type": "latency", "first_audio_ms": ms, "mode": "pipeline"})
        await self.send_json({"type": "state", "state": "speaking"})
        for i in range(0, len(pcm), 9600):
            await self.send_audio(pcm[i : i + 9600])
        await self.send_json({"type": "state", "state": "listening"})

    # ------------------------------------------------------------------ end
    async def end(self) -> None:
        if self.closed.is_set():
            return
        await self.svc.orchestrator.close(self.conv_id, by="customer", resolved=None)
        await self.send_json({"type": "ended", "reason": "closed"})
        await self.close()

    async def close(self) -> None:
        if self.closed.is_set():
            return
        self.closed.set()
        for t in self.tasks:
            t.cancel()
        if self.up is not None:
            try:
                await self.up.close()
            except Exception:
                pass
        conv = await self.svc.store.get(self.conv_id)
        if conv:
            conv.metrics["voice_barge_ins"] = self.barge_ins
            conv.usage = self.svc.meter.conversation(self.conv_id)
            await self.svc.store.save(conv, publish=False)
