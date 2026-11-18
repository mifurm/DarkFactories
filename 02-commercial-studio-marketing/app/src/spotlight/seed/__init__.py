"""Idempotent seed loader (+ demo reset)."""

from __future__ import annotations

from typing import Any

from ..core.vector import chunk_text
from ..util import now_iso
from . import data

RESET_COLLECTIONS = ("artifacts", "assets", "reports", "approvals", "audit", "provenance", "experiments", "performance", "jobs", "plans", "collections", "learnings", "webhooks")


def kit_chunks(kit: dict[str, Any], name: str) -> list[dict[str, Any]]:
    """Structured brand-kit facts as retrievable passages (so agents can cite 'Brand kit · Voice')."""
    v = kit.get("voice", {})
    out = [
        ("Voice & tone", f"Tone: {', '.join(v.get('tone', []))}. Do: {'; '.join(v.get('dos', []))}. Do not: {'; '.join(v.get('donts', []))}. Forbidden words: {', '.join(v.get('forbidden_words', []))}."),
        ("Palette & typography", "Palette: " + "; ".join(f"{p['name']} {p['hex']} ({p.get('role', '')})" for p in kit.get("palette", [])) + f". Typography: {kit.get('typography', {})}."),
        ("Logo rules", f"Logo: {kit.get('logo', {})}"),
        ("Products", " ".join(f"{p['name']}: {p['description']}" for p in kit.get("products", []))),
        ("Personas", " ".join(f"{p['name']} — needs: {p.get('needs', '')}." for p in kit.get("personas", []))),
        ("Tagline & markets", f"Tagline: {kit.get('tagline', '')}. Markets: {', '.join(kit.get('markets', []))}. Category: {kit.get('category', '')}."),
    ]
    return [{"id": f"kit-{i}", "text": f"{name} — {title}. {text}", "title": f"Brand kit · {title}", "source": "Brand kit", "meta": {"section": title}} for i, (title, text) in enumerate(out)]


async def seed_brand(svc: Any) -> int:
    """Create the Northwind brand kit v1 + embed the brand book and kit facts into the vector index."""
    repo = svc.repo
    now = now_iso()
    await repo.upsert("brands", {"id": data.BRAND_ID, "pk": data.BRAND_ID, "brand_id": data.BRAND_ID, "type": "brand", "name": "Northwind Coffee Roasters", "active_version": 1, "category": "beverage", "synthetic": True, "created_at": now})
    await repo.upsert("brands", {"id": f"{data.BRAND_ID}@1", "pk": data.BRAND_ID, "brand_id": data.BRAND_ID, "type": "brand_version", "version": 1, "kit": data.KIT, "note": "Initial synthetic kit", "author": "seed", "created_at": now})
    await repo.upsert("brands", {"id": "doc-brand-book", "pk": data.BRAND_ID, "brand_id": data.BRAND_ID, "type": "brand_doc", "name": "Northwind Brand Book (sample).md", "text": data.GUIDELINES_MD, "chars": len(data.GUIDELINES_MD), "quarantined": False, "created_at": now})
    await svc.vectors.delete_where(data.BRAND_ID, {"version": "docs"})
    await svc.vectors.delete_where(data.BRAND_ID, {"version": "kit-1"})
    items = []
    for n, ch in enumerate(chunk_text(data.GUIDELINES_MD, 650)):
        title = ch.split("\n", 1)[0].lstrip("# ").strip()[:60] if ch.startswith("#") else "Brand Book"
        items.append({"id": f"doc-brand-book-{n:02d}", "text": ch, "title": title, "source": "Northwind Brand Book (sample).md", "meta": {"doc_id": "doc-brand-book", "n": n}})
    n_docs = await svc.vectors.add(data.BRAND_ID, "docs", items, kind="document")
    n_kit = await svc.vectors.add(data.BRAND_ID, "kit-1", kit_chunks(data.KIT, "Northwind Coffee Roasters"), kind="kit")
    return n_docs + n_kit


async def ensure_seeded(svc: Any, force: bool = False) -> dict[str, Any]:
    repo = svc.repo
    state = await repo.get("settings", "seed_state", pk="tenant")
    if state and state.get("version") == data.SEED_VERSION and not force:
        return {"seeded": False, "version": state["version"]}
    chunks = await seed_brand(svc)
    for c in data.claims():
        await repo.upsert("claims", c)
    for r in data.rights():
        await repo.upsert("rights", r)
    for camp in data.campaigns():
        if force or not await repo.get("campaigns", camp["id"], pk=camp["id"]):
            await repo.upsert("campaigns", camp)
    await repo.upsert("settings", {"id": "seed_state", "pk": "tenant", "version": data.SEED_VERSION, "at": now_iso(), "chunks": chunks})
    return {"seeded": True, "version": data.SEED_VERSION, "chunks": chunks}


async def reset_demo(svc: Any) -> dict[str, Any]:
    """Wipe generated demo state (artifacts, assets, reports, approvals, audit, experiments…) and reseed."""
    repo = svc.repo
    removed: dict[str, int] = {}
    for coll in RESET_COLLECTIONS:
        rows = await repo.query(coll)
        for r in rows:
            await repo.delete(coll, r["id"], pk=r.get("pk"))
        removed[coll] = len(rows)
    for c in await repo.query("campaigns"):
        await repo.delete("campaigns", c["id"], pk=c.get("pk"))
    for b in await svc.blobs.list("campaigns/"):
        await svc.blobs.delete(b.path)
    for chunk in await repo.query("brand_chunks", {"kind": "asset"}):
        await repo.delete("brand_chunks", chunk["id"], pk=chunk.get("pk"))
    svc.vectors.invalidate("library")
    await repo.delete("settings", "seed_state", pk="tenant")
    res = await ensure_seeded(svc, force=True)
    for hook in svc.extras.get("reseed_hooks", []):
        await hook(svc)
    return {"removed": removed, **res}
