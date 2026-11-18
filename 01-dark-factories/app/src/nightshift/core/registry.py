"""Feature registry: every Release-1 feature package self-registers a FeatureSpec; routers are auto-discovered."""

from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import asdict, dataclass, field
from typing import Any

log = logging.getLogger("nightshift.registry")


@dataclass(frozen=True)
class FeatureSpec:
    id: str
    name: str
    epic: str
    priority: str
    ui_route: str
    api_prefix: str
    status: str = "planned"  # planned | implemented
    summary: str = ""
    depth: str = ""  # what is real vs simulated in this reference implementation
    tags: tuple[str, ...] = field(default_factory=tuple)

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d["tags"] = list(self.tags)
        return d


@dataclass
class LoadedFeature:
    spec: FeatureSpec
    module: str
    router: Any | None = None
    extra_routers: list[Any] = field(default_factory=list)


def discover_features() -> list[LoadedFeature]:
    """Import every ``nightshift.features.dfNN_*`` package, read ``FEATURE`` and (optionally) ``router.router``."""
    import nightshift.features as pkg

    loaded: list[LoadedFeature] = []
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda m: m.name):
        if not info.ispkg or not info.name.startswith("df"):
            continue
        mod = importlib.import_module(f"nightshift.features.{info.name}")
        spec = getattr(mod, "FEATURE", None)
        if not isinstance(spec, FeatureSpec):
            log.warning("feature package %s has no FEATURE spec", info.name)
            continue
        router = None
        extras: list[Any] = []
        try:
            rmod = importlib.import_module(f"nightshift.features.{info.name}.router")
            router = getattr(rmod, "router", None)
            extras = list(getattr(rmod, "extra_routers", []))
        except ModuleNotFoundError as exc:
            if exc.name != f"nightshift.features.{info.name}.router":
                raise
        loaded.append(LoadedFeature(spec=spec, module=info.name, router=router, extra_routers=extras))
    loaded.sort(key=lambda f: f.spec.id)
    return loaded


def feature_for_path(features: list[LoadedFeature], path: str) -> str:
    """Map a request path to the owning feature id (longest api_prefix match) for per-feature counters."""
    best, best_len = "platform", -1
    for f in features:
        p = f.spec.api_prefix
        if p and (path == p or path.startswith(p + "/")) and len(p) > best_len:
            best, best_len = f.spec.id, len(p)
    return best
