"""Feature registry (auto-discovery) and the in-process event bus used for live consoles / widgets."""

from __future__ import annotations

import asyncio
import importlib
import pkgutil
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from typing import Any

from fastapi import APIRouter

EPIC_A = "A — Conversational AI agents"
EPIC_B = "B — Routing & human collaboration"
EPIC_C = "C — Quality, compliance, insight"
EPIC_D = "D — Operations & LLMOps"
EPIC_E = "E — Platform"


@dataclass
class FeatureInfo:
    id: str
    name: str
    epic: str
    priority: str
    ui_route: str
    api_prefix: str
    summary: str = ""
    status: str = "implemented"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FeatureRegistry:
    features: dict[str, FeatureInfo] = field(default_factory=dict)
    modules: dict[str, str] = field(default_factory=dict)
    routers: list[tuple[str, APIRouter]] = field(default_factory=list)
    seeders: list[tuple[int, str, Any]] = field(default_factory=list)
    startups: list[tuple[str, Any]] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    def register_module(self, mod_name: str, mod: Any) -> None:
        for f in getattr(mod, "FEATURES", []):
            self.features[f.id] = f
            self.modules[f.id] = mod_name
        router = getattr(mod, "router", None)
        if router is not None:
            self.routers.append((mod_name, router))
        seed = getattr(mod, "seed", None)
        if seed is not None:
            self.seeders.append((getattr(mod, "SEED_ORDER", 50), mod_name, seed))
        startup = getattr(mod, "startup", None)
        if startup is not None:
            self.startups.append((mod_name, startup))

    def listing(self) -> list[dict[str, Any]]:
        return [f.to_dict() | {"module": self.modules.get(f.id, "")} for f in sorted(self.features.values(), key=lambda x: x.id)]


def discover_features(package: str = "concierge.features") -> FeatureRegistry:
    """Import every feature package under concierge/features and register its FEATURES / router / seed / startup."""
    reg = FeatureRegistry()
    pkg = importlib.import_module(package)
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{package}.{info.name}")
            reg.register_module(info.name, mod)
        except Exception as exc:  # pragma: no cover - surfaced via /api/features diagnostics
            reg.errors[info.name] = f"{type(exc).__name__}: {exc}"
            raise
    reg.seeders.sort(key=lambda t: t[0])
    return reg


class Subscription:
    def __init__(self, bus: EventBus, topics: set[str]) -> None:
        self.bus = bus
        self.topics = topics
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)

    async def get(self, timeout: float | None = None) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(self.queue.get(), timeout)
        except TimeoutError:
            return None

    def close(self) -> None:
        self.bus.unsubscribe(self)


class EventBus:
    """Topic pub/sub with a short replay buffer. In-process (single replica); scale-out path = Azure Web PubSub / Service Bus."""

    def __init__(self, replay: int = 50) -> None:
        self._subs: dict[str, set[Subscription]] = defaultdict(set)
        self._history: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=replay))
        self.published = 0

    def subscribe(self, topics: list[str] | set[str], replay: bool = False) -> Subscription:
        sub = Subscription(self, set(topics))
        for t in sub.topics:
            self._subs[t].add(sub)
            if replay:
                for ev in self._history[t]:
                    sub.queue.put_nowait(ev)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        for t in sub.topics:
            self._subs[t].discard(sub)

    async def publish(self, topic: str, event: dict[str, Any]) -> None:
        ev = {"topic": topic, "ts": time.time(), **event}
        self._history[topic].append(ev)
        self.published += 1
        for sub in list(self._subs.get(topic, ())):
            if sub.queue.full():
                try:
                    sub.queue.get_nowait()
                except asyncio.QueueEmpty:  # pragma: no cover
                    pass
            sub.queue.put_nowait(ev)

    def recent(self, topic: str) -> list[dict[str, Any]]:
        return list(self._history[topic])

    def subscriber_count(self) -> int:
        return sum(len(s) for s in self._subs.values())
