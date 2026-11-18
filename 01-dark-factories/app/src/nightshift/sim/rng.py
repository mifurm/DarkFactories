"""Deterministic random streams: fixed number of variates per tick, so arms of a replay stay aligned (common random numbers)."""

from __future__ import annotations

import zlib

import numpy as np

BLOCK = 256
NORMALS = 6
UNIFORMS = 2


def stable_hash(key: str) -> int:
    return zlib.crc32(key.encode("utf-8")) & 0xFFFFFFFF


class Stream:
    """One seeded generator per asset/stream; ``next()`` always consumes exactly one row (6 normals + 2 uniforms)."""

    __slots__ = ("rng", "nrm", "uni", "i")

    def __init__(self, seed: int, key: str) -> None:
        ss = np.random.SeedSequence([seed & 0xFFFFFFFF, stable_hash(key)])
        self.rng = np.random.Generator(np.random.PCG64(ss))
        self.nrm = np.empty((BLOCK, NORMALS))
        self.uni = np.empty((BLOCK, UNIFORMS))
        self.i = BLOCK

    def _refill(self) -> None:
        self.nrm = self.rng.standard_normal((BLOCK, NORMALS))
        self.uni = self.rng.random((BLOCK, UNIFORMS))
        self.i = 0

    def next(self) -> tuple[list[float], list[float]]:
        if self.i >= BLOCK:
            self._refill()
        n = self.nrm[self.i].tolist()
        u = self.uni[self.i].tolist()
        self.i += 1
        return n, u


class Streams:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._s: dict[str, Stream] = {}

    def get(self, key: str) -> Stream:
        s = self._s.get(key)
        if s is None:
            s = self._s[key] = Stream(self.seed, key)
        return s

    def generator(self, key: str) -> np.random.Generator:
        """Independent generator for event-driven draws (order attributes, fault schedules, chaos)."""
        return self.get("gen:" + key).rng
