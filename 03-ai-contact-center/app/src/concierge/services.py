"""Service container (dependency injection) and wiring for azure / offline modes."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .core.ai.base import BudgetExceededError  # noqa: F401  (re-exported for callers)
from .core.ai.stub_llm import StubLLM
from .core.ai.usage import UsageMeter
from .core.blobstore import MemoryBlobStore
from .core.config import Settings
from .core.registry import EventBus, FeatureRegistry
from .core.repo import InMemoryRepository, Repository
from .core.security import RateLimiter
from .core.tracing import TraceBuffer
from .engine.audit import AuditLog
from .engine.cognitive import OfflineCognitive, OfflineSpeech, ResilientCognitive
from .engine.guard import Guard

log = logging.getLogger("concierge.services")


@dataclass
class Services:
    settings: Settings
    repo: Repository
    blobs: Any
    meter: UsageMeter
    llm: Any
    speech: Any
    cognitive: Any
    guard: Guard
    bus: EventBus
    audit: AuditLog
    access_audit: AuditLog
    registry: FeatureRegistry | None = None
    limiter: RateLimiter = field(default_factory=RateLimiter)
    traces: TraceBuffer = field(default_factory=TraceBuffer)
    sandbox: bool = False
    # engine singletons (attached by engine.runtime.attach_engine)
    backoffice: Any = None
    oms: Any = None  # connector-backed facade: customer/order/case access goes through the configured CRM/OMS connector (CC-20)
    kb: Any = None
    store: Any = None
    configs: Any = None
    tools: Any = None
    orchestrator: Any = None
    ext: dict[str, Any] = field(default_factory=dict)
    seed_state: dict[str, Any] = field(default_factory=lambda: {"status": "pending", "steps": {}, "started": None, "finished": None})
    ready_cache: dict[str, Any] = field(default_factory=dict)
    _tasks: set[asyncio.Task] = field(default_factory=set)

    def spawn(self, coro: Any) -> asyncio.Task:
        """Fire-and-forget background task with strong reference + error logging."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)

        def _done(t: asyncio.Task) -> None:
            self._tasks.discard(t)
            if not t.cancelled() and t.exception():
                log.error("background task failed: %r", t.exception())

        task.add_done_callback(_done)
        return task

    async def drain(self) -> None:
        """Wait for background work (wrap-up, QA) - used by tests and the sandbox."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def start(self) -> None:
        await self.meter.load()
        await self.audit.init()
        await self.access_audit.init()

    async def stop(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        await self.meter.flush(force=True)
        for comp in (self.llm, self.speech, self.cognitive, self.repo, self.blobs):
            close = getattr(comp, "close", None)
            if close:
                try:
                    await close()
                except Exception as exc:  # pragma: no cover
                    log.warning("close failed: %s", exc)

    def make_sandbox(self, isolated_kb: bool = False) -> Services:
        """Isolated in-memory copy used by the evaluation harness (shares AI clients; shares the read-only KB index unless isolated_kb)."""
        from .engine.runtime import attach_engine

        repo = InMemoryRepository()
        sb = Services(
            settings=self.settings,
            repo=repo,
            blobs=MemoryBlobStore(),
            meter=self.meter,
            llm=self.llm,
            speech=self.speech,
            cognitive=self.cognitive,
            guard=Guard(self.cognitive, use_azure=self.guard.use_azure),
            bus=EventBus(),
            audit=AuditLog(repo),
            access_audit=AuditLog(repo, "access_audit"),
            registry=self.registry,
            limiter=self.limiter,
            sandbox=True,
        )
        attach_engine(sb, shared_kb=None if isolated_kb else self.kb, shared_configs=self.configs)
        return sb


def build_services(
    settings: Settings,
    *,
    repo: Repository | None = None,
    llm: Any | None = None,
    speech: Any | None = None,
    cognitive: Any | None = None,
    blobs: Any | None = None,
) -> Services:
    if settings.is_azure:  # pragma: no cover - needs Azure credentials
        from .core.ai.azure_cognitive import AzureCognitive, AzureSpeech
        from .core.ai.azure_llm import AzureLLM
        from .core.azure_auth import get_credential
        from .core.blobstore import AzureBlobStore
        from .core.cosmos_repo import CosmosRepository

        cred = get_credential(settings.client_id)
        repo = repo or CosmosRepository(settings.cosmos_endpoint, settings.cosmos_database, cred)
        blobs = blobs or (AzureBlobStore(settings.storage_account_url, cred) if settings.storage_account_url else MemoryBlobStore())
        meter = UsageMeter(settings.daily_budget_usd, repo, enforce=True)
        llm = llm or AzureLLM(settings, meter)
        speech = speech or AzureSpeech(settings, meter)
        cognitive = cognitive or ResilientCognitive(AzureCognitive(settings, meter), OfflineCognitive())
        use_azure_guard = True
    else:
        repo = repo or InMemoryRepository()
        blobs = blobs or MemoryBlobStore()
        meter = UsageMeter(settings.daily_budget_usd, repo, enforce=False)
        llm = llm or StubLLM(meter)
        speech = speech or OfflineSpeech()
        cognitive = cognitive or OfflineCognitive()
        use_azure_guard = False

    svc = Services(
        settings=settings,
        repo=repo,
        blobs=blobs,
        meter=meter,
        llm=llm,
        speech=speech,
        cognitive=cognitive,
        guard=Guard(cognitive, use_azure=use_azure_guard),
        bus=EventBus(),
        audit=AuditLog(repo),
        access_audit=AuditLog(repo, "access_audit"),
    )
    from .engine.runtime import attach_engine

    attach_engine(svc)
    return svc


def uptime_s() -> float:
    from .core.config import STARTED_AT

    return round(time.time() - STARTED_AT, 1)
