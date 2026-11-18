"""C2PA-style provenance (CS-14): manifest per asset (hashes, tools/models, prompt digests, edits, approvals, rights), signed
sidecar JSON, verification, provenance pack. NOT a certified C2PA claim — a documented, verifiable subset (see ARCHITECTURE)."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .. import __version__
from ..domain.disclosure import localize_labels, required_labels
from ..i18n import current_locale, label
from ..i18n import t as tr
from ..util import canonical_json, new_id, now_iso, sha256_hex
from .audit import entry_hash
from .studio import Studio

KEY_BLOB = "keys/provenance-ed25519.pem"
MANIFEST_VERSION = "spotlight-c2pa-lite/1"
DST_ALGORITHMIC = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"


class LocalSigner:
    """Ed25519 signer. Demo: key generated on first start and kept in the private Entra-only blob container.
    Production target: Azure Key Vault / Managed HSM `sign` with a C2PA-compliant certificate chain."""

    def __init__(self, key: Ed25519PrivateKey) -> None:
        self._key = key
        pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.key_id = sha256_hex(pub)[:16]
        self.public_b64 = base64.b64encode(pub).decode()

    @classmethod
    async def load_or_create(cls, blobs: Any) -> LocalSigner:
        try:
            pem = await blobs.get(KEY_BLOB)
            return cls(serialization.load_pem_private_key(pem, password=None))  # type: ignore[arg-type]
        except Exception:
            key = Ed25519PrivateKey.generate()
            pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
            await blobs.put(KEY_BLOB, pem, "application/x-pem-file")
            return cls(key)

    def sign(self, data: bytes) -> bytes:
        return self._key.sign(data)


def verify_signature(public_b64: str, signature_b64: str, data: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_b64)).verify(base64.b64decode(signature_b64), data)
        return True
    except Exception:
        return False


def manifest_hash(manifest: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(manifest))


async def get_signer(svc: Any) -> LocalSigner:
    if "signer" not in svc.extras:
        svc.extras["signer"] = await LocalSigner.load_or_create(svc.blobs)
    return svc.extras["signer"]


async def build_manifest(svc: Any, asset: dict[str, Any], campaign: dict[str, Any] | None, spot: dict[str, Any] | None = None, parent_hash: str | None = None) -> dict[str, Any]:
    st = Studio(svc)
    actions: list[dict[str, Any]] = []
    ingredients: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []
    rights: list[dict[str, Any]] = []
    meta = asset.get("meta", {})
    ai_generated = bool(asset.get("ai_generated"))
    if asset["kind"] == "image" and meta.get("prompt"):
        actions.append({"action": "c2pa.created", "digitalSourceType": DST_ALGORITHMIC, "softwareAgent": meta.get("model", "image-model"), "when": asset["created_at"], "parameters": {"prompt_sha256": sha256_hex(meta["prompt"]), "quality": meta.get("quality"), "size": meta.get("size")}})
        models.append({"role": "image", "deployment": meta.get("model")})
    elif asset["kind"] == "audio" and meta.get("voice"):
        actions.append({"action": "c2pa.created", "digitalSourceType": DST_ALGORITHMIC, "softwareAgent": meta.get("voice"), "when": asset["created_at"], "parameters": {"text_sha256": sha256_hex(asset.get("description", "")), "chars": meta.get("chars")}})
        models.append({"role": "speech", "deployment": meta.get("voice")})
    elif asset["source"] == "upload":
        actions.append({"action": "c2pa.opened", "softwareAgent": "Spotlight library upload", "when": asset["created_at"], "parameters": {"declared_ai_generated": False}})
    if spot:
        spec = spot["spec"]
        actions.append({"action": "c2pa.placed", "softwareAgent": f"Spotlight compositor {__version__} (ffmpeg, H.264/AAC)", "when": asset["created_at"], "parameters": {"spec_sha256": sha256_hex(canonical_json(spec)), "aspect": spec["aspect"], "duration": spot.get("probe", {}).get("duration")}})
        actions.append({"action": "spotlight.loudness_normalised", "softwareAgent": "ffmpeg loudnorm (EBU R128, two-pass)", "parameters": {"target_lufs": spec.get("loudness_lufs"), "measured": spot.get("loudness")}})
        sb = await st.repo.get("artifacts", spot.get("storyboard_id", ""), pk=campaign["id"]) if campaign and spot.get("storyboard_id") else None
        for shot in (sb or {}).get("shots", []):
            if shot.get("asset_id"):
                a = await st.asset(shot["asset_id"])
                ingredients.append({"asset_id": a["id"], "sha256": a["sha256"], "relationship": "componentOf", "role": "keyframe", "model": shot.get("image_model")})
                models.append({"role": "image", "deployment": shot.get("image_model")})
        for ln in spot["spec"].get("vo", []):
            if ln.get("asset_id"):
                a = await st.asset(ln["asset_id"])
                ingredients.append({"asset_id": a["id"], "sha256": a["sha256"], "relationship": "componentOf", "role": "voice-over", "voice": a["meta"].get("voice")})
                models.append({"role": "speech", "deployment": a["meta"].get("voice")})
        m = spec.get("music")
        if m:
            actions.append({"action": "spotlight.music_generated", "softwareAgent": "Spotlight procedural library (numpy additive synthesis)", "parameters": {"title": m["title"], "mood": m["mood"], "bpm": m["bpm"], "key": m["key"], "seed": m["seed"]}})
            if m.get("rights_id"):
                r = await st.repo.get("rights", m["rights_id"], pk=(campaign or {}).get("brand_id", "northwind"))
                if r:
                    rights.append({"rights_id": r["id"], "title": r["title"], "kind": r["kind"], "licensor": r.get("licensor"), "valid_to": r.get("valid_to"), "territories": r.get("territories")})
        ai_generated = True
    for rid in asset.get("rights_ids", []):
        r = await st.repo.get("rights", rid, pk="northwind")
        if r and not any(x["rights_id"] == rid for x in rights):
            rights.append({"rights_id": r["id"], "title": r["title"], "kind": r["kind"], "licensor": r.get("licensor"), "valid_to": r.get("valid_to")})
    chain = (campaign or {}).get("id") or "global"
    head = await svc.audit.head(chain)
    approvals = [{"stage": a["stage"], "state": a["state"], "decisions": [{"role": d["role"], "by": d["by"], "decision": d["decision"], "at": d["at"]} for d in a.get("decisions", [])]} for a in await st.repo.query("approvals", {"type": "approval"}, pk=chain)] if campaign else []
    reports = await st.repo.query("reports", {"type": "report", "artifact_id": spot["id"]}, pk=chain, order_by="created_at", desc=True, limit=1) if (spot and campaign) else []
    labels = required_labels((campaign or {}).get("markets", []), (campaign or {}).get("channels", []), ai_generated, (spot or {}).get("spec", {}).get("lang", "en")) if ai_generated else None
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "claim_generator": f"SwarmAI Spotlight/{__version__}",
        "title": asset["name"],
        "asset": {"id": asset["id"], "sha256": asset["sha256"], "size": asset["size"], "mime": asset["mime"], "version": asset.get("version", 1)},
        "created_at": now_iso(),
        "campaign_id": (campaign or {}).get("id"),
        "assertions": {
            "actions": actions,
            "ingredients": ingredients,
            "ai_disclosure": {"ai_generated": ai_generated, "labels": labels, "burned_in_badge": (spot or {}).get("spec", {}).get("disclosure_badge")},
            "rights": rights,
            "approvals": approvals,
            "guardian": {k: reports[0].get(k) for k in ("id", "verdict", "score", "rules_version")} if reports else None,
            "models": [dict(t) for t in {tuple(sorted(m.items())) for m in models if m.get("deployment")}],
        },
        "audit_anchor": {"chain": chain, "seq": head["seq"] if head else 0, "hash": head["hash"] if head else None},
        "prev_manifest_hash": parent_hash,
        "notice": "C2PA-style (hash-based, signed) manifest for demonstration — not a certified C2PA Content Credential.",
    }
    return manifest


async def create_for_asset(svc: Any, asset: dict[str, Any], campaign: dict[str, Any] | None, spot: dict[str, Any] | None = None) -> dict[str, Any]:
    st = Studio(svc)
    signer = await get_signer(svc)
    prev = await st.repo.query("provenance", {"asset_id": asset["id"]}, order_by="created_at", desc=True, limit=1)
    manifest = await build_manifest(svc, asset, campaign, spot, prev[0]["manifest_hash"] if prev else None)
    mh = manifest_hash(manifest)
    sig = base64.b64encode(signer.sign(mh.encode())).decode()
    sidecar = {"manifest": manifest, "manifest_hash": mh, "signature": {"alg": "Ed25519", "key_id": signer.key_id, "public_key": signer.public_b64, "value": sig}}
    pid = new_id("prv")
    blob = f"provenance/{asset['id']}/{pid}.c2pa.json"
    await svc.blobs.put(blob, json.dumps(sidecar, indent=2).encode(), "application/json")
    doc = {"id": pid, "pk": (campaign or {}).get("id") or "library", "campaign_id": (campaign or {}).get("id"), "asset_id": asset["id"], "manifest": manifest, "manifest_hash": mh, "signature": sidecar["signature"], "sidecar_blob": blob, "created_at": now_iso()}
    await svc.repo.upsert("provenance", doc)
    return doc


async def verify_doc(svc: Any, doc: dict[str, Any], asset_bytes: bytes | None = None, manifest_override: dict[str, Any] | None = None) -> dict[str, Any]:
    """Hash match + signature + audit anchor + ingredient hashes. ``manifest_override`` lets callers test tampered copies."""
    st = Studio(svc)
    manifest = manifest_override if manifest_override is not None else doc["manifest"]
    checks: list[dict[str, Any]] = []
    if asset_bytes is None:
        try:
            asset_bytes = await st.asset_bytes(await st.asset(doc["asset_id"]))
        except Exception:
            asset_bytes = None
    if asset_bytes is not None:
        ok = sha256_hex(asset_bytes) == manifest["asset"]["sha256"]
        checks.append({"name": "asset_hash", "ok": ok, "detail": tr("prov.asset_hash.ok" if ok else "prov.asset_hash.bad")})
    else:
        checks.append({"name": "asset_hash", "ok": False, "detail": tr("prov.asset_hash.na")})
    mh = manifest_hash(manifest)
    ok = mh == doc["manifest_hash"]
    checks.append({"name": "manifest_hash", "ok": ok, "detail": tr("prov.manifest_hash.ok" if ok else "prov.manifest_hash.bad")})
    sig = doc["signature"]
    ok = verify_signature(sig["public_key"], sig["value"], mh.encode())
    checks.append({"name": "signature", "ok": ok, "detail": tr("prov.signature.ok", key_id=sig["key_id"]) if ok else tr("prov.signature.bad")})
    anchor = manifest.get("audit_anchor") or {}
    if anchor.get("hash"):
        entries = await svc.audit.entries(anchor["chain"])
        e = next((x for x in entries if x["seq"] == anchor["seq"]), None)
        ok = bool(e and e["hash"] == anchor["hash"] and entry_hash(e) == e["hash"])
        checks.append({"name": "audit_anchor", "ok": ok, "detail": tr("prov.audit_anchor.ok", chain=anchor["chain"], seq=anchor["seq"]) if ok else tr("prov.audit_anchor.bad")})
    bad = []
    for ing in manifest.get("assertions", {}).get("ingredients", []):
        try:
            a = await st.asset(ing["asset_id"])
            if a["sha256"] != ing["sha256"]:
                bad.append(ing["asset_id"])
        except Exception:
            bad.append(ing["asset_id"])
    if manifest.get("assertions", {}).get("ingredients"):
        checks.append({"name": "ingredients", "ok": not bad, "detail": tr("prov.ingredients.ok", n=len(manifest["assertions"]["ingredients"])) if not bad else tr("prov.ingredients.bad", ids=str(bad[:3]))})
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "manifest_hash": mh, "verified_at": now_iso()}


async def build_pack(svc: Any, doc: dict[str, Any]) -> bytes:
    """Provenance pack: asset + signed sidecar + disclosure labels + verification report (zip)."""
    st = Studio(svc)
    asset = await st.asset(doc["asset_id"])
    data = await st.asset_bytes(asset)
    ver = await verify_doc(svc, doc, data)
    labels = (doc["manifest"]["assertions"].get("ai_disclosure") or {}).get("labels")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(asset["name"], data)
        z.writestr(f"{asset['name']}.c2pa.json", json.dumps({"manifest": doc["manifest"], "manifest_hash": doc["manifest_hash"], "signature": doc["signature"]}, indent=2))
        z.writestr("disclosure-labels.json", json.dumps(labels, indent=2))
        z.writestr("verification-report.json", json.dumps(ver, indent=2))
        z.writestr("README.txt", tr("prov.pack.readme"))
        s = human_summary(doc)
        z.writestr("summary.txt", "\n".join([s["headline"], "", *s["lines"]]) + "\n")  # human-readable, in the request language (the JSON files stay machine-readable English)
    return buf.getvalue()


def human_summary(doc: dict[str, Any], locale: str | None = None) -> dict[str, Any]:
    """The manifest in plain words, rendered in ``locale`` (default: the request locale) at read time. The signed manifest itself is never
    modified: its machine fields stay English, only this summary (and the disclosure-label wording shown with it) is localized."""
    loc = locale or current_locale()
    m = doc["manifest"]
    a = m.get("assertions", {})
    ai = a.get("ai_disclosure") or {}
    lines: list[str] = []
    if ai.get("ai_generated"):
        badge = ai.get("burned_in_badge")
        lines.append(tr("prov.sum.ai.yes", loc, badge=badge) if badge else tr("prov.sum.ai.yes_nobadge", loc))
    else:
        lines.append(tr("prov.sum.ai.no", loc))
    models = sorted({str(x.get("deployment")) for x in a.get("models", []) if x.get("deployment")})
    lines.append(tr("prov.sum.models", loc, models=", ".join(models)) if models else tr("prov.sum.models.none", loc))
    if a.get("ingredients"):
        lines.append(tr("prov.sum.ingredients", loc, count=len(a["ingredients"])))
    rights = a.get("rights") or []
    lines.append(tr("prov.sum.rights", loc, count=len(rights), titles="; ".join(r["title"] for r in rights)) if rights else tr("prov.sum.rights.none", loc))
    if a.get("approvals"):
        lines.append(tr("prov.sum.approvals", loc, approved=sum(1 for x in a["approvals"] if x.get("state") == "approved"), total=len(a["approvals"])))
    if a.get("guardian"):
        g = a["guardian"]
        lines.append(tr("prov.sum.guardian", loc, verdict=label("label.verdict", g.get("verdict"), loc), score=g.get("score")))
    labels = localize_labels(ai.get("labels"), loc)
    if labels and labels.get("jurisdictions"):
        lines.append(tr("prov.sum.labels", loc, names=", ".join(j["name"] for j in labels["jurisdictions"])))
    sig = doc.get("signature") or {}
    lines.append(tr("prov.sum.signature", loc, key_id=sig.get("key_id", "?"), hash=str(doc.get("manifest_hash", ""))[:12]))
    anchor = m.get("audit_anchor") or {}
    if anchor.get("hash"):
        lines.append(tr("prov.sum.audit", loc, chain=anchor["chain"], seq=anchor["seq"]))
    lines.append(tr("prov.sum.notice", loc))
    return {"lang": loc, "headline": tr("prov.sum.headline", loc, title=m.get("title", "")), "lines": lines}


def tamper_copy(doc: dict[str, Any]) -> dict[str, Any]:
    m = json.loads(json.dumps(doc["manifest"]))
    m["assertions"]["ai_disclosure"]["ai_generated"] = not m["assertions"]["ai_disclosure"].get("ai_generated", True)
    return m
