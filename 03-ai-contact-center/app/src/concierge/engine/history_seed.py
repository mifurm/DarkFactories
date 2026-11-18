"""Idempotent seeding of the synthetic analytics history (interaction records + WFM interval volumes). Shared by VoC, QA, metrics and WFM."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from . import synth

HISTORY_VERSION = "h4"
_lock = asyncio.Lock()


async def _bulk(svc: Any, coll: str, docs: list[dict[str, Any]], chunk: int = 50) -> None:
    for i in range(0, len(docs), chunk):
        await svc.repo.put_many(coll, docs[i : i + chunk])


async def seed_history(svc: Any, force: bool = False) -> dict[str, Any]:
    async with _lock:
        meta = await svc.repo.get("seed_meta", "history")
        if meta and meta.get("version") == HISTORY_VERSION and not force:
            return {"skipped": True, **{k: meta[k] for k in ("records", "wfm_docs", "anchor")}}
        anchor = synth.anchor_midnight(time.time())
        history = synth.generate_history(anchor)
        wfm = synth.generate_wfm_history(anchor)
        if meta:  # stale version or forced re-seed: do not mix anchors
            await svc.repo.clear("history")
            await svc.repo.clear("wfm_history")
        await _bulk(svc, "history", history)
        await _bulk(svc, "wfm_history", wfm)
        meta = {
            "id": "history", "version": HISTORY_VERSION, "anchor": anchor, "records": len(history), "wfm_docs": len(wfm), "sample_factor": synth.SAMPLE_FACTOR, "seed": synth.SEED,
            "planted": {"topic": "damaged_on_delivery", "carrier": synth.SPIKE_CARRIER, "days": synth.SPIKE_DAYS}, "synthetic": True, "ts": time.time(),
        }  # fmt: skip
        await svc.repo.put("seed_meta", meta)
        return {"skipped": False, "records": len(history), "wfm_docs": len(wfm), "anchor": anchor}


async def load_history(svc: Any) -> list[dict[str, Any]]:
    rows = await svc.repo.query("history", order_by="ts", limit=6000)
    return [{k: v for k, v in r.items() if k not in ("pk", "_ts", "ttl")} for r in rows]
