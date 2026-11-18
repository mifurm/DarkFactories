"""Anomaly detection and prognostics primitives for the Predictive Maintenance agent (DF-05)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

EULER = 0.5772156649


def _c(n: int) -> float:
    """Average path length of an unsuccessful BST search (isolation forest normaliser)."""
    if n <= 1:
        return 0.0
    return 2.0 * (math.log(n - 1) + EULER) - 2.0 * (n - 1) / n


class IsolationForest:
    """Minimal isolation forest (Liu et al.) - numpy only, deterministic given the seed."""

    def __init__(self, n_trees: int = 40, sample: int = 64, seed: int = 0) -> None:
        self.n_trees, self.sample = n_trees, sample
        self.rng = np.random.default_rng(seed)
        self.trees: list[Any] = []
        self.n = 0

    def _build(self, X: np.ndarray, depth: int, limit: int) -> Any:
        if depth >= limit or len(X) <= 1:
            return ("leaf", len(X))
        q = int(self.rng.integers(0, X.shape[1]))
        lo, hi = float(X[:, q].min()), float(X[:, q].max())
        if hi - lo < 1e-12:
            return ("leaf", len(X))
        p = float(self.rng.uniform(lo, hi))
        mask = X[:, q] < p
        return ("node", q, p, self._build(X[mask], depth + 1, limit), self._build(X[~mask], depth + 1, limit))

    def fit(self, X: np.ndarray) -> IsolationForest:
        X = np.asarray(X, dtype=float)
        self.n = min(self.sample, len(X))
        limit = int(math.ceil(math.log2(max(self.n, 2))))
        self.trees = []
        for _ in range(self.n_trees):
            idx = self.rng.choice(len(X), size=self.n, replace=False)
            self.trees.append(self._build(X[idx], 0, limit))
        return self

    def _path(self, x: np.ndarray, node: Any, depth: int = 0) -> float:
        while node[0] == "node":
            node = node[3] if x[node[1]] < node[2] else node[4]
            depth += 1
        return depth + _c(node[1])

    def score(self, X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(np.asarray(X, dtype=float))
        cn = _c(self.n) or 1.0
        out = np.empty(len(X))
        for i, x in enumerate(X):
            out[i] = 2.0 ** (-(sum(self._path(x, t) for t in self.trees) / len(self.trees)) / cn)
        return out


def robust_stats(x: np.ndarray) -> tuple[float, float]:
    """Median and MAD-based sigma (1.4826 * MAD)."""
    x = x[~np.isnan(x)]
    if x.size == 0:
        return 0.0, 1.0
    med = float(np.median(x))
    return med, float(1.4826 * np.median(np.abs(x - med)))


def theil_sen(t: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Robust slope with an empirical 10-90 % band from the pairwise slopes."""
    n = len(t)
    if n < 3:
        return 0.0, 0.0, 0.0
    i, j = np.triu_indices(n, k=1)
    dt = t[j] - t[i]
    ok = dt > 0
    s = (y[j] - y[i])[ok] / dt[ok]
    if s.size == 0:
        return 0.0, 0.0, 0.0
    return float(np.median(s)), float(np.percentile(s, 10)), float(np.percentile(s, 90))


@dataclass
class Signature:
    """Failure signature: direction of the residual vector across [vibration, temperature, load, pressure] in z-units."""

    name: str
    vector: tuple[float, float, float, float]
    description: str
    source: str = "library"  # library | learned:<plant>
    model: dict[str, float] = field(default_factory=dict)
    actionable: bool = True

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "vector": list(self.vector),
            "description": self.description,
            "source": self.source,
            "model": self.model,
            "actionable": self.actionable,
        }


DEFAULT_SIGNATURES = [
    Signature(
        "bearing_wear",
        (1.0, 0.7, 0.15, 0.0),
        "Vibration energy and bearing temperature grow together (damage^2 / damage^1.5).",
        "library",
        {"vib_k": 6.0, "temp_k": 20.0, "temp_exp": 1.5, "d0": 0.11},
    ),
    Signature(
        "tool_wear",
        (0.15, 0.25, 1.0, 0.0),
        "Spindle/drive load rises with little vibration; dimensions drift.",
        "library",
        actionable=False,
    ),
    Signature(
        "thermal_drift",
        (0.1, 1.0, 0.1, 0.0),
        "Temperature rises on its own; process mean drifts.",
        "library",
        actionable=False,
    ),
    Signature("hydraulic_leak", (0.2, 0.1, 0.0, -1.0), "Hydraulic pressure sags under load.", "library", {"d0": 0.11}),
]


def match_signatures(z: tuple[float, float, float, float], library: list[Signature]) -> list[tuple[Signature, float]]:
    v = np.asarray(z, dtype=float)
    nv = float(np.linalg.norm(v))
    out = []
    for s in library:
        sv = np.asarray(s.vector, dtype=float)
        sim = float(np.dot(v, sv) / (nv * np.linalg.norm(sv))) if nv > 1e-9 else 0.0
        out.append((s, sim))
    return sorted(out, key=lambda x: -x[1])


class SignatureLibrary:
    def __init__(self) -> None:
        self.items: list[Signature] = list(DEFAULT_SIGNATURES)

    def add(self, sig: Signature) -> bool:
        if any(s.name == sig.name and s.source == sig.source for s in self.items):
            return False
        self.items.append(sig)
        return True

    def public(self) -> list[dict[str, Any]]:
        return [s.public() for s in self.items]
