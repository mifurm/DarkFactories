"""CS-01 Brand Kit & Brand Brain — ingest guidelines, kit versioning, embeddings + cited retrieval, learnings."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, Field

from ...core.ai.stubs import stub_task
from ...core.vector import chunk_text
from ...deps import mutate_limit, spend_limit, svc
from ...domain.ingest import extract_text
from ...errors import NotFound, PayloadTooLarge, ValidationFailed
from ...registry import Feature
from ...roles import Actor, require
from ...seed import kit_chunks
from ...util import new_id, now_iso
from ..common import CREW_PREAMBLE, studio, untrusted

router = APIRouter(prefix="/api/brand", tags=["CS-01 Brand Brain"])
DEFAULT_BRAND = "northwind"


class VoiceProfileOut(BaseModel):
    tone: list[str]
    dos: list[str]
    donts: list[str]
    forbidden_words: list[str]
    summary: str


@stub_task("brand.voice_profile")
def _stub_voice_profile(ctx: dict[str, Any]) -> dict[str, Any]:
    text = ctx.get("text", "")
    sents = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
    donts = [s for s in sents if any(k in s.lower() for k in ("never", "do not", "don't", "no "))][:5]
    dos = [s for s in sents if s.lower().startswith(("do:", "we ", "lead", "use ")) or "we sound" in s.lower()][:5]
    forb = ["cheap", "miracle", "detox"] if "cheap" in text.lower() else []
    return {"tone": ["warm", "unhurried", "honest"], "dos": dos or ["Lead with a human moment"], "donts": donts or ["No hype"], "forbidden_words": forb, "summary": "Voice profile derived from the ingested guidelines (offline heuristic)."}


async def _brand(request: Request, brand_id: str) -> dict[str, Any]:
    return await studio(request).brand_kit(brand_id)


@router.get("")
async def overview(request: Request, brand_id: str = DEFAULT_BRAND) -> dict[str, Any]:
    st = studio(request)
    b, docs, versions, learnings, chunks = await asyncio.gather(
        st.brand_kit(brand_id),
        st.repo.query("brands", {"type": "brand_doc"}, pk=brand_id),
        st.repo.query("brands", {"type": "brand_version"}, pk=brand_id, order_by="version", desc=True),
        st.repo.count("learnings", pk=brand_id),
        st.repo.count("brand_chunks", pk=brand_id),
    )
    return {
        "id": b["id"],
        "name": b["name"],
        "active_version": b["active_version"],
        "kit": b["kit"],
        "documents": [{k: v for k, v in d.items() if k != "text"} | {"preview": d["text"][:280]} for d in docs],
        "versions": [{"version": v["version"], "created_at": v["created_at"], "author": v.get("author"), "note": v.get("note")} for v in versions],
        "counts": {"documents": len(docs), "chunks": chunks, "learnings": learnings},
        "synthetic": b.get("synthetic", True),
    }


@router.get("/search")
async def search(request: Request, q: str, brand_id: str = DEFAULT_BRAND, k: int = 5) -> dict[str, Any]:
    st = studio(request)
    ctx = await st.brand_context(brand_id, q[:500], k=min(max(k, 1), 12))
    return {"query": q, "hits": ctx["citations"], "learnings": ctx["learnings"]}


class KitUpdate(BaseModel):
    note: str = Field(default="Updated brand kit", max_length=200)
    tagline: str | None = None
    palette: list[dict[str, Any]] | None = None
    typography: dict[str, Any] | None = None
    logo: dict[str, Any] | None = None
    voice: dict[str, Any] | None = None
    products: list[dict[str, Any]] | None = None
    personas: list[dict[str, Any]] | None = None
    markets: list[str] | None = None


def _validate_kit(kit: dict[str, Any]) -> None:
    for p in kit.get("palette", []):
        hx = str(p.get("hex", ""))
        if not (len(hx) == 7 and hx.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in hx[1:])):
            raise ValidationFailed(f"invalid palette colour {hx!r} (use #RRGGBB)", code="bad_palette")
    logo = kit.get("logo", {})
    if not 1 <= float(logo.get("min_width_pct", 12)) <= 60:
        raise ValidationFailed("logo.min_width_pct must be between 1 and 60", code="bad_logo")


@router.put("/kit", dependencies=[Depends(mutate_limit)])
async def update_kit(request: Request, body: KitUpdate, brand_id: str = DEFAULT_BRAND, actor: Actor = Depends(require("brand.write"))) -> dict[str, Any]:
    st = studio(request)
    b = await st.brand_kit(brand_id)
    kit = dict(b["kit"])
    for k, v in body.model_dump(exclude={"note"}, exclude_none=True).items():
        kit[k] = v
    _validate_kit(kit)
    nv = b["active_version"] + 1
    existing = await st.repo.query("brands", {"type": "brand_version"}, pk=brand_id)
    nv = max([x["version"] for x in existing] + [b["active_version"]]) + 1
    await st.repo.upsert("brands", {"id": f"{brand_id}@{nv}", "pk": brand_id, "brand_id": brand_id, "type": "brand_version", "version": nv, "kit": kit, "note": body.note, "author": actor.name, "created_at": now_iso()})
    await svc(request).vectors.add(brand_id, f"kit-{nv}", kit_chunks(kit, b["name"]), kind="kit")
    root = await st.brand(brand_id)
    root["active_version"] = nv
    await st.repo.upsert("brands", root)
    await st.audit(None, actor, "brand.kit_updated", {"brand_id": brand_id}, {"version": nv, "note": body.note})
    return {"active_version": nv, "kit": kit}


@router.post("/versions/{version}/activate", dependencies=[Depends(mutate_limit)])
async def activate_version(request: Request, version: int, brand_id: str = DEFAULT_BRAND, actor: Actor = Depends(require("brand.write"))) -> dict[str, Any]:
    st = studio(request)
    v = await st.repo.get("brands", f"{brand_id}@{version}", pk=brand_id)
    if not v:
        raise NotFound(f"brand version {version} not found", code="version_not_found")
    root = await st.brand(brand_id)
    root["active_version"] = version
    await st.repo.upsert("brands", root)
    await st.audit(None, actor, "brand.version_activated", {"brand_id": brand_id}, {"version": version})
    return {"active_version": version}


async def _index_document(request: Request, brand_id: str, doc_id: str, name: str, text: str) -> int:
    s = svc(request)
    items = [{"id": f"{doc_id}-{n:02d}", "text": ch, "title": (ch.split("\n", 1)[0].lstrip("# ").strip()[:60] if ch.startswith("#") else name), "source": name, "meta": {"doc_id": doc_id, "n": n}} for n, ch in enumerate(chunk_text(text, 650))]
    return await s.vectors.add(brand_id, "docs", items, kind="document")


@router.post("/ingest", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def ingest(
    request: Request,
    file: UploadFile | None = File(default=None),
    name: str = Form(default=""),
    text: str = Form(default=""),
    brand_id: str = Form(default=DEFAULT_BRAND),
    actor: Actor = Depends(require("brand.write")),
) -> dict[str, Any]:
    s = svc(request)
    st = studio(request)
    if file is not None:
        data = await file.read(s.settings.max_upload_bytes + 1)
        if len(data) > s.settings.max_upload_bytes:
            raise PayloadTooLarge(f"upload exceeds {s.settings.max_upload_bytes} bytes")
        fname = file.filename or "document.txt"
        content = extract_text(fname, data)
    else:
        fname = name or "pasted-guidelines.md"
        content = text
    content = content.strip()
    if len(content) < 40:
        raise ValidationFailed("document is empty or too short to ingest", code="empty_document")
    content = content[:300_000]
    attack = await s.safety.shield_prompt(content[:9000])
    doc_id = new_id("doc")
    doc = {"id": doc_id, "pk": brand_id, "brand_id": brand_id, "type": "brand_doc", "name": fname, "text": content, "chars": len(content), "quarantined": bool(attack), "created_at": now_iso(), "created_by": actor.name}
    if attack:
        await st.repo.upsert("brands", doc)
        await st.audit(None, actor, "brand.document_quarantined", {"doc_id": doc_id}, {"reason": "prompt-injection detected"})
        raise ValidationFailed("The document contains instructions aimed at the AI (prompt injection) and was quarantined, not indexed.", code="prompt_injection", hint="Remove embedded instructions and re-upload.", details={"doc_id": doc_id})
    n = await _index_document(request, brand_id, doc_id, fname, content)
    doc["chunk_count"] = n
    await st.repo.upsert("brands", doc)
    await st.audit(None, actor, "brand.document_ingested", {"doc_id": doc_id}, {"name": fname, "chunks": n})
    return {"id": doc_id, "name": fname, "chars": len(content), "chunks": n}


@router.delete("/documents/{doc_id}", dependencies=[Depends(mutate_limit)])
async def delete_document(request: Request, doc_id: str, brand_id: str = DEFAULT_BRAND, actor: Actor = Depends(require("brand.write"))) -> dict[str, Any]:
    st = studio(request)
    d = await st.repo.get("brands", doc_id, pk=brand_id)
    if not d or d.get("type") != "brand_doc":
        raise NotFound("document not found", code="document_not_found")
    removed = 0
    for c in await st.repo.query("brand_chunks", {"version": "docs"}, pk=brand_id):
        if c.get("meta", {}).get("doc_id") == doc_id:
            await st.repo.delete("brand_chunks", c["id"], pk=brand_id)
            removed += 1
    svc(request).vectors.invalidate(brand_id)
    await st.repo.delete("brands", doc_id, pk=brand_id)
    await st.audit(None, actor, "brand.document_deleted", {"doc_id": doc_id})
    return {"deleted": doc_id, "chunks_removed": removed}


@router.post("/voice-profile/extract", dependencies=[Depends(spend_limit)])
async def extract_voice_profile(request: Request, brand_id: str = DEFAULT_BRAND, _: Actor = Depends(require("brand.write"))) -> dict[str, Any]:
    s = svc(request)
    st = studio(request)
    docs = [d for d in await st.repo.query("brands", {"type": "brand_doc"}, pk=brand_id) if not d.get("quarantined")]
    text = "\n\n".join(d["text"] for d in docs)[:12000]
    if not text:
        raise ValidationFailed("ingest brand guidelines first", code="no_documents")
    out = await s.llm.complete(
        task="brand.voice_profile",
        system=CREW_PREAMBLE + " Extract the brand voice profile from the guidelines. Lists must be short, concrete phrases.",
        user=untrusted(text, 12000),
        schema=VoiceProfileOut,
        context={"text": text},
        max_tokens=1500,
    )
    return {"suggested_voice": out.model_dump(), "note": "Suggestion only — review and apply via PUT /api/brand/kit."}


@router.get("/learnings")
async def learnings(request: Request, brand_id: str = DEFAULT_BRAND) -> list[dict[str, Any]]:
    return await studio(request).repo.query("learnings", pk=brand_id, order_by="created_at", desc=True, limit=100)


class LearningIn(BaseModel):
    statement: str = Field(min_length=8, max_length=400)
    confidence: float = Field(default=0.6, ge=0, le=1)
    source: str = "manual"
    campaign_id: str | None = None


@router.post("/learnings", dependencies=[Depends(mutate_limit)])
async def add_learning_endpoint(request: Request, body: LearningIn, brand_id: str = DEFAULT_BRAND, actor: Actor = Depends(require("brand.write"))) -> dict[str, Any]:
    return await add_learning(request.app.state.services, brand_id, body.statement, {"entered_by": actor.name}, body.confidence, body.source, body.campaign_id)


async def add_learning(s: Any, brand_id: str, statement: str, evidence: dict[str, Any], confidence: float, source: str, campaign_id: str | None) -> dict[str, Any]:
    lid = new_id("lrn")
    doc = {"id": lid, "pk": brand_id, "brand_id": brand_id, "statement": statement, "evidence": evidence, "confidence": round(confidence, 2), "source": source, "campaign_id": campaign_id, "created_at": now_iso()}
    await s.repo.upsert("learnings", doc)
    await s.vectors.add(brand_id, "learnings", [{"id": f"lrn-{lid}", "text": statement, "title": "Learning · " + (campaign_id or source), "source": "Learnings", "meta": {"learning_id": lid}}], kind="learning")
    return doc


FEATURE = Feature(id="CS-01", summary="Ingest brand guidelines (md/pdf/txt/docx), versioned kit, embeddings + cited retrieval, learnings loop.", router=router)
