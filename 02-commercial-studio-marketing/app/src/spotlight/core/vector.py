"""In-process vector index (numpy cosine) with persistence in the repository — AI Search is the documented scale-out path."""

from __future__ import annotations

import base64
from typing import Any

import numpy as np

from ..util import new_id, now_iso


def encode_vec(vec: list[float] | np.ndarray) -> str:
    return base64.b64encode(np.asarray(vec, dtype=np.float32).tobytes()).decode()


def decode_vec(b64: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(b64), dtype=np.float32)


def chunk_text(text: str, max_chars: int = 700, overlap: int = 80) -> list[str]:
    """Paragraph-aware chunking: split on blank lines / headings, then pack up to ``max_chars``."""
    paras = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        if len(p) > max_chars:  # hard-split very long paragraphs on sentence ends
            if cur:
                chunks.append(cur)
                cur = ""
            sentences = p.replace(". ", ".\n").split("\n")
            buf = ""
            for s in sentences:
                if len(buf) + len(s) + 1 > max_chars and buf:
                    chunks.append(buf.strip())
                    buf = buf[-overlap:] + " " + s if overlap else s
                else:
                    buf = (buf + " " + s).strip()
            if buf:
                chunks.append(buf.strip())
            continue
        if cur and len(cur) + len(p) + 2 > max_chars:
            chunks.append(cur)
            cur = p
        else:
            cur = (cur + "\n\n" + p).strip()
    if cur:
        chunks.append(cur)
    return chunks


class VectorIndex:
    def __init__(self, repo: Any, embedder: Any) -> None:
        self.repo = repo
        self.embedder = embedder
        self._cache: dict[tuple[str, str], tuple[np.ndarray, list[dict[str, Any]]]] = {}

    def invalidate(self, namespace: str) -> None:
        for k in [k for k in self._cache if k[0] == namespace]:
            del self._cache[k]

    async def add(self, namespace: str, version: str, items: list[dict[str, Any]], kind: str = "brand") -> int:
        """items: [{text, title?, source?, meta?}] -> embedded + persisted. Returns the number stored."""
        if not items:
            return 0
        vecs = await self.embedder.embed([i["text"] for i in items])
        for n, (it, vec) in enumerate(zip(items, vecs, strict=True)):
            await self.repo.upsert(
                "brand_chunks",
                {
                    "id": it.get("id") or new_id("chk"),
                    "pk": namespace,
                    "namespace": namespace,
                    "version": version,
                    "kind": kind,
                    "ord": n,
                    "text": it["text"],
                    "title": it.get("title", ""),
                    "source": it.get("source", ""),
                    "meta": it.get("meta", {}),
                    "embedding": encode_vec(vec),
                    "dim": len(vec),
                    "model": getattr(self.embedder, "mode", "?"),
                    "ts": now_iso(),
                },
            )
        self.invalidate(namespace)
        return len(items)

    async def delete_where(self, namespace: str, where: dict[str, Any]) -> int:
        rows = await self.repo.query("brand_chunks", where, pk=namespace)
        for r in rows:
            await self.repo.delete("brand_chunks", r["id"], pk=namespace)
        self.invalidate(namespace)
        return len(rows)

    async def delete_version(self, namespace: str, version: str) -> int:
        return await self.delete_where(namespace, {"version": version})

    async def _load(self, namespace: str, version: str | list[str] | None) -> tuple[np.ndarray, list[dict[str, Any]]]:
        vkey = ",".join(version) if isinstance(version, list) else (version or "*")
        key = (namespace, vkey)
        if key in self._cache:
            return self._cache[key]
        where: dict[str, Any] | None = None
        if isinstance(version, list):
            where = {"version": {"$in": version}}
        elif version:
            where = {"version": version}
        rows = await self.repo.query("brand_chunks", where, pk=namespace)
        rows = [r for r in rows if r.get("embedding")]
        if not rows:
            self._cache[key] = (np.zeros((0, 1), dtype=np.float32), [])
            return self._cache[key]
        dim = rows[0]["dim"]
        rows = [r for r in rows if r["dim"] == dim]
        mat = np.vstack([decode_vec(r["embedding"]) for r in rows]).astype(np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        mat = (mat / np.where(norms == 0, 1, norms)).astype(np.float32)
        meta = [{k: v for k, v in r.items() if k != "embedding"} for r in rows]
        self._cache[key] = (mat, meta)
        return self._cache[key]

    async def search(self, namespace: str, query: str, *, k: int = 5, version: str | list[str] | None = None, min_score: float = -1.0) -> list[dict[str, Any]]:
        mat, meta = await self._load(namespace, version)
        if not meta:
            return []
        q = np.asarray((await self.embedder.embed([query]))[0], dtype=np.float32)
        if q.shape[0] != mat.shape[1]:
            return []
        n = float(np.linalg.norm(q))
        q = q / n if n else q
        scores = mat @ q
        order = np.argsort(-scores)[:k]
        return [{**meta[i], "score": round(float(scores[i]), 4)} for i in order if scores[i] >= min_score]
