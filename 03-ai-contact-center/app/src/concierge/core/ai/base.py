"""Shared AI types and protocols. Every AI call in the product goes through these interfaces:
an Azure implementation (managed identity) and a deterministic offline stub."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    audio_in_tokens: int = 0
    audio_out_tokens: int = 0
    reasoning_tokens: int = 0

    def add(self, other: Usage) -> None:
        for name in self.__dataclass_fields__:
            setattr(self, name, getattr(self, name) + getattr(other, name))


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""


@dataclass
class ChatResult:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    latency_ms: float = 0.0
    ttft_ms: float | None = None
    finish_reason: str = "stop"
    cost_usd: float = 0.0


@dataclass
class StreamEvent:
    kind: str  # "text" | "tool_call" | "done"
    text: str = ""
    tool_call: ToolCall | None = None
    result: ChatResult | None = None


class BudgetExceededError(RuntimeError):
    """Raised (fail closed) when the daily AI budget cap has been reached."""

    def __init__(self, spent: float, cap: float) -> None:
        self.spent = spent
        self.cap = cap
        super().__init__(
            f"Daily AI budget of ${cap:.2f} reached (spent ${spent:.2f}). AI features are paused until the next UTC day "
            "or until an administrator raises AI_DAILY_BUDGET_USD."
        )


class LLMClient(Protocol):
    name: str
    deterministic: bool

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        role: str = "chat",
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 700,
        reasoning_effort: str | None = "low",
        json_mode: bool = False,
        feature: str = "chat",
        conv_id: str | None = None,
        hints: dict[str, Any] | None = None,
    ) -> ChatResult: ...

    def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        role: str = "chat",
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 700,
        reasoning_effort: str | None = "low",
        feature: str = "chat",
        conv_id: str | None = None,
        hints: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamEvent]: ...

    async def embed(self, texts: list[str], *, feature: str = "embed") -> list[list[float]]: ...


@dataclass
class TranscriptResult:
    text: str
    language: str = ""
    duration_s: float = 0.0


class SpeechClient(Protocol):
    name: str

    async def transcribe(self, audio: bytes, *, mime: str = "audio/wav", language: str | None = None) -> TranscriptResult: ...

    async def synthesize(self, text: str, *, language: str = "en", voice: str | None = None) -> tuple[bytes, str]:
        """Returns (audio bytes, mime type)."""
        ...


@dataclass
class PiiEntity:
    category: str
    text: str
    offset: int
    length: int
    confidence: float = 1.0


class CognitiveClient(Protocol):
    """Azure AI Language + Content Safety (managed identity) or deterministic heuristics offline."""

    name: str

    async def detect_language(self, text: str) -> tuple[str, float]: ...

    async def pii_entities(self, text: str, language: str = "en") -> list[PiiEntity]: ...

    async def shield_prompt(self, user_prompt: str, documents: list[str] | None = None) -> dict[str, Any]: ...

    async def analyze_text(self, text: str) -> dict[str, int]: ...

    async def groundedness(self, query: str, answer: str, sources: list[str], language: str = "en") -> dict[str, Any]: ...
