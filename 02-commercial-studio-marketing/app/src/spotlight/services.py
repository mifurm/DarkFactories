"""Service container: wires repository, blobs, AI clients, meter/guard, jobs, vector index, audit."""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .core.ai.cache import AICache
from .core.ai.meter import BudgetGuard, UsageMeter
from .core.ai.stubs import StubEmbeddings, StubImage, StubLLM, StubSafety, StubSpeech
from .core.audit import AuditLog
from .core.blobs import AzureBlobStore, LocalDirBlobStore, MemoryBlobStore
from .core.jobs import JobRunner
from .core.notify import Notifier
from .core.repo import MemoryRepository
from .core.vector import VectorIndex
from .security import RateLimiter


@dataclass
class Services:
    settings: Settings
    repo: Any
    blobs: Any
    llm: Any
    image: Any
    speech: Any
    embeddings: Any
    safety: Any
    meter: UsageMeter
    guard: BudgetGuard
    cache: AICache
    jobs: JobRunner
    vectors: VectorIndex
    audit: AuditLog
    limiter: RateLimiter
    notifier: Notifier
    credential: Any = None
    motion: Any = None  # the cinematic-motion backend (spotlight.motion.MotionClient)
    started_at: float = field(default_factory=time.time)
    route_stats: dict[str, dict[str, float]] = field(default_factory=dict)
    ready_cache: dict[str, Any] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)

    async def close(self) -> None:
        await self.jobs.shutdown()
        with contextlib.suppress(Exception):
            await self.notifier.close()
        for obj in (self.repo, self.blobs, self.motion):
            if obj is None:
                continue
            with contextlib.suppress(Exception):
                await obj.close()
        for obj in (self.llm, self.image, self.speech, self.embeddings, self.safety):
            for attr in ("client", "_http"):
                c = getattr(obj, attr, None)
                if c is not None and hasattr(c, "aclose"):
                    with contextlib.suppress(Exception):
                        await c.aclose()
                elif c is not None and hasattr(c, "close"):
                    with contextlib.suppress(Exception):
                        await c.close()
        if self.credential is not None:
            with contextlib.suppress(Exception):
                await self.credential.close()


def _resolve(value: str, azure: bool, azure_name: str, offline_name: str) -> str:
    if value != "auto":
        return value
    return azure_name if azure else offline_name


async def build_services(settings: Settings) -> Services:
    azure = settings.mode == "azure"
    repo_backend = _resolve(settings.repo_backend, azure, "cosmos", "memory")
    blob_backend = _resolve(settings.blob_backend, azure, "azure", "localdir" if settings.data_dir else "memory")
    ai_backend = _resolve(settings.ai_backend, azure, "azure", "stub")

    credential = None
    if "azure" in (blob_backend, ai_backend) or repo_backend == "cosmos" or settings.motion_effective_mode == "azure":
        from .core.ai.azure import make_credential

        credential = make_credential(settings.azure_client_id)

    if repo_backend == "cosmos":
        from .core.repo.cosmos import CosmosRepository

        repo: Any = CosmosRepository(settings.cosmos_endpoint, settings.cosmos_database, credential)
    else:
        repo = MemoryRepository()

    if blob_backend == "azure":
        blobs: Any = AzureBlobStore(settings.blob_account_url, settings.blob_container, credential)
    elif blob_backend == "localdir":
        blobs = LocalDirBlobStore(settings.data_dir)
    else:
        blobs = MemoryBlobStore()

    notifier = Notifier(repo, settings)
    meter = UsageMeter(repo, simulated=ai_backend == "stub")
    guard = BudgetGuard(meter, repo, settings.daily_ai_budget_usd, settings.campaign_ai_budget_usd, on_alert=notifier.emit)
    cache = AICache(repo, blobs)

    if ai_backend == "azure":
        from .core.ai.azure import AzureEmbeddings, AzureImage, AzureLLM, AzureSafety, AzureSpeech

        llm: Any = AzureLLM(settings, credential, meter, guard, cache)
        image: Any = AzureImage(settings, credential, meter, guard, cache)
        speech: Any = AzureSpeech(settings, credential, meter, guard, cache)
        embeddings: Any = AzureEmbeddings(settings, credential, meter, guard)
        safety: Any = AzureSafety(settings, credential, meter, guard)
    else:
        llm = StubLLM(meter, guard)
        image = StubImage(meter, guard)
        speech = StubSpeech(meter, guard)
        embeddings = StubEmbeddings(meter, guard)
        safety = StubSafety(meter, guard)

    jobs = JobRunner(repo, max_concurrent=settings.max_concurrent_jobs, instance_id=settings.instance_id, on_event=notifier.emit)
    notifier.attach()
    from .motion import build_client

    motion = build_client(settings, credential)
    return Services(
        settings=settings,
        repo=repo,
        blobs=blobs,
        llm=llm,
        image=image,
        speech=speech,
        embeddings=embeddings,
        safety=safety,
        meter=meter,
        guard=guard,
        cache=cache,
        jobs=jobs,
        vectors=VectorIndex(repo, embeddings),
        audit=AuditLog(repo),
        limiter=RateLimiter(settings.rate_limit_enabled),
        notifier=notifier,
        credential=credential,
        motion=motion,
    )
