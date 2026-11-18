"""Domain models shared by the engine and all features (pydantic v2; persisted as plain dicts)."""

from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, Field


def now() -> float:
    return time.time()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Citation(BaseModel):
    ref: str = ""  # K1, K2 ... as used in the answer text
    doc_id: str
    title: str
    chunk_id: str
    snippet: str
    score: float = 0.0
    version: int | None = None


class ToolRecord(BaseModel):
    id: str
    name: str
    agent: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    status: str = "ok"  # ok | error | blocked | confirmation_required | approval_required | replayed
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    latency_ms: float = 0.0
    ts: float = Field(default_factory=now)
    idempotency_key: str | None = None
    actor: str = "ai"


class Message(BaseModel):
    id: str
    idx: int
    role: str  # customer | agent_ai | agent_human | supervisor | system_notice
    text: str
    ts: float = Field(default_factory=now)
    lang: str | None = None
    author: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    tools: list[ToolRecord] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
    translations: dict[str, str] = Field(default_factory=dict)
    visible_to_customer: bool = True


class Understanding(BaseModel):
    intent: str = "other"
    secondary: list[str] = Field(default_factory=list)
    entities: dict[str, Any] = Field(default_factory=dict)
    sentiment: float = 0.0  # -1 .. 1
    emotion: str = "neutral"
    urgency: str = "normal"  # low | normal | high | critical
    risk_flags: list[str] = Field(default_factory=list)
    language: str = "en"
    confidence: float = 0.5
    source: str = "rules"


class IdentityState(BaseModel):
    verified: bool = False
    level: int = 0  # 0 anonymous | 1 OTP (or KBA fallback) | 2 step-up (OTP + KBA)
    method: str | None = None
    customer_id: str | None = None
    verified_at: float | None = None
    attempts: int = 0
    locked: bool = False
    challenge: dict[str, Any] | None = None  # {code_hash, salt, customer_id, expires_at, channel, destination_masked}
    kba_attempts: int = 0
    candidate_customer_id: str | None = None


class Consent(BaseModel):
    ai_disclosure_shown_at: float | None = None
    ai_disclosure_text_version: str = "ai-disclosure-2026-11"
    recording: str = "pending"  # pending | granted | declined
    recording_ts: float | None = None
    recording_text_version: str = "recording-consent-2026-11"
    privacy_notice_version: str = "2026-11"
    payment_handoff_used: bool = False


class Pending(BaseModel):
    action_id: str
    tool: str
    args: dict[str, Any]
    summary: str
    fingerprint: str
    created_turn: int
    confirmed: bool = False
    confirmation_ref: str | None = None


class Conversation(BaseModel):
    id: str
    channel: str = "web_chat"
    status: str = "active"  # active | waiting_human | with_human | resolved | closed | abandoned
    language: str = "en"
    created_at: float = Field(default_factory=now)
    updated_at: float = Field(default_factory=now)
    closed_at: float | None = None
    customer_label: str | None = None
    identity: IdentityState = Field(default_factory=IdentityState)
    consent: Consent = Field(default_factory=Consent)
    understanding: Understanding | None = None
    sentiment_trajectory: list[float] = Field(default_factory=list)
    intent_trail: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    handler: str = "ai"  # ai | queue | human
    queue: str | None = None
    priority: int = 50
    assigned_agent: str | None = None
    active_agent: str = "greeter"
    agent_trace: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    handoff: dict[str, Any] | None = None
    wrapup: dict[str, Any] | None = None
    qa: dict[str, Any] | None = None
    pending: list[Pending] = Field(default_factory=list)
    outbox: list[dict[str, Any]] = Field(default_factory=list)
    payment: dict[str, Any] | None = None
    counters: dict[str, int] = Field(default_factory=lambda: {"tool_failures": 0, "kb_misses": 0, "no_progress": 0, "turns": 0})
    metrics: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, float] = Field(default_factory=dict)
    entities: dict[str, Any] = Field(default_factory=dict)
    kb_used: list[str] = Field(default_factory=list)
    supervisor_notes: list[dict[str, Any]] = Field(default_factory=list)
    config_version: str = "cfg-v1"
    sim: bool = False
    eval_run_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    retention_days: int = 365

    def next_idx(self) -> int:
        return len(self.messages)

    def add(self, role: str, text: str, **kw: Any) -> Message:
        m = Message(id=new_id("m"), idx=self.next_idx(), role=role, text=text, **kw)
        self.messages.append(m)
        self.updated_at = m.ts
        return m

    def transcript(self, customer_visible: bool = True, limit: int | None = None) -> list[dict[str, Any]]:
        msgs = [m for m in self.messages if m.visible_to_customer or not customer_visible]
        if limit:
            msgs = msgs[-limit:]
        return [{"role": m.role, "text": m.text, "ts": m.ts, "idx": m.idx} for m in msgs]

    def public_view(self) -> dict[str, Any]:
        """Customer-safe projection (no internal state, whispers, challenge hashes)."""
        d = self.model_dump(exclude={"identity", "steps", "agent_trace", "supervisor_notes", "qa", "wrapup", "handoff", "metrics", "counters"})
        d["messages"] = [m.model_dump() for m in self.messages if m.visible_to_customer]
        d["identity"] = {"verified": self.identity.verified, "level": self.identity.level, "method": self.identity.method, "locked": self.identity.locked}
        d["pending"] = [p.model_dump() for p in self.pending]
        d["outbox"] = list(self.outbox)  # simulated SMS/e-mail inbox of the customer; OTP codes live in memory only (never persisted)
        return d


class AgentConfig(BaseModel):
    id: str
    name: str
    version: int
    status: str = "draft"  # draft | candidate | canary | active | retired
    prompts: dict[str, str] = Field(default_factory=dict)
    tools: dict[str, list[str]] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)
    models: dict[str, str] = Field(default_factory=dict)
    kb_version: int | None = None
    notes: str = ""
    created_at: float = Field(default_factory=now)
    created_by: str = "system"
    canary_pct: int = 0
    gate: dict[str, Any] | None = None
    parent: str | None = None
