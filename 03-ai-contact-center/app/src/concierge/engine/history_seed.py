"""Idempotent seeding of the synthetic analytics history (interaction records + WFM interval volumes). Shared by VoC, QA, metrics and WFM.

Polish slice (`PL_SLICE_VERSION`): every record gains `summary_pl` (+ a Polish opening message for the PL market) and two Polish-market WFM queues are added.
A repository that was seeded before the slice existed (e.g. the deployed Cosmos DB) is UPGRADED in place - the Polish fields are merged into the stored
records and the new queue documents are upserted; nothing is cleared and `HISTORY_VERSION` (which would trigger a wipe) is not bumped.
Bump `PL_SLICE_VERSION` whenever the Polish wording of `synth_pl` changes: the stored Polish fields are then refreshed once (pl1 -> pl2: wording only)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from . import synth

HISTORY_VERSION = "h4"
PL_SLICE_VERSION = "pl2"  # pl2: reviewed Polish wording of the summaries / opening messages / topic labels (no number changed)
_lock = asyncio.Lock()


async def _bulk(svc: Any, coll: str, docs: list[dict[str, Any]], chunk: int = 50) -> None:
    for i in range(0, len(docs), chunk):
        await svc.repo.put_many(coll, docs[i : i + chunk])


async def _ensure_pl_slice(svc: Any, meta: dict[str, Any]) -> dict[str, Any] | None:
    """Merge the Polish fields into an already-seeded history (same seed + anchor -> same record ids) and upsert the Polish WFM queues."""
    if meta.get("pl_slice") == PL_SLICE_VERSION:
        return None
    anchor = meta["anchor"]
    stored = {r["id"]: r for r in await svc.repo.query("history", limit=6000)}
    patched = []
    for rec in synth.generate_history(anchor):
        old = stored.get(rec["id"])
        if old is not None:  # a version mismatch means the stored Polish fields are missing or older wording: refresh them (English fields are never touched)
            patched.append({**old, "summary_pl": rec["summary_pl"], **({"text": rec["text"]} if rec["market"] == "PL" else {})})
    await _bulk(svc, "history", patched)
    wfm_pl = synth.generate_wfm_history_pl(anchor)
    await _bulk(svc, "wfm_history", wfm_pl)
    await svc.repo.put("seed_meta", {**meta, "pl_slice": PL_SLICE_VERSION, "pl_patched_records": len(patched), "wfm_docs_pl": len(wfm_pl), "ts": time.time()})
    return {"patched_records": len(patched), "wfm_docs_pl": len(wfm_pl)}


async def seed_history(svc: Any, force: bool = False) -> dict[str, Any]:
    async with _lock:
        meta = await svc.repo.get("seed_meta", "history")
        if meta and meta.get("version") == HISTORY_VERSION and not force:
            upgraded = await _ensure_pl_slice(svc, meta)
            return {"skipped": True, **{k: meta[k] for k in ("records", "wfm_docs", "anchor")}, **({"pl_slice": upgraded} if upgraded else {})}
        anchor = synth.anchor_midnight(time.time())
        history = synth.generate_history(anchor)
        wfm = synth.generate_wfm_history(anchor)
        wfm_pl = synth.generate_wfm_history_pl(anchor)
        if meta:  # stale version or forced re-seed: do not mix anchors
            await svc.repo.clear("history")
            await svc.repo.clear("wfm_history")
        await _bulk(svc, "history", history)
        await _bulk(svc, "wfm_history", [*wfm, *wfm_pl])
        meta = {
            "id": "history", "version": HISTORY_VERSION, "pl_slice": PL_SLICE_VERSION, "anchor": anchor, "records": len(history), "wfm_docs": len(wfm), "wfm_docs_pl": len(wfm_pl),
            "sample_factor": synth.SAMPLE_FACTOR, "seed": synth.SEED,
            "planted": {"topic": "damaged_on_delivery", "carrier": synth.SPIKE_CARRIER, "days": synth.SPIKE_DAYS}, "synthetic": True, "ts": time.time(),
        }  # fmt: skip
        await svc.repo.put("seed_meta", meta)
        return {"skipped": False, "records": len(history), "wfm_docs": len(wfm), "anchor": anchor}


async def load_history(svc: Any) -> list[dict[str, Any]]:
    rows = await svc.repo.query("history", order_by="ts", limit=6000)
    return [{k: v for k, v in r.items() if k not in ("pk", "_ts", "ttl")} for r in rows]
