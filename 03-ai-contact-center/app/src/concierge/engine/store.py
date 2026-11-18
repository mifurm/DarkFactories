"""Conversation store (write-through cache over the repository, per-conversation locks, live summaries) and agent-config store (CC-17)."""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

from ..core.registry import EventBus
from ..core.repo import Repository
from .audit import AuditLog
from .models import AgentConfig, Conversation, new_id, now
from .prompts import default_config


class ConversationNotFound(KeyError):
    pass


class ConversationStore:
    def __init__(self, repo: Repository, bus: EventBus) -> None:
        self.repo = repo
        self.bus = bus
        self.cache: dict[str, Conversation] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, conv_id: str) -> asyncio.Lock:
        return self._locks.setdefault(conv_id, asyncio.Lock())

    async def create(self, **kw: Any) -> Conversation:
        conv = Conversation(id=kw.pop("id", None) or new_id("cv"), **kw)
        self.cache[conv.id] = conv
        await self.save(conv)
        return conv

    async def get(self, conv_id: str) -> Conversation | None:
        if conv_id in self.cache:
            return self.cache[conv_id]
        doc = await self.repo.get("conversations", conv_id)
        if not doc:
            return None
        doc.pop("pk", None)
        doc.pop("_ts", None)
        doc.pop("ttl", None)
        conv = Conversation.model_validate(doc)
        self.cache[conv_id] = conv
        return conv

    def _doc(self, conv: Conversation) -> dict[str, Any]:
        doc = conv.model_dump()
        for o in doc["outbox"]:
            o.pop("code", None)  # one-time codes live in memory only
        doc["identity"]["challenge"] = None
        if conv.consent.recording == "declined":
            for m in doc["messages"]:
                m["text"] = "[not recorded - recording consent declined]"
                m["translations"] = {}
            doc["tags"] = [*doc["tags"], "consent_declined"]
        return doc

    async def save(self, conv: Conversation, publish: bool = True) -> None:
        conv.updated_at = now()
        ttl = (7 if conv.consent.recording == "declined" else conv.retention_days) * 86400
        await self.repo.put("conversations", self._doc(conv), ttl=ttl)
        if publish:
            summary = self.summary(conv)
            await self.bus.publish("supervisor", {"type": "conversation.updated", "summary": summary})
            await self.bus.publish(f"conv:{conv.id}", {"type": "conversation.updated", "summary": summary})

    async def delete(self, conv_id: str) -> None:
        self.cache.pop(conv_id, None)
        await self.repo.delete("conversations", conv_id)

    def summary(self, conv: Conversation) -> dict[str, Any]:
        last_cust = next((m for m in reversed(conv.messages) if m.role == "customer"), None)
        u = conv.understanding
        tools = [t for m in conv.messages for t in m.tools]
        return {
            "id": conv.id, "channel": conv.channel, "status": conv.status, "language": conv.language, "customer": conv.customer_label,
            "verified": conv.identity.verified, "level": conv.identity.level, "intent": u.intent if u else None,
            "sentiment": conv.sentiment_trajectory[-1] if conv.sentiment_trajectory else 0.0, "emotion": u.emotion if u else "neutral",
            "risk_flags": conv.risk_flags, "queue": conv.queue, "priority": conv.priority, "handler": conv.handler, "assigned_agent": conv.assigned_agent,
            "active_agent": conv.active_agent, "created_at": conv.created_at, "updated_at": conv.updated_at, "messages": len(conv.messages),
            "last_customer_text": (last_cust.text[:140] if last_cust else ""), "tools": len(tools), "sim": conv.sim, "config_version": conv.config_version,
            "waiting_since": conv.handoff.get("created_at") if conv.handoff and conv.handler == "queue" else None, "sla_s": (conv.handoff or {}).get("routing", {}).get("sla_s"),
            "disposition": (conv.wrapup or {}).get("disposition"), "qa_score": (conv.qa or {}).get("overall"), "eval_run_id": conv.eval_run_id,
        }

    async def list_live(self) -> list[Conversation]:
        return [c for c in self.cache.values() if c.status in ("active", "waiting_human", "with_human") and not c.eval_run_id]

    async def recent(self, limit: int = 50, where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        docs = await self.repo.query("conversations", where, order_by="updated_at", desc=True, limit=limit)
        out = []
        for d in docs:
            live = self.cache.get(d["id"])
            out.append(self.summary(live) if live else self.summary(Conversation.model_validate({k: v for k, v in d.items() if k not in ("pk", "_ts", "ttl")})))
        return out


class ConfigStore:
    """Versioned agent configs: prompts, tool allow-lists, policy parameters; canary assignment by deterministic hash; rollback."""

    def __init__(self, repo: Repository, audit: AuditLog) -> None:
        self.repo = repo
        self.audit = audit
        self._cache: dict[str, AgentConfig] = {}
        self.active_id = "cfg-v1"
        self.canary_id: str | None = None
        self.canary_pct = 0

    async def load(self) -> None:
        rows = await self.repo.query("agent_configs")
        if not rows:
            base = default_config()
            await self.repo.put("agent_configs", base.model_dump())
            rows = [base.model_dump()]
        self._cache = {}
        for r in rows:
            r.pop("pk", None)
            r.pop("_ts", None)
            cfg = AgentConfig.model_validate(r)
            self._cache[cfg.id] = cfg
        act = [c for c in self._cache.values() if c.status == "active"]
        self.active_id = max(act, key=lambda c: c.version).id if act else "cfg-v1"
        can = [c for c in self._cache.values() if c.status == "canary"]
        self.canary_id = can[0].id if can else None
        self.canary_pct = can[0].canary_pct if can else 0

    async def active(self) -> AgentConfig:
        if not self._cache:
            await self.load()
        return self._cache[self.active_id]

    async def get(self, cfg_id: str) -> AgentConfig | None:
        if not self._cache:
            await self.load()
        return self._cache.get(cfg_id)

    async def list(self) -> list[AgentConfig]:
        if not self._cache:
            await self.load()
        return sorted(self._cache.values(), key=lambda c: c.version, reverse=True)

    async def assign(self, conv_id: str) -> AgentConfig:
        """Canary: a deterministic hash of the conversation id decides whether it runs on the canary config."""
        if not self._cache:
            await self.load()
        if self.canary_id and self.canary_pct > 0:
            bucket = int(hashlib.sha1(conv_id.encode()).hexdigest(), 16) % 100
            if bucket < self.canary_pct:
                return self._cache[self.canary_id]
        return self._cache[self.active_id]

    async def save(self, cfg: AgentConfig) -> AgentConfig:
        await self.repo.put("agent_configs", cfg.model_dump())
        self._cache[cfg.id] = cfg
        return cfg

    async def create_version(self, base_id: str | None, *, name: str, prompts: dict[str, str] | None = None, tools: dict[str, list[str]] | None = None, policy: dict[str, Any] | None = None, notes: str = "", author: str = "system") -> AgentConfig:
        base = await self.get(base_id or self.active_id) or await self.active()
        n = max((c.version for c in self._cache.values()), default=0) + 1
        cfg = AgentConfig(
            id=f"cfg-v{n}", name=name, version=n, status="candidate",
            prompts={**base.prompts, **(prompts or {})}, tools={**{k: list(v) for k, v in base.tools.items()}, **(tools or {})},
            policy={**base.policy, **(policy or {})}, models=dict(base.models), notes=notes, created_by=author, parent=base.id,
        )  # fmt: skip
        await self.save(cfg)
        await self.audit.log("config.created", actor=author, resource=cfg.id, detail={"parent": base.id, "name": name})
        return cfg

    async def set_status(self, cfg_id: str, status: str, actor: str = "system", canary_pct: int = 0) -> AgentConfig:
        cfg = await self.get(cfg_id)
        if cfg is None:
            raise KeyError(cfg_id)
        if status == "active":
            for c in list(self._cache.values()):
                if c.status == "active" and c.id != cfg_id:
                    c.status = "retired"
                    await self.save(c)
            self.active_id = cfg_id
            cfg.canary_pct = 0
            self.canary_id, self.canary_pct = None, 0
        if status == "canary":
            for c in list(self._cache.values()):
                if c.status == "canary" and c.id != cfg_id:
                    c.status = "candidate"
                    c.canary_pct = 0
                    await self.save(c)
            cfg.canary_pct = canary_pct
            self.canary_id, self.canary_pct = cfg_id, canary_pct
        cfg.status = status
        await self.save(cfg)
        await self.audit.log(f"config.{status}", actor=actor, resource=cfg_id, detail={"canary_pct": canary_pct})
        return cfg


def epoch_ms() -> int:
    return int(time.time() * 1000)
