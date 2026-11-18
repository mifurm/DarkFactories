"""Idempotent seed loader (+ demo reset).

Seeding only ever *upserts* deterministic ids — it never wipes: user-uploaded Brand Brain documents and their embeddings, kit versions
created after v1, learnings, artifacts, … survive a reseed (``SEED_VERSION`` bumps re-run it once on the already-deployed data).
"""

from __future__ import annotations

from typing import Any

from ..core.vector import chunk_text
from ..i18n.fmt import fmt_number
from ..util import now_iso
from . import data

RESET_COLLECTIONS = ("artifacts", "assets", "reports", "approvals", "audit", "provenance", "experiments", "performance", "jobs", "plans", "collections", "learnings", "webhooks")

# (doc id, display name, text, language) — the two Brand Books of the sample brand
BRAND_DOCS: list[tuple[str, str, str, str]] = [
    ("doc-brand-book", "Northwind Brand Book (sample).md", data.GUIDELINES_MD, "en"),
    ("doc-brand-book-pl", "Northwind — Księga marki (przykład).md", data.GUIDELINES_MD_PL, "pl"),
]


def kit_chunks(kit: dict[str, Any], name: str, lang: str = "en", version: int = 1) -> list[dict[str, Any]]:
    """Structured brand-kit facts as retrievable passages (so agents can cite 'Brand kit · Voice')."""
    if lang != "en":
        return _kit_chunks_pl(kit, name, version) if lang == "pl" else []
    v = kit.get("voice", {})
    out = [
        ("Voice & tone", f"Tone: {', '.join(v.get('tone', []))}. Do: {'; '.join(v.get('dos', []))}. Do not: {'; '.join(v.get('donts', []))}. Forbidden words: {', '.join(v.get('forbidden_words', []))}."),
        ("Palette & typography", "Palette: " + "; ".join(f"{p['name']} {p['hex']} ({p.get('role', '')})" for p in kit.get("palette", [])) + f". Typography: {kit.get('typography', {})}."),
        ("Logo rules", f"Logo: {kit.get('logo', {})}"),
        ("Products", " ".join(f"{p['name']}: {p['description']}" for p in kit.get("products", []))),
        ("Personas", " ".join(f"{p['name']} — needs: {p.get('needs', '')}." for p in kit.get("personas", []))),
        ("Tagline & markets", f"Tagline: {kit.get('tagline', '')}. Markets: {', '.join(kit.get('markets', []))}. Category: {kit.get('category', '')}."),
    ]
    return [{"id": f"kit-{i}", "text": f"{name} — {title}. {text}", "title": f"Brand kit · {title}", "source": "Brand kit", "meta": {"section": title}, "lang": "en"} for i, (title, text) in enumerate(out)]


def _lc(text: str) -> str:
    """Lower-case the first letter of an imperative list item so it reads as a continuation after a label ("…; pokaż produkt")."""
    return text[:1].lower() + text[1:] if text[:1].isalpha() and not text[:2].isupper() else text


def _kit_chunks_pl(kit: dict[str, Any], name: str, version: int) -> list[dict[str, Any]]:
    pl = (kit.get("i18n") or {}).get("pl")
    if not pl:
        return []
    v = pl.get("voice", {})
    logo = kit.get("logo", {})
    typo = kit.get("typography", {})

    def font(spec: str) -> str:
        return spec.replace("(serif)", "(szeryfowa)").replace("(sans-serif)", "(bezszeryfowa)")

    def colour(p: dict[str, Any]) -> str:
        pl_name, pl_role = data.PALETTE_PL.get(p["name"], (p["name"], p.get("role", "")))
        return f"{pl_name} {p['hex']}" + (f" ({pl_role})" if pl_role else "")

    category = {"beverage": "napoje"}.get(str(kit.get("category", "")), str(kit.get("category", "")))
    out = [
        ("Głos i ton", f"Ton: {', '.join(v.get('tone', []))}. Zalecenia: {'; '.join(_lc(x) for x in v.get('dos', []))}. Czego unikać: {'; '.join(_lc(x) for x in v.get('donts', []))}. Zakazane słowa: {', '.join(v.get('forbidden_words', []))}. {pl.get('register_note', '')}"),
        ("Paleta i typografia", "Paleta: " + "; ".join(colour(p) for p in kit.get("palette", [])) + f". Typografia: nagłówki — {font(str(typo.get('display', '')))}, tekst — {font(str(typo.get('body', '')))}."),
        ("Zasady logo", f"Logo: napis {logo.get('wordmark', '')}, minimum {fmt_number(logo.get('min_width_pct', 12), 'pl')}% szerokości kadru, pole ochronne równe połowie wysokości logo."),
        ("Produkty", " ".join(f"{p['name']}: {p['description']}" for p in pl.get("products", []))),
        ("Odbiorcy", " ".join(f"{p['name']} — potrzeba: {p.get('needs', '')}." for p in pl.get("personas", []))),
        ("Hasło i rynki", f"Hasło marki: „{pl.get('tagline', '')}” Rynki: {', '.join(kit.get('markets', []))}. Kategoria: {category}."),
        ("Pochodzenie i zrównoważony rozwój", str(pl.get("sourcing", ""))),
    ]
    return [{"id": f"kit-v{version}-pl-{i}", "text": f"{name} — {title}. {text}", "title": f"Zestaw marki · {title}", "source": "Zestaw marki", "meta": {"section": title}, "lang": "pl"} for i, (title, text) in enumerate(out)]


