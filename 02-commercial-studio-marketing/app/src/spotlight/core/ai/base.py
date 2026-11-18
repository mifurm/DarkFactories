"""AI abstractions: every model call goes through these interfaces.

Each interface has (a) an Azure implementation using Entra (managed identity / az login — no keys) and
(b) a deterministic offline stub, so tests, CI and local-without-Azure runs never need the network.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class AICtx:
    """Attribution context for metering: which campaign / feature a call belongs to."""

    campaign_id: str | None = None
    feature: str | None = None
    ref: str | None = None
    premium_ok: bool = False


_ctx: ContextVar[AICtx] = ContextVar("ai_ctx", default=AICtx())  # noqa: B039 - the default is never mutated; set_ctx() always installs a new AICtx


def current_ctx() -> AICtx:
    return _ctx.get()


def set_ctx(**kw: Any) -> Token:
    cur = _ctx.get()
    return _ctx.set(AICtx(**{**cur.__dict__, **kw}))


def reset_ctx(token: Token) -> None:
    _ctx.reset(token)


@dataclass
class ImageResult:
    data: bytes
    mime: str
    model: str
    size: str
    quality: str
    prompt_digest: str
    cached: bool = False
    cost_usd: float = 0.0
    provider: str = "azure-openai"


@dataclass
class SpeechResult:
    data: bytes
    mime: str
    voice: str
    lang: str
    chars: int
    model: str
    cached: bool = False
    cost_usd: float = 0.0
    provider: str = "azure-openai"


@dataclass
class SafetyResult:
    categories: dict[str, int] = field(default_factory=dict)
    protected_material: bool | None = None
    attack_detected: bool | None = None
    provider: str = "azure-content-safety"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def max_severity(self) -> int:
        return max(self.categories.values(), default=0)


@dataclass
class VoiceInfo:
    id: str  # "openai:nova" | "neural:de-DE-KatjaNeural"
    name: str
    provider: str
    lang: str  # BCP-47 primary language ("en", "de", ...)
    gender: str = ""
    style: str = ""


class LLMClient(Protocol):
    mode: str

    async def complete(
        self,
        *,
        task: str,
        system: str,
        user: str,
        schema: type[T],
        role: str = "chat",
        max_tokens: int = 2500,
        effort: str = "minimal",
        context: dict[str, Any] | None = None,
        fresh: bool = False,
    ) -> T: ...

    async def complete_text(
        self,
        *,
        task: str,
        system: str,
        user: str,
        role: str = "chat",
        max_tokens: int = 1200,
        effort: str = "minimal",
        context: dict[str, Any] | None = None,
        fresh: bool = False,
    ) -> str: ...

    async def ping(self) -> dict[str, Any]: ...


class ImageClient(Protocol):
    mode: str

    async def generate(
        self,
        prompt: str,
        *,
        size: str = "1536x1024",
        quality: str = "low",
        model_role: str = "image",
        references: list[bytes] | None = None,
        seed: int | None = None,
        palette: list[str] | None = None,
        fresh: bool = False,
    ) -> ImageResult: ...


class SpeechClient(Protocol):
    mode: str

    def voices(self) -> list[VoiceInfo]: ...

    async def synthesize(
        self, text: str, *, voice: str = "openai:nova", lang: str = "en", speed: float = 1.0, fresh: bool = False
    ) -> SpeechResult: ...

    async def ping(self) -> dict[str, Any]: ...


class EmbeddingClient(Protocol):
    mode: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class SafetyClient(Protocol):
    mode: str

    async def analyze_text(self, text: str) -> SafetyResult: ...
    async def analyze_image(self, data: bytes) -> SafetyResult: ...
    async def protected_material(self, text: str) -> bool: ...
    async def shield_prompt(self, user_prompt: str, documents: list[str] | None = None) -> bool: ...
    async def ping(self) -> dict[str, Any]: ...
