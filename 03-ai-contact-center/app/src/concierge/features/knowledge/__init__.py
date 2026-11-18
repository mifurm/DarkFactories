"""CC-03 Knowledge-grounded answers / RAG: KB admin (documents, versions, publish, rollback), retrieval with citations, groundedness."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from ...core import i18n
from ...core.rbac import Actor, require
from ...core.registry import EPIC_A, FeatureInfo
from ...engine.rag import answer_question
from .evalset import FABRICATED, FABRICATED_PL, IN_SCOPE, IN_SCOPE_PL, UNANSWERABLE, UNANSWERABLE_PL

FEATURES = [
    FeatureInfo(
        "CC-03", "Knowledge-grounded answers / RAG", EPIC_A, "P0", "/kb", "/api/kb",
        "51 seeded KB documents, heading-aware chunking, embeddings, hybrid retrieval with citations, don't-know threshold, groundedness check, versions + publish/rollback, injection quarantine.",
    ),
]  # fmt: skip
SEED_ORDER = 20

router = APIRouter(prefix="/api/kb", tags=["knowledge (CC-03)"])


async def seed(svc: Any, force: bool) -> dict[str, Any]:
    return await svc.kb.seed(force=force)


class DocBody(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    text: str = Field(min_length=20, max_length=200_000)
    category: str = Field("general", max_length=40)
    lang: str = Field("en", max_length=8)
    tags: list[str] = Field(default_factory=list, max_length=12)
    doc_id: str | None = Field(None, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    publish: bool = False


class PublishBody(BaseModel):
    version: int | None = None


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=400)
    language: str | None = Field(None, max_length=8, description="Answer language; omitted = the request locale")


@router.get("/docs")
async def list_docs(request: Request, _: Actor = Depends(require("kb.read"))) -> list[dict[str, Any]]:
    return await request.app.state.services.kb.list_docs()


@router.get("/docs/{doc_id}")
async def get_doc(doc_id: str, request: Request, _: Actor = Depends(require("kb.read"))) -> dict[str, Any]:
    doc = await request.app.state.services.kb.get_doc(doc_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    return doc


@router.post("/docs")
async def create_doc(body: DocBody, request: Request, actor: Actor = Depends(require("kb.write"))) -> dict[str, Any]:
    svc = request.app.state.services
    return await svc.kb.ingest(title=body.title, text=body.text, category=body.category, lang=body.lang, tags=body.tags, doc_id=body.doc_id, source="admin", author=actor.user, publish=body.publish)


@router.post("/upload")
async def upload(
    request: Request, file: UploadFile = File(...), title: str | None = Form(None), category: str = Form("general"), lang: str = Form("en"), publish: bool = Form(False),
    actor: Actor = Depends(require("kb.write")),
) -> dict[str, Any]:  # fmt: skip
    svc = request.app.state.services
    data = await file.read(svc.settings.max_upload_bytes + 1)
    if len(data) > svc.settings.max_upload_bytes:
        raise HTTPException(413, "file too large")
    name = file.filename or "upload.txt"
    if not name.lower().endswith((".md", ".txt", ".html", ".htm", ".pdf")):
        raise HTTPException(415, "supported: .md .txt .html .pdf")
    res = await svc.kb.ingest_file(name, data, file.content_type or "", title=title, category=category, lang=lang, source=f"upload:{name}", author=actor.user, publish=publish)
    await svc.blobs.put("kb-sources", f"{res['doc_id']}/{name}", data, file.content_type or "application/octet-stream")
    return res


@router.post("/docs/{doc_id}/publish")
async def publish(doc_id: str, body: PublishBody, request: Request, actor: Actor = Depends(require("kb.write"))) -> dict[str, Any]:
    try:
        return await request.app.state.services.kb.publish(doc_id, body.version, actor=actor.user)
    except KeyError:
        raise HTTPException(404, "document or version not found") from None


@router.post("/docs/{doc_id}/rollback")
async def rollback(doc_id: str, request: Request, actor: Actor = Depends(require("kb.write"))) -> dict[str, Any]:
    try:
        return await request.app.state.services.kb.rollback(doc_id, actor=actor.user)
    except KeyError:
        raise HTTPException(404, "document not found") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/search")
async def search(q: str, request: Request, k: int = 4, drafts: bool = False) -> dict[str, Any]:
    if not 2 <= len(q) <= 300:
        raise HTTPException(422, "q must be 2-300 characters")
    res = await request.app.state.services.kb.search(q, k=max(1, min(k, 8)), include_drafts=drafts)
    return {**res, "hits": [{**h, "text": h["text"][:900]} for h in res["hits"]]}


@router.get("/chunks/{chunk_id:path}")
async def chunk(chunk_id: str, request: Request) -> dict[str, Any]:
    c = await request.app.state.services.kb.chunk(chunk_id)
    if c is None:
        raise HTTPException(404, "chunk not found")
    return c


@router.post("/ask")
async def ask(body: AskBody, request: Request) -> dict[str, Any]:
    return await answer_question(request.app.state.services, body.question, body.language or i18n.current_locale())


@router.get("/stats")
async def stats(request: Request) -> dict[str, Any]:
    svc = request.app.state.services
    docs = await svc.kb.list_docs()
    return {"documents": len(docs), "published": sum(1 for d in docs if d["published_version"]), "quarantined": sum(1 for d in docs if d.get("quarantined")), "chunks": len(svc.kb.chunks), "embedder": svc.kb.embedder_id, "categories": sorted({d["category"] for d in docs}), "guard": svc.guard.stats}


@router.post("/evalset/run")
async def run_evalset(request: Request, lang: str = "en", _: Actor = Depends(require("kb.read"))) -> dict[str, Any]:
    """Retrieval + groundedness evaluation on the labelled set (citation accuracy, don't-know rate, fabricated-answer detection); `?lang=pl` runs the Polish set."""
    svc = request.app.state.services
    polish = lang == "pl"
    in_scope, unanswerable, fabricated = (IN_SCOPE_PL, UNANSWERABLE_PL, FABRICATED_PL) if polish else (IN_SCOPE, UNANSWERABLE, FABRICATED)
    prefer = "pl" if polish else None
    hit = 0
    detail = []
    for q, expected in in_scope:
        res = await svc.kb.search(q, k=3, prefer_lang=prefer)
        ids = [h["doc_id"] for h in res["hits"]]
        ok = bool(set(ids) & set(expected)) and res["answerable"]
        hit += ok
        detail.append({"question": q, "expected": expected, "retrieved": ids, "ok": ok})
    dk = 0
    for q in unanswerable:
        res = await svc.kb.search(q, k=3, prefer_lang=prefer)
        dk += not res["answerable"]
    caught = 0
    for q, fake, expect_ungrounded in fabricated:
        res = await svc.kb.search(q, k=3, prefer_lang=prefer)
        g = await svc.cognitive.groundedness(q, fake, [h["text"] for h in res["hits"]], "pl" if polish else "en")
        caught += bool(g.get("ungroundedDetected")) == expect_ungrounded
    return {
        "lang": "pl" if polish else "en", "citation_accuracy": round(hit / len(in_scope), 3), "in_scope": len(in_scope),
        "dont_know_rate": round(dk / len(unanswerable), 3), "unanswerable": len(unanswerable),
        "groundedness_accuracy": round(caught / len(fabricated), 3), "fabricated_cases": len(fabricated), "embedder": svc.kb.embedder_id, "detail": detail,
    }
