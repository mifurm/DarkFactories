"""Diagnostic: prove the Azure OpenAI Realtime path with an Entra (managed identity / az login) bearer token.

Text input -> audio + transcript output, one tool-call round trip. Usage:
    python scripts/diagnose_realtime.py --endpoint https://<ai>.openai.azure.com --deployment gpt-realtime-2.1-mini
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import time

from azure.identity import AzureCliCredential
from websockets.asyncio.client import connect

TOOLS = [
    {
        "type": "function",
        "name": "lookup_order",
        "description": "Look up an order by its id.",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]},
    }
]


async def run(endpoint: str, deployment: str, variant: str, tools: bool) -> dict:
    token = AzureCliCredential().get_token("https://cognitiveservices.azure.com/.default").token
    host = endpoint.replace("https://", "")
    url = f"wss://{host}/openai/v1/realtime?model={deployment}"
    t0 = time.perf_counter()
    events: list[str] = []
    audio_bytes = 0
    transcript = ""
    first_audio_ms = None
    tool_called = None
    async with connect(url, additional_headers={"Authorization": f"Bearer {token}"}, max_size=None) as ws:
        session = {
            "type": "realtime",
            "instructions": "You are a concise contact-center agent. Speak briefly. Use tools when needed.",
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "transcription": {"model": "gpt-4o-mini-transcribe"},
                    "turn_detection": {"type": "server_vad", "silence_duration_ms": 500, "create_response": True, "interrupt_response": True},
                },
                "output": {"format": {"type": "audio/pcm", "rate": 24000}, "voice": "marin"},
            },
            "tool_choice": "auto",
        }
        if tools:
            session["tools"] = TOOLS
        if variant == "preview":
            session = {
                "modalities": ["audio", "text"],
                "instructions": session["instructions"],
                "voice": "alloy",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {"model": "gpt-4o-mini-transcribe"},
                "turn_detection": {"type": "server_vad"},
            }
        await ws.send(json.dumps({"type": "session.update", "session": session}))
        prompt = "Please look up order CH-100231 and tell me its status in one short sentence." if tools else "Say hello in German in one short sentence."
        await ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": prompt}]},
                }
            )
        )
        await ws.send(json.dumps({"type": "response.create"}))
        deadline = time.perf_counter() + 40
        responses_done = 0
        while time.perf_counter() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
            ev = json.loads(raw)
            et = ev.get("type", "")
            if et not in events[-1:]:
                events.append(et)
            if et in ("response.output_audio.delta", "response.audio.delta"):
                audio_bytes += len(base64.b64decode(ev.get("delta", "")))
                first_audio_ms = first_audio_ms or round((time.perf_counter() - t0) * 1000)
            elif et in ("response.output_audio_transcript.delta", "response.audio_transcript.delta"):
                transcript += ev.get("delta", "")
            elif et == "response.function_call_arguments.done":
                tool_called = {"name": ev.get("name"), "args": ev.get("arguments")}
                await ws.send(
                    json.dumps(
                        {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": ev.get("call_id"),
                                "output": json.dumps({"order_id": "CH-100231", "status": "delivered", "damaged": True}),
                            },
                        }
                    )
                )
                await ws.send(json.dumps({"type": "response.create"}))
            elif et == "error":
                return {"ok": False, "error": ev.get("error"), "events": events}
            elif et == "response.done":
                responses_done += 1
                if not tools or responses_done >= 2 or tool_called is None and responses_done >= 1 and not tool_called:
                    if tools and tool_called is None and responses_done == 1:
                        continue
                    usage = (ev.get("response") or {}).get("usage")
                    return {
                        "ok": True,
                        "deployment": deployment,
                        "variant": variant,
                        "first_audio_ms": first_audio_ms,
                        "audio_bytes": audio_bytes,
                        "audio_seconds": round(audio_bytes / 2 / 24000, 2),
                        "transcript": transcript,
                        "tool_called": tool_called,
                        "usage": usage,
                        "total_ms": round((time.perf_counter() - t0) * 1000),
                        "event_types": events[:30],
                    }
    return {"ok": False, "error": "timeout", "events": events}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--deployment", default="gpt-realtime-2.1-mini")
    ap.add_argument("--variant", default="ga", choices=["ga", "preview"])
    ap.add_argument("--tools", action="store_true")
    a = ap.parse_args()
    print(json.dumps(asyncio.run(run(a.endpoint, a.deployment, a.variant, a.tools)), indent=2, default=str))
