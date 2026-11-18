"""Deterministic offline embedder (hashed bag-of-words + char n-grams) and vector helpers (numpy only)."""

from __future__ import annotations

import itertools
import re
import zlib

import numpy as np

DIMS = 512
_WORD = re.compile(r"[\w'-]+", re.UNICODE)
_STOP = frozenset(
    ["a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "for", "with", "is", "are", "was", "were", "be", "been", "it", "this", "that", "these", "those", "i", "you", "we", "they", "he", "she", "my", "your", "our", "der", "die", "das", "und", "oder", "ein", "eine", "einen", "ist", "sind", "war", "mit", "für", "auf", "zu", "von", "im", "in", "le", "la", "les", "un", "une", "et", "ou", "de", "du", "des", "est", "sont", "il", "elle", "el", "los", "las", "un", "una", "y", "o", "en", "es", "que", "di", "il", "lo", "e", "per", "da"]
)


def _bucket(token: str, dims: int) -> tuple[int, float]:
    h = zlib.crc32(token.encode("utf-8"))
    return h % dims, 1.0 if (h >> 16) & 1 else -1.0


def hashed_embedding(text: str, dims: int = DIMS) -> list[float]:
    vec = np.zeros(dims, dtype=np.float64)
    tokens = [t for t in _WORD.findall(text.lower()) if t not in _STOP]
    for tok in tokens:
        idx, sign = _bucket("w:" + tok, dims)
        vec[idx] += 1.5 * sign
        padded = f"^{tok}$"
        for i in range(len(padded) - 2):
            idx, sign = _bucket("c:" + padded[i : i + 3], dims)
            vec[idx] += 0.5 * sign
    for a, b in itertools.pairwise(tokens):
        idx, sign = _bucket(f"b:{a}_{b}", dims)
        vec[idx] += 0.8 * sign
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return [round(float(x), 5) for x in vec]


def cosine(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float:
    va, vb = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    return float(va @ vb / (na * nb)) if na and nb else 0.0


def cosine_matrix(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    qn = query / (np.linalg.norm(query) or 1.0)
    mn = matrix / np.clip(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-9, None)
    return mn @ qn
