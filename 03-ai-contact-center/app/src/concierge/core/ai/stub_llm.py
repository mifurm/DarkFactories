"""Deterministic offline LLM stub. A domain 'brain' (engine/stub_brain.py) is injected to drive tool-calling turns."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from typing import Any

from .base import ChatResult, StreamEvent, Usage
from .embedding import hashed_embedding
from .usage import UsageMeter

Brain = Callable[[list[dict[str, Any]], list[dict[str, Any]] | None, dict[str, Any]], ChatResult]


def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class StubLLM:
    name = "stub"
    deterministic = True

    def __init__(self, meter: UsageMeter | None = None, brain: Brain | None = None) -> None:
        self.meter = meter
        self.brain = brain

    def _run(self, messages, tools, hints) -> ChatResult:
        if self.brain:
            return self.brain(messages, tools, hints or {})
        last = next((m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"), "")
        return ChatResult(text=f"(offline stub) {last[:120]}")

    def _meter(self, res: ChatResult, messages, role: str, feature: str, conv_id: str | None) -> ChatResult:
        res.model = res.model or f"stub-{role}"
        res.usage = Usage(
            input_tokens=sum(approx_tokens(str(m.get("content") or "")) for m in messages),
            output_tokens=approx_tokens(res.text) + 25 * len(res.tool_calls),
        )
        if self.meter:
            res.cost_usd = self.meter.record(
                model="gpt-5.4-mini", feature=feature, usage=res.usage, conv_id=conv_id, latency_ms=res.latency_ms, simulated=True
            )
        return res

    async def chat(
        self,
        messages,
        *,
        role="chat",
        tools=None,
        max_tokens=700,
        reasoning_effort="low",
        json_mode=False,
        feature="chat",
        conv_id=None,
        hints=None,
    ) -> ChatResult:
        res = self._run(messages, tools, hints)
        res.latency_ms = 1.0
        return self._meter(res, messages, role, feature, conv_id)

    async def stream(
        self,
        messages,
        *,
        role="chat",
        tools=None,
        max_tokens=700,
        reasoning_effort="low",
        feature="chat",
        conv_id=None,
        hints=None,
    ) -> AsyncIterator[StreamEvent]:
        res = self._run(messages, tools, hints)
        res.latency_ms = 1.0
        res.ttft_ms = 1.0 if res.text else None
        for piece in re.findall(r"\S+\s*", res.text):
            yield StreamEvent("text", text=piece)
        self._meter(res, messages, role, feature, conv_id)
        yield StreamEvent("done", result=res)

    async def embed(self, texts: list[str], *, feature: str = "embed") -> list[list[float]]:
        return [hashed_embedding(t) for t in texts]

    async def ping(self) -> dict[str, Any]:
        return {"ok": True, "model": "offline-stub", "latency_ms": 0.0}

    async def close(self) -> None:
        return None
