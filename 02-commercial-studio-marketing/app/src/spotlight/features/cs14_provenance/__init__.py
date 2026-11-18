"""CS-14 AI disclosure & provenance — C2PA-style manifest per asset, sidecar JSON, disclosure labels, pack export, verification."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from pydantic import BaseModel

from ...core import provenance as prov
from ...deps import mutate_limit, svc
from ...domain.disclosure import PLATFORMS, required_labels
from ...errors import NotFound, ValidationFailed
from ...registry import Feature
from ...roles import Actor, require
from ...util import sha256_hex
from ..common import studio

router = APIRouter(prefix="/api/provenance", tags=["CS-14 AI Disclosure & Provenance"])


async def _latest(st: Any, asset_id: str) -> dict[str, Any] | None:
    rows = await st.repo.query("provenance", {"asset_id": asset_id}, order_by="created_at", desc=True, limit=1)
    return rows[0] if rows else None


@router.get("/labels")
async def labels(markets: str = "US", channels: str = "", ai: bool = True, lang: str = "en") -> dict[str, Any]:
    """Which AI-disclosure labels a campaign needs per jurisdiction and platform (illustrative — validate with counsel)."""
    return {**required_labels([m.strip().upper() for m in markets.split(",") if m.strip()], [c.strip().lower() for c in channels.split(",") if c.strip()], ai, lang), "platform_catalog": PLATFORMS}


@router.get("/assets/{asset_id}")
async def get_manifest(request: Request, asset_id: str) -> dict[str, Any]:
    st = studio(request)
    doc = await _latest(st, asset_id)
    if not doc:
        raise NotFound("no provenance manifest for this asset yet", code="manifest_missing")
    ver = await prov.verify_doc(svc(request), doc)
    return {"id": doc["id"], "asset_id": asset_id, "manifest": doc["manifest"], "manifest_hash": doc["manifest_hash"], "signature": dict(doc["signature"].items()), "sidecar_url": f"/api/provenance/assets/{asset_id}/sidecar.json", "verification": ver}


@router.get("/assets/{asset_id}/sidecar.json")
async def sidecar(request: Request, asset_id: str) -> Response:
    st = studio(request)
    doc = await _latest(st, asset_id)
    if not doc:
        raise NotFound("no provenance manifest for this asset yet", code="manifest_missing")
    data = await svc(request).blobs.get(doc["sidecar_blob"])
    return Response(data, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{asset_id}.c2pa.json"'})


@router.post("/assets/{asset_id}/manifest", dependencies=[Depends(mutate_limit)])
async def create_manifest(request: Request, asset_id: str, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    st = studio(request)
    asset = await st.asset(asset_id)
    camp = await st.campaign(asset["campaign_id"]) if asset.get("campaign_id") else None
    spot = None
    if asset.get("meta", {}).get("spec_id") and camp:
        spot = next((a for a in await st.artifacts(camp["id"], "spot") if a.get("assets", {}).get("video") == asset_id), None)
    doc = await prov.create_for_asset(svc(request), asset, camp, spot)
    await st.audit(asset.get("campaign_id"), actor, "provenance.manifest_created", {"asset_id": asset_id, "manifest_id": doc["id"]})
    return {"id": doc["id"], "manifest_hash": doc["manifest_hash"], "signature": doc["signature"]["key_id"]}


class VerifyIn(BaseModel):
    asset_id: str
    tamper_test: bool = False


@router.post("/verify")
async def verify(request: Request, body: VerifyIn) -> dict[str, Any]:
    """Verify an asset against its signed manifest. ``tamper_test`` additionally proves verification FAILS on a tampered copy."""
    st = studio(request)
    doc = await _latest(st, body.asset_id)
    if not doc:
        raise NotFound("no provenance manifest for this asset yet", code="manifest_missing")
    s = svc(request)
    result = await prov.verify_doc(s, doc)
    out: dict[str, Any] = {"asset_id": body.asset_id, "result": result}
    if body.tamper_test:
        asset = await st.asset(body.asset_id)
        data = await st.asset_bytes(asset)
        out["tamper_manifest"] = await prov.verify_doc(s, doc, data, manifest_override=prov.tamper_copy(doc))
        flipped = bytearray(data)
        flipped[len(flipped) // 2] ^= 0xFF
        out["tamper_asset"] = await prov.verify_doc(s, doc, bytes(flipped))
        out["tamper_detected"] = (not out["tamper_manifest"]["ok"]) and (not out["tamper_asset"]["ok"])
    return out


@router.post("/verify/file")
async def verify_file(request: Request, file: UploadFile = File(...), sidecar_json: str = Form(...)) -> dict[str, Any]:
    """Independent verification: upload a file + its sidecar JSON; checks hash, manifest hash and Ed25519 signature."""
    s = svc(request)
    data = await file.read(s.settings.max_upload_bytes + 1)
    try:
        sc = json.loads(sidecar_json)
        manifest, mh, sig = sc["manifest"], sc["manifest_hash"], sc["signature"]
    except Exception as exc:
        raise ValidationFailed("sidecar_json must be a Spotlight .c2pa.json document", code="bad_sidecar") from exc
    checks = [
        {"name": "asset_hash", "ok": sha256_hex(data) == manifest["asset"]["sha256"], "detail": "file SHA-256 vs manifest"},
        {"name": "manifest_hash", "ok": prov.manifest_hash(manifest) == mh, "detail": "manifest content vs recorded hash"},
        {"name": "signature", "ok": prov.verify_signature(sig["public_key"], sig["value"], mh.encode()), "detail": f"Ed25519 key {sig.get('key_id')}"},
    ]
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


@router.get("/assets/{asset_id}/pack")
async def pack(request: Request, asset_id: str, _: Actor = Depends(require("export"))) -> Response:
    st = studio(request)
    doc = await _latest(st, asset_id)
    if not doc:
        raise NotFound("no provenance manifest for this asset yet", code="manifest_missing")
    data = await prov.build_pack(svc(request), doc)
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="provenance-pack-{asset_id}.zip"'})


@router.get("/campaigns/{campaign_id}")
async def campaign_summary(request: Request, campaign_id: str) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)
    assets = [a for a in await st.repo.query("assets", {"campaign_id": campaign_id}, limit=500) if a["kind"] == "video"]  # deliverables; keyframes/voice are hashed as ingredients of the spot manifest
    manifests = {m["asset_id"]: m for m in await st.repo.query("provenance", pk=campaign_id)}
    rows = [{"asset_id": a["id"], "name": a["name"], "kind": a["kind"], "has_manifest": a["id"] in manifests, "manifest_id": manifests.get(a["id"], {}).get("id"), "ai_generated": a.get("ai_generated")} for a in assets]
    return {"assets": rows, "coverage": round(sum(1 for r in rows if r["has_manifest"]) / max(1, len(rows)) * 100, 1), "signer": (await prov.get_signer(svc(request))).key_id}


FEATURE = Feature(id="CS-14", summary="C2PA-style signed manifest per asset (hashes, models, prompt digests, edits, approvals, rights), sidecar JSON, jurisdiction/platform labels, provenance pack, tamper-evident verification.", router=router)
