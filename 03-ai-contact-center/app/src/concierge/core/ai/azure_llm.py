"""Azure OpenAI (Foundry) LLM client over the v1 endpoint with Entra bearer tokens (managed identity)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import openai
from openai import AsyncOpenAI

from ..azure_auth import token_provider
from ..config import Settings
from .base import ChatResult, StreamEvent, ToolCall, Usage
from .usage import UsageMeter

log = logging.getLogger("concierge.llm")


def _safe_json(raw: str) -> dict[str, Any]:
    try:
        val = json.loads(raw or "{}")
        return val if isinstance(val, dict) else {"value": val}
    except json.JSONDecodeError:
        return {"_unparsed": raw[:500]}


def _usage_from(u: Any) -> Usage:
    if not u:
        return Usage()
    details = getattr(u, "prompt_tokens_details", None)
    cdetails = getattr(u, "completion_tokens_details", None)
    return Usage(
        input_tokens=getattr(u, "prompt_tokens", 0) or 0,
        output_tokens=getattr(u, "completion_tokens", 0) or 0,
        cached_tokens=(getattr(details, "cached_tokens", 0) or 0) if details else 0,
        reasoning_tokens=(getattr(cdetails, "reasoning_tokens", 0) or 0) if cdetails else 0,
    )


class AzureLLM:
    name = "azure"
    deterministic = False

    def __init__(self, settings: Settings, meter: UsageMeter) -> None:
        self.s = settings
        self.meter = meter
        self._client = AsyncOpenAI(
            base_url=f"{settings.openai_endpoint}/openai/v1/",
            api_key=token_provider(settings.client_id),
            timeout=httpx.Timeout(60.0, connect=10.0),
            max_retries=6,  # 429 / transient errors back off exponentially (honours Retry-After)
        )
        self._effort_unsupported: set[str] = set()

    def model_for(self, role: str) -> str:
        return self.s.deployment(role)

    def _kwargs(self, role, messages, tools, max_tokens, reasoning_effort, json_mode) -> dict[str, Any]:
        model = self.model_for(role)
        kw: dict[str, Any] = {"model": model, "messages": messages, "max_completion_tokens": max_tokens}
        if reasoning_effort and model not in self._effort_unsupported:
            kw["reasoning_effort"] = reasoning_effort
        if tools:
            kw["tools"] = tools
            kw["parallel_tool_calls"] = False
        if json_mode:
            kw["response_format"] = {"type": "json_object"}
        return kw

    async def _create(self, kw: dict[str, Any]):
        try:
            return await self._client.chat.completions.create(**kw)
        except openai.BadRequestError as exc:
            msg = str(exc).lower()
            if "reasoning_effort" in msg and "reasoning_effort" in kw:
                log.warning("reasoning_effort=%s rejected by %s; retrying without", kw["reasoning_effort"], kw["model"])
                self._effort_unsupported.add(kw["model"])
                kw = {k: v for k, v in kw.items() if k != "reasoning_effort"}
                return await self._client.chat.completions.create(**kw)
            raise

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
        self.meter.check_budget()
        kw = self._kwargs(role, messages, tools, max_tokens, reasoning_effort, json_mode)
        t0 = time.perf_counter()
        try:
            resp = await self._create(kw)
        except openai.BadRequestError as exc:
            if getattr(exc, "code", "") == "content_filter" or "content_filter" in str(exc):
                return ChatResult(text="", finish_reason="content_filter", model=kw["model"])
            raise
        latency = (time.perf_counter() - t0) * 1000
        choice = resp.choices[0]
        calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=_safe_json(tc.function.arguments), raw_arguments=tc.function.arguments)
            for tc in (choice.message.tool_calls or [])
            if getattr(tc, "function", None)
        ]
        usage = _usage_from(resp.usage)
        cost = self.meter.record(model=kw["model"], feature=feature, usage=usage, conv_id=conv_id, latency_ms=latency)
        return ChatResult(
            text=choice.message.content or "",
            tool_calls=calls,
            usage=usage,
            model=kw["model"],
            latency_ms=latency,
            finish_reason=choice.finish_reason or "stop",
            cost_usd=cost,
        )

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
        self.meter.check_budget()
        kw = self._kwargs(role, messages, tools, max_tokens, reasoning_effort, False)
        kw["stream"] = True
        kw["stream_options"] = {"include_usage": True}
        t0 = time.perf_counter()
        ttft: float | None = None
        text_parts: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        usage = Usage()
        finish = "stop"
        try:
            resp = await self._create(kw)
            async for chunk in resp:
                if getattr(chunk, "usage", None):
                    usage = _usage_from(chunk.usage)
                if not chunk.choices:
                    continue
                ch = chunk.choices[0]
                delta = ch.delta
                if delta and delta.content:
                    if ttft is None:
                        ttft = (time.perf_counter() - t0) * 1000
                    text_parts.append(delta.content)
                    yield StreamEvent("text", text=delta.content)
                if delta and delta.tool_calls:
                    for tc in delta.tool_calls:
                        slot = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function and tc.function.name:
                            slot["name"] += tc.function.name
                        if tc.function and tc.function.arguments:
                            slot["args"] += tc.function.arguments
                if ch.finish_reason:
                    finish = ch.finish_reason
        except openai.BadRequestError as exc:
            if getattr(exc, "code", "") == "content_filter" or "content_filter" in str(exc):
                finish = "content_filter"
            else:
                raise
        latency = (time.perf_counter() - t0) * 1000
        tool_calls = [
            ToolCall(id=c["id"] or f"call_{i}", name=c["name"], arguments=_safe_json(c["args"]), raw_arguments=c["args"])
            for i, c in sorted(calls.items())
            if c["name"]
        ]
        cost = self.meter.record(model=kw["model"], feature=feature, usage=usage, conv_id=conv_id, latency_ms=latency)
        yield StreamEvent(
            "done",
            result=ChatResult(
                text="".join(text_parts),
                tool_calls=tool_calls,
                usage=usage,
                model=kw["model"],
                latency_ms=latency,
                ttft_ms=ttft,
                finish_reason=finish,
                cost_usd=cost,
            ),
        )

    async def embed(self, texts: list[str], *, feature: str = "embed") -> list[list[float]]:
        self.meter.check_budget()
        model = self.s.deployment("embed")
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            batch = texts[i : i + 64]
            t0 = time.perf_counter()
            resp = await self._client.embeddings.create(model=model, input=batch, dimensions=512)
            out.extend([d.embedding for d in resp.data])
            tokens = getattr(resp.usage, "prompt_tokens", 0) if resp.usage else 0
            self.meter.record(
                model=model, feature=feature, usage=Usage(input_tokens=tokens), latency_ms=(time.perf_counter() - t0) * 1000
            )
        return out

    async def ping(self) -> dict[str, Any]:
        t0 = time.perf_counter()
        res = await self.chat(
            [{"role": "user", "content": "Reply with the single word: pong"}],
            role="nano",
            max_tokens=16,
            reasoning_effort="minimal",
            feature="readyz",
        )
        return {"ok": True, "model": res.model, "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "reply": res.text.strip()[:20]}

    async def close(self) -> None:
        await self._client.close()
