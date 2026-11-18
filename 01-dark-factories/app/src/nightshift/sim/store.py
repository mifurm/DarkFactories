"""Ring-buffer time-series store: one shared timeline, one row of values per tick (vectorised writes, cheap forks)."""

from __future__ import annotations

from typing import Any

import numpy as np


class TimeSeriesStore:
    def __init__(self, keys: list[tuple[str, str]], capacity: int = 1440) -> None:
        self.keys = list(keys)
        self.index = {k: i for i, k in enumerate(self.keys)}
        self.cap = capacity
        self.data = np.full((len(self.keys), capacity), np.nan, dtype=np.float32)
        self.n = 0  # ticks pushed so far (== sim minutes elapsed)

    def push(self, row: list[float] | np.ndarray) -> None:
        self.data[:, self.n % self.cap] = row
        self.n += 1

    def has(self, asset: str, metric: str) -> bool:
        return (asset, metric) in self.index

    def series(self, asset: str, metric: str, n: int = 60) -> np.ndarray:
        """Last ``n`` samples (chronological; NaN = no sample that minute)."""
        n = max(0, min(n, self.n, self.cap))
        i = self.index[(asset, metric)]
        idx = np.arange(self.n - n, self.n) % self.cap
        return self.data[i, idx]

    def latest(self, asset: str, metric: str) -> float:
        if self.n == 0:
            return float("nan")
        return float(self.data[self.index[(asset, metric)], (self.n - 1) % self.cap])

    def aggregates(self, asset: str, metric: str, bucket: int = 15, buckets: int = 24) -> list[dict[str, Any]]:
        """Downsample the tail of a series into fixed buckets (mean/min/max/count) for UI, persistence and reports."""
        s = self.series(asset, metric, bucket * buckets)
        if s.size == 0:
            return []
        start_tick = self.n - s.size
        out: list[dict[str, Any]] = []
        for k in range(0, s.size, bucket):
            chunk = s[k : k + bucket]
            ok = chunk[~np.isnan(chunk)]
            out.append(
                {
                    "t": int(start_tick + k),
                    "mean": float(ok.mean()) if ok.size else None,
                    "min": float(ok.min()) if ok.size else None,
                    "max": float(ok.max()) if ok.size else None,
                    "count": int(ok.size),
                }
            )
        return out
