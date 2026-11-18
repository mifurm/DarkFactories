"""CS-21 Asset library / DAM — Entra-only Blob storage behind the API (no public blobs), metadata, tags, semantic search,
versions, rights links, collections."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...core.studio import asset_kind_for
from ...deps import mutate_limit, spend_limit, svc
from ...errors import AppError, NotFound, PayloadTooLarge, ValidationFailed
from ...registry import Feature
from ...roles import Actor, require
from ...util import new_id, now_iso, safe_filename
from ..common import studio

router = APIRouter(prefix="/api/library", tags=["CS-21 Asset Library"])
ALLOWED = {
    "image/png", "image/jpeg", "image/webp", "video/mp4", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "text/plain", "text/markdown", "text/csv",
    "application/pdf", "application/json", "application/x-subrip", "text/vtt", "application/zip",
}
EXT_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".mp4": "video/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv", ".pdf": "application/pdf", ".json": "application/json", ".srt": "application/x-subrip", ".vtt": "text/vtt"}


def public(a: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in a.items() if k != "blob"}


@router.get("/assets")
async def list_assets(request: Request, q: str | None = None, kind: str | None = None, tag: str | None = None, campaign_id: str | None = None, collection: str | None = None, status: str | None = None, limit: int = 60) -> dict[str, Any]:
    st = studio(request)
    where: dict[str, Any] = {}
    if kind:
        where["kind"] = kind
    if campaign_id:
        where["campaign_id"] = campaign_id
    if status:
        where["status"] = status
    if tag:
        where["tags"] = {"$contains": tag.lower()}
    if collection:
        where["collection_ids"] = {"$contains": collection}
    rows = await st.repo.query("assets", where or None, order_by="created_at", desc=True, limit=min(max(limit, 1), 200))
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in (r["name"] + " " + " ".join(r.get("tags", [])) + " " + r.get("description", "")).lower()]
    return {"assets": [public(r) for r in rows], "count": len(rows)}


@router.get("/search")
async def semantic_search(request: Request, q: str, kind: str | None = None, k: int = 12) -> dict[str, Any]:
    """Semantic search over asset name/tags/description/prompt (text-embedding-3-small; in-process cosine index)."""
    st = studio(request)
    vectors = svc(request).vectors
    wanted = min(max(k, 1), 30)
    hits = await vectors.search("library", q[:300], k=min(wanted * 4, 120))  # over-fetch: vectors of deleted assets must not push live ones out of the top-k
    out: list[dict[str, Any]] = []
    stale: set[str] = set()
    for h in hits:
        aid = h.get("meta", {}).get("asset_id")
        a = await st.repo.get("assets", aid) if aid else None
        if a is None:
            if aid:
                stale.add(aid)
            continue
        if not kind or a["kind"] == kind:
            out.append({**public(a), "score": h["score"]})
        if len(out) >= wanted:
            break
    for aid in stale:  # self-heal vectors left behind by assets that were deleted before they were removed together
        await vectors.delete_where("library", {"meta.asset_id": aid})
    return {"query": q, "results": out}


@router.get("/assets/{asset_id}")
async def get_asset(request: Request, asset_id: str) -> dict[str, Any]:
    st = studio(request)
    a = await st.asset(asset_id)
    chain: list[dict[str, Any]] = []
    cur = a
    while cur.get("parent_id") and len(chain) < 20:
        cur = await st.asset(cur["parent_id"])
        chain.append({"id": cur["id"], "version": cur["version"], "created_at": cur["created_at"]})
    children = await st.repo.query("assets", {"parent_id": asset_id})
    rights = []
    for rid in a.get("rights_ids", []):
        r = await st.repo.get("rights", rid, pk="northwind")
        if r:
            rights.append({"id": r["id"], "title": r["title"], "kind": r["kind"], "status": r["status"], "valid_to": r.get("valid_to")})
    prov = await st.repo.query("provenance", {"asset_id": asset_id}, limit=1)
    return {**public(a), "ancestors": chain, "children": [{"id": c["id"], "version": c["version"], "name": c["name"]} for c in children], "rights": rights, "provenance_id": prov[0]["id"] if prov else None}


def _range(header: str | None, size: int) -> tuple[int, int] | None:
    if not header:
        return None
    m = re.match(r"bytes=(\d*)-(\d*)$", header.strip())
    if not m:
        return None
    a, b = m.group(1), m.group(2)
    if a == "" and b == "":
        return None
    if a == "":
        n = int(b)
        return max(0, size - n), size - 1
    start = int(a)
    end = int(b) if b else size - 1
    return (start, min(end, size - 1)) if start < size else None


@router.get("/assets/{asset_id}/content")
async def content(request: Request, asset_id: str, download: bool = False) -> Response:
    st = studio(request)
    a = await st.asset(asset_id)
    data = await st.asset_bytes(a)
    size = len(data)
    mime = a["mime"] if a["mime"] in ALLOWED or a["mime"].startswith(("image/", "video/", "audio/")) else "application/octet-stream"
    if mime == "image/svg+xml":
        mime = "application/octet-stream"
    fname = safe_filename(a["name"])
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=600", "Content-Disposition": f'{"attachment" if download else "inline"}; filename="{fname}"', "ETag": f'"{a["sha256"][:24]}"'}
    rng = _range(request.headers.get("range"), size)
    if rng:
        s, e = rng
        headers["Content-Range"] = f"bytes {s}-{e}/{size}"
        return Response(content=data[s : e + 1], status_code=206, media_type=mime, headers=headers)
    if request.method == "HEAD":
        headers["Content-Length"] = str(size)
    return StreamingResponse(iter([data]), media_type=mime, headers={**headers, "Content-Length": str(size)})


async def _read_upload(request: Request, file: UploadFile) -> tuple[bytes, str, str]:
    s = svc(request)
    data = await file.read(s.settings.max_upload_bytes + 1)
    if len(data) > s.settings.max_upload_bytes:
        raise PayloadTooLarge(f"upload exceeds {s.settings.max_upload_bytes // 1048576} MB", key="err.payload_too_large.upload_mb", params={"mb": s.settings.max_upload_bytes // 1048576})
    name = safe_filename(file.filename or "upload.bin")
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    mime = EXT_MIME.get(ext) or (file.content_type or "application/octet-stream")
    if mime not in ALLOWED:
        raise AppError(f"file type {mime!r} is not allowed", code="unsupported_media", status=415, key="err.unsupported_media.mime", params={"mime": mime})
    if mime.startswith("image/"):
        import io

        from PIL import Image

        try:
            Image.open(io.BytesIO(data)).verify()
        except Exception as exc:
            raise ValidationFailed("file is not a valid image", code="bad_image") from exc
    return data, name, mime


@router.post("/assets", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def upload(
    request: Request,
    file: UploadFile = File(...),
    tags: str = Form(default=""),
    description: str = Form(default=""),
    campaign_id: str = Form(default=""),
    actor: Actor = Depends(require("library.write")),
) -> dict[str, Any]:
    st = studio(request)
    if campaign_id:
        await st.campaign(campaign_id)
    data, name, mime = await _read_upload(request, file)
    a = await st.put_asset(campaign_id=campaign_id or None, name=name, data=data, mime=mime, kind=asset_kind_for(mime, name), tags=[t.strip().lower() for t in tags.split(",") if t.strip()], description=description[:500], actor=actor, source="upload")
    await st.audit(campaign_id or None, actor, "library.asset_uploaded", {"asset_id": a["id"]}, {"name": name, "size": len(data)})
    return public(a)


@router.post("/assets/{asset_id}/version", dependencies=[Depends(mutate_limit)])
async def new_version(request: Request, asset_id: str, file: UploadFile = File(...), note: str = Form(default=""), actor: Actor = Depends(require("library.write"))) -> dict[str, Any]:
    st = studio(request)
    parent = await st.asset(asset_id)
    data, name, mime = await _read_upload(request, file)
    a = await st.put_asset(campaign_id=parent.get("campaign_id"), name=name, data=data, mime=mime, tags=parent.get("tags", []), description=note or parent.get("description", ""), parent_id=asset_id, actor=actor, source="upload", meta={"note": note})
    a["rights_ids"] = parent.get("rights_ids", [])
    await st.save_asset(a)
    await st.audit(parent.get("campaign_id"), actor, "library.asset_versioned", {"asset_id": a["id"], "parent_id": asset_id}, {"version": a["version"]})
    return public(a)


class AssetPatch(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    tags: list[str] | None = None
    description: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, pattern="^(draft|in_review|approved|archived)$")


@router.put("/assets/{asset_id}", dependencies=[Depends(mutate_limit)])
async def update_asset(request: Request, asset_id: str, body: AssetPatch, actor: Actor = Depends(require("library.write"))) -> dict[str, Any]:
    st = studio(request)
    a = await st.asset(asset_id)
    if body.name:
        a["name"] = safe_filename(body.name)
    if body.tags is not None:
        a["tags"] = sorted({t.strip().lower() for t in body.tags if t.strip()})
    if body.description is not None:
        a["description"] = body.description
    if body.status:
        a["status"] = body.status
    a = await st.save_asset(a)
    await st.index_asset(a)
    return public(a)


@router.delete("/assets/{asset_id}", dependencies=[Depends(mutate_limit)])
async def delete_asset(request: Request, asset_id: str, actor: Actor = Depends(require("brand.write"))) -> dict[str, Any]:
    st = studio(request)
    a = await st.asset(asset_id)
    await svc(request).blobs.delete(a["blob"])
    await st.repo.delete("assets", asset_id, pk=a["pk"])
    await svc(request).vectors.delete_where("library", {"meta.asset_id": asset_id})
    await st.audit(a.get("campaign_id"), actor, "library.asset_deleted", {"asset_id": asset_id})
    return {"deleted": asset_id}


class RightsLink(BaseModel):
    rights_ids: list[str]


@router.post("/assets/{asset_id}/rights", dependencies=[Depends(mutate_limit)])
async def link_rights(request: Request, asset_id: str, body: RightsLink, actor: Actor = Depends(require("library.write"))) -> dict[str, Any]:
    st = studio(request)
    a = await st.asset(asset_id)
    for rid in body.rights_ids:
        if not await st.repo.get("rights", rid, pk="northwind"):
            raise NotFound(f"rights entry {rid} not found", code="rights_not_found", key="err.rights_not_found.id", params={"id": rid})
    a["rights_ids"] = sorted(set(body.rights_ids))
    await st.save_asset(a)
    await st.audit(a.get("campaign_id"), actor, "library.rights_linked", {"asset_id": asset_id}, {"rights_ids": a["rights_ids"]})
    return public(a)


@router.get("/collections")
async def list_collections(request: Request) -> list[dict[str, Any]]:
    return await studio(request).repo.query("collections", order_by="created_at", desc=True)


class CollectionIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=300)


@router.post("/collections", dependencies=[Depends(mutate_limit)])
async def create_collection(request: Request, body: CollectionIn, actor: Actor = Depends(require("library.write"))) -> dict[str, Any]:
    doc = {"id": new_id("col"), "pk": "tenant", **body.model_dump(), "created_at": now_iso(), "created_by": actor.name}
    return await studio(request).repo.upsert("collections", doc)


class CollectionAssets(BaseModel):
    asset_ids: list[str]


@router.post("/collections/{collection_id}/assets", dependencies=[Depends(mutate_limit)])
async def add_to_collection(request: Request, collection_id: str, body: CollectionAssets, actor: Actor = Depends(require("library.write"))) -> dict[str, Any]:
    st = studio(request)
    if not await st.repo.get("collections", collection_id, pk="tenant"):
        raise NotFound("collection not found", code="collection_not_found")
    for aid in body.asset_ids:
        a = await st.asset(aid)
        a["collection_ids"] = sorted(set(a.get("collection_ids", [])) | {collection_id})
        await st.save_asset(a)
    return {"collection_id": collection_id, "added": len(body.asset_ids)}


FEATURE = Feature(id="CS-21", summary="DAM over Entra-only Blob: metadata, tags, semantic search (embeddings), versions, rights links, collections; media served via the backend (range requests, no public blobs).", router=router)