async def _index_docs(svc: Any) -> int:
    """(Re-)embed the sample Brand Books. Only their own chunks are replaced — uploaded documents keep their embeddings."""
    n = 0
    for doc_id, name, text, lang in BRAND_DOCS:
        await svc.vectors.delete_where(data.BRAND_ID, {"meta.doc_id": doc_id})
        items = []
        for i, ch in enumerate(chunk_text(text, 650)):
            title = ch.split("\n", 1)[0].lstrip("# ").strip()[:60] if ch.startswith("#") else ("Księga marki" if lang == "pl" else "Brand Book")
            items.append({"id": f"{doc_id}-{i:02d}", "text": ch, "title": title, "source": name, "meta": {"doc_id": doc_id, "n": i}, "lang": lang})
        n += await svc.vectors.add(data.BRAND_ID, "docs", items, kind="document")
    return n


async def seed_brand(svc: Any) -> int:
    """Create / refresh the Northwind brand kit v1 (+ Polish overlay) and embed the brand books and kit facts. Never deletes user content."""
    repo = svc.repo
    now = now_iso()
    root = await repo.get("brands", data.BRAND_ID, pk=data.BRAND_ID) or {}
    active = int(root.get("active_version", 1))
    await repo.upsert("brands", {**root, "id": data.BRAND_ID, "pk": data.BRAND_ID, "brand_id": data.BRAND_ID, "type": "brand", "name": "Northwind Coffee Roasters", "active_version": active, "category": "beverage", "synthetic": True, "created_at": root.get("created_at", now)})
    v1 = await repo.get("brands", f"{data.BRAND_ID}@1", pk=data.BRAND_ID) or {}
    await repo.upsert("brands", {"id": f"{data.BRAND_ID}@1", "pk": data.BRAND_ID, "brand_id": data.BRAND_ID, "type": "brand_version", "version": 1, "kit": data.KIT, "note": "Initial synthetic kit", "author": "seed", "created_at": v1.get("created_at", now)})
    if active != 1:  # a user-edited kit is active: give it the Polish overlay too (without touching anything else)
        cur = await repo.get("brands", f"{data.BRAND_ID}@{active}", pk=data.BRAND_ID)
        if cur and "pl" not in (cur.get("kit", {}).get("i18n") or {}):
            await repo.upsert("brands", {**cur, "kit": {**cur["kit"], "i18n": {**(cur["kit"].get("i18n") or {}), **data.KIT["i18n"]}}})
    for doc_id, name, text, lang in BRAND_DOCS:
        prev = await repo.get("brands", doc_id, pk=data.BRAND_ID) or {}
        await repo.upsert("brands", {"id": doc_id, "pk": data.BRAND_ID, "brand_id": data.BRAND_ID, "type": "brand_doc", "name": name, "text": text, "chars": len(text), "lang": lang, "quarantined": False, "created_at": prev.get("created_at", now)})
    n_docs = await _index_docs(svc)
    n_kit = 0
    for version in sorted({1, active}):
        kit_doc = await repo.get("brands", f"{data.BRAND_ID}@{version}", pk=data.BRAND_ID)
        kit = (kit_doc or {}).get("kit", data.KIT)
        await svc.vectors.delete_where(data.BRAND_ID, {"version": f"kit-{version}"})
        n_kit += await svc.vectors.add(data.BRAND_ID, f"kit-{version}", [*kit_chunks(kit, "Northwind Coffee Roasters"), *kit_chunks(kit, "Northwind Coffee Roasters", "pl", version)], kind="kit")
    return n_docs + n_kit


async def ensure_seeded(svc: Any, force: bool = False) -> dict[str, Any]:
    repo = svc.repo
    state = await repo.get("settings", "seed_state", pk="tenant")
    if state and state.get("version") == data.SEED_VERSION and not force:
        return {"seeded": False, "version": state["version"]}
    chunks = await seed_brand(svc)
    claims = data.all_claims()
    for c in claims:
        await repo.upsert("claims", c)
    for r in data.all_rights():
        await repo.upsert("rights", r)
    for camp in [*data.campaigns(), *data.campaigns_pl()]:
        existing = await repo.get("campaigns", camp["id"], pk=camp["id"])
        if force or not existing:
            await repo.upsert("campaigns", camp)
        elif not existing.get("language"):  # campaigns seeded before content languages existed: tag them, keep their progress
            await repo.upsert("campaigns", {**existing, "language": camp.get("language", "en")})
    await repo.upsert("settings", {"id": "seed_state", "pk": "tenant", "version": data.SEED_VERSION, "at": now_iso(), "chunks": chunks, "claims": len(claims)})
    return {"seeded": True, "version": data.SEED_VERSION, "chunks": chunks, "claims": len(claims)}


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
