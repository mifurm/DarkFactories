"""Composition root: builds the adapters (Azure or offline) and owns the long-lived services of the process."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from nightshift import APP_NAME, __version__
from nightshift.config import Settings
from nightshift.core.bus import EventHub
from nightshift.core.llm import AzureLLM, LLMClient, StubLLM
from nightshift.core.obs import Metrics
from nightshift.core.registry import LoadedFeature
from nightshift.core.repo import (
    AzureBlobStore,
    BlobStore,
    CosmosRepository,
    MemoryBlobStore,
    MemoryRepository,
    Repository,
    WriteBehind,
)
from nightshift.core.usage import UsageMeter

log = logging.getLogger("nightshift.runtime")

READY_TTL_S = {"cosmos": 30.0, "storage": 30.0, "openai": 300.0}


def build_credential(settings: Settings) -> Any:  # pragma: no cover - needs Azure
    from azure.identity.aio import DefaultAzureCredential

    return (
        DefaultAzureCredential(managed_identity_client_id=settings.azure_client_id)
        if settings.azure_client_id
        else DefaultAzureCredential()
    )


class Runtime:
    def __init__(
        self,
        settings: Settings,
        features: list[LoadedFeature],
        repo: Repository,
        blobs: BlobStore,
        llm: LLMClient,
        usage: UsageMeter,
        credential: Any = None,
    ) -> None:
        self.settings = settings
        self.features = features
        self.repo, self.blobs, self.llm, self.usage = repo, blobs, llm, usage
        self.credential = credential
        self.hub = EventHub()
        self.metrics = Metrics()
        self.writer = WriteBehind(repo)
        self.started_at = time.time()
        self._ready_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._tasks: list[asyncio.Task] = []
        self.fleet: Any = None  # nightshift.plant.fleet.Fleet once the domain layer is loaded
        self.extras: dict[str, Any] = {}
        from nightshift.features.df23_rbac.rbac import Rbac

        self.rbac = Rbac(settings)

    @classmethod
    async def create(cls, settings: Settings, features: list[LoadedFeature]) -> Runtime:
        usage = UsageMeter(settings.daily_ai_budget_usd)
        cred = None
        repo: Repository = MemoryRepository()
        blobs: BlobStore = MemoryBlobStore()
        llm: LLMClient = StubLLM()
        if settings.is_azure:  # pragma: no cover - needs Azure
            cred = build_credential(settings)
            if settings.cosmos_endpoint:
                repo = CosmosRepository(settings.cosmos_endpoint, settings.cosmos_database, cred)
            if settings.storage_account_url:
                blobs = AzureBlobStore(settings.storage_account_url, cred)
            if settings.openai_endpoint:
                llm = AzureLLM(
                    settings.openai_endpoint, settings.chat_deployment, settings.reasoning_deployment, usage, cred
                )
        rt = cls(settings, features, repo, blobs, llm, usage, cred)
        return rt

    async def start(self) -> None:
        self.writer.start()
        try:
            doc = await self.repo.get("state", f"usage-{datetime.now(UTC).strftime('%Y-%m-%d')}", "usage")
            self.usage.load_doc(doc)
        except Exception as exc:  # pragma: no cover
            log.warning("could not load usage doc: %s", exc)
        self._tasks.append(asyncio.create_task(self._usage_persister(), name="usage-persister"))
        if self.fleet is not None:
            await self.fleet.start()

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        if self.fleet is not None:
            await self.fleet.stop()
        await self.writer.stop()
        try:
            await self.repo.upsert("state", self.usage.to_doc())
        except Exception:  # pragma: no cover
            pass
        for closer in (self.llm.close(), self.repo.close(), self.blobs.close()):
            try:
                await closer
            except Exception:  # pragma: no cover
                pass
        if self.credential is not None:  # pragma: no cover
            await self.credential.close()

    async def _usage_persister(self) -> None:
        while True:
            await asyncio.sleep(20)
            try:
                await self.repo.upsert("state", self.usage.to_doc())
            except Exception as exc:  # pragma: no cover
                log.warning("usage persist failed: %s", exc)

    # ------------------------------------------------------------------ meta / readiness
    def meta(self) -> dict[str, Any]:
        s = self.settings
        out = {
            "name": APP_NAME,
            "version": __version__,
            "build_id": s.build_id,
            "mode": s.mode,
            "region": s.region,
            "models": {
                "chat": self.llm.deployments.get("chat"),
                "reasoning": self.llm.deployments.get("reasoning"),
                "backend": getattr(self.llm, "endpoint", "offline-stub"),
            },
            "persistence": {
                "repository": self.repo.name,
                "blobs": self.blobs.name,
                "write_behind": self.writer.stats(),
            },
            "uptime_s": round(time.time() - self.started_at, 1),
            "synthetic_data": True,
            "disclaimer": "Simulated plant & synthetic data: no real factory, PLC or personal data is connected.",
            "ai_budget": {"daily_usd": s.daily_ai_budget_usd, "blocked": self.usage.blocked},
            "features": {
                "total": len(self.features),
                "implemented": sum(1 for f in self.features if f.spec.status == "implemented"),
            },
        }
        if self.fleet is not None:
            out["plants"] = self.fleet.summary()
        return out

    async def _check(self, name: str, fn, timeout: float = 12.0) -> dict[str, Any]:
        t = time.perf_counter()
        try:
            res = await asyncio.wait_for(fn(), timeout)
        except Exception as exc:
            return {
                "status": "fail",
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                "latency_ms": round((time.perf_counter() - t) * 1000, 1),
            }
        return res

    async def readiness(self, fresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        wanted = {"cosmos": self.repo.ping, "storage": self.blobs.ping, "openai": self.llm.ping}
        results: dict[str, dict[str, Any]] = {}
        todo: dict[str, Any] = {}
        for name, fn in wanted.items():
            cached = self._ready_cache.get(name)
            if cached and now - cached[0] < READY_TTL_S[name] and not (fresh and name != "openai"):
                results[name] = {**cached[1], "cached": True}
            else:
                todo[name] = fn
        if todo:
            outs = await asyncio.gather(*(self._check(n, f) for n, f in todo.items()))
            for (n, _), res in zip(todo.items(), outs, strict=True):
                results[n] = res
                self._ready_cache[n] = (now, res)
        ok = all(r.get("status") == "ok" for r in results.values())
        return {
            "status": "ready" if ok else "unready",
            "mode": self.settings.mode,
            "checks": results,
            "ai_budget_blocked": self.usage.blocked,
            "time": datetime.now(UTC).isoformat(),
        }
