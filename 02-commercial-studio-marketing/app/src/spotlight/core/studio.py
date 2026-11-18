"""Studio facade: campaigns, versioned artifacts, assets, audit and Brand-Brain context shared by every feature."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import mimetypes
from typing import Any

from ..domain import colors as col
from ..domain.claims import ClaimRule
from ..domain.guardian import BrandRules, GuardianContext, GuardianSubject, SafetyObs, VoicePack
from ..domain.kit import localized_kit
from ..domain.perfsim import localize_learning
from ..domain.pl_morph import DEFAULT_PL_FORBIDDEN, DEFAULT_PL_REPLACEMENTS, HYPE_PATTERNS_PL
from ..domain.rights import RightsEntry
from ..errors import NotFound
from ..roles import Actor
from ..util import new_id, now_iso, safe_filename, sha256_hex
from .ai.base import current_ctx

RESERVED = {"id", "pk", "campaign_id", "kind", "version", "status", "parent_id", "created_at", "updated_at", "created_by", "guardian"}
KIND_BY_MIME = {"image": "image", "video": "video", "audio": "audio"}


def campaign_lang(campaign: dict[str, Any] | None) -> str:
    """The campaign's content language ("en" for campaigns created before languages existed)."""
    return (campaign or {}).get("language") or "en"


def _voice_pack(voice: dict[str, Any], lang: str) -> VoicePack:
    """A language's voice rules from a kit overlay; Polish falls back to the built-in pack for any missing part."""
    pl = lang == "pl"
    return VoicePack(
        forbidden_words=voice.get("forbidden_words") or (DEFAULT_PL_FORBIDDEN if pl else []),
        replacements=voice.get("replacements") or (DEFAULT_PL_REPLACEMENTS if pl else {}),
        hype_terms=voice.get("hype_terms") or (HYPE_PATTERNS_PL if pl else []),
        max_sentence_words=voice.get("max_sentence_words"),
    )


def asset_kind_for(mime: str, name: str = "") -> str:
    top = (mime or "").split("/")[0]
    if top in KIND_BY_MIME:
        return KIND_BY_MIME[top]
    if name.endswith((".srt", ".vtt")):
        return "subtitle"
    if mime in {"application/zip", "application/x-zip-compressed"}:
        return "archive"
    return "document"


class Studio:
    def __init__(self, svc: Any) -> None:
        self.s = svc
        self.repo = svc.repo

    # ------------------------------------------------------------------ campaigns
    async def campaign(self, campaign_id: str) -> dict[str, Any]:
        c = await self.repo.get("campaigns", campaign_id, pk=campaign_id)
        if not c:
            raise NotFound(f"campaign {campaign_id} not found", code="campaign_not_found", params={"id": campaign_id})
        c.setdefault("language", "en")  # campaigns created before content languages existed are English
        return c

    async def save_campaign(self, c: dict[str, Any]) -> dict[str, Any]:
        return await self.repo.upsert("campaigns", c)

    async def set_stage(self, campaign_id: str, stage: str, status: str | None = None) -> dict[str, Any]:
        c = await self.campaign(campaign_id)
        c["stage"] = stage
        if status:
            c["status"] = status
        return await self.save_campaign(c)

    # ------------------------------------------------------------------ artifacts
    async def create_artifact(self, campaign_id: str, kind: str, data: dict[str, Any], *, actor: Actor | None = None, parent_id: str | None = None, status: str = "draft") -> dict[str, Any]:
        existing = await self.repo.query("artifacts", {"kind": kind}, pk=campaign_id)
        doc = {
            **{k: v for k, v in data.items() if k not in RESERVED},
            "id": new_id("art"),
            "pk": campaign_id,
            "campaign_id": campaign_id,
            "kind": kind,
            "version": len(existing) + 1,
            "status": status,
            "parent_id": parent_id,
            "created_by": actor.to_dict() if actor else None,
            "created_at": now_iso(),
        }
        return await self.repo.upsert("artifacts", doc)

    async def artifact(self, campaign_id: str, artifact_id: str, kind: str | None = None) -> dict[str, Any]:
        a = await self.repo.get("artifacts", artifact_id, pk=campaign_id)
        if not a or (kind and a["kind"] != kind):
            raise NotFound(f"{kind or 'artifact'} {artifact_id} not found", code="artifact_not_found", params={"kind": kind or "artifact", "id": artifact_id})
        return a

    async def artifacts(self, campaign_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        return await self.repo.query("artifacts", {"kind": kind} if kind else None, pk=campaign_id, order_by="created_at", desc=True)

    async def latest(self, campaign_id: str, kind: str, status_in: list[str] | None = None) -> dict[str, Any] | None:
        rows = await self.repo.query("artifacts", {"kind": kind, **({"status": {"$in": status_in}} if status_in else {})}, pk=campaign_id, order_by="version", desc=True, limit=1)
        return rows[0] if rows else None

    async def save_artifact(self, doc: dict[str, Any]) -> dict[str, Any]:
        return await self.repo.upsert("artifacts", doc)

    async def gate_artifact(self, campaign: dict[str, Any], kind: str) -> dict[str, Any] | None:
        """The artifact a stage gate is about: the selected script, else the latest (masters only for spots)."""
        cid = campaign["id"]
        if kind == "script" and campaign.get("selected_script_id"):
            a = await self.repo.get("artifacts", campaign["selected_script_id"], pk=cid)
            if a:
                return a
        rows = await self.repo.query("artifacts", {"kind": kind}, pk=cid, order_by="version", desc=True, limit=None if kind == "spot" else 1)
        if kind == "spot":
            rows = [r for r in rows if r.get("lineage_kind", "master") == "master"]
        return rows[0] if rows else None

    # ------------------------------------------------------------------ assets
    async def put_asset(
        self,
        *,
        campaign_id: str | None,
        name: str,
        data: bytes,
        mime: str,
        kind: str | None = None,
        tags: list[str] | None = None,
        meta: dict[str, Any] | None = None,
        parent_id: str | None = None,
        actor: Actor | None = None,
        source: str = "generated",
        description: str = "",
        index: bool = True,
    ) -> dict[str, Any]:
        aid = new_id("ast")
        kind = kind or asset_kind_for(mime, name)
        blob = f"campaigns/{campaign_id or 'library'}/{kind}/{aid}-{safe_filename(name)}"
        await self.s.blobs.put(blob, data, mime)
        parent_version = 0
        if parent_id:
            p = await self.asset(parent_id)
            parent_version = int(p.get("version", 1))
        doc = {
            "id": aid,
            "pk": campaign_id or "library",
            "campaign_id": campaign_id,
            "kind": kind,
            "name": name,
            "mime": mime,
            "size": len(data),
            "sha256": sha256_hex(data),
            "blob": blob,
            "tags": sorted(set(tags or [])),
            "description": description,
            "meta": meta or {},
            "version": parent_version + 1,
            "parent_id": parent_id,
            "rights_ids": [],
            "collection_ids": [],
            "source": source,
            "status": "draft",
            "ai_generated": source == "generated",
            "created_by": actor.to_dict() if actor else None,
            "created_at": now_iso(),
        }
        doc = await self.repo.upsert("assets", doc)
        if index:
            with contextlib.suppress(Exception):  # indexing must never break asset creation
                await self.index_asset(doc)
        return doc

    async def index_asset(self, doc: dict[str, Any]) -> None:
        text = " · ".join(x for x in [doc["name"], doc.get("description", ""), " ".join(doc.get("tags", [])), doc["kind"], str(doc.get("meta", {}).get("prompt", ""))[:300]] if x)
        await self.s.vectors.add("library", f"asset-{doc['id']}", [{"id": f"lib-{doc['id']}", "text": text, "title": doc["name"], "source": doc["id"], "meta": {"asset_id": doc["id"], "kind": doc["kind"], "campaign_id": doc.get("campaign_id")}}], kind="asset")

    async def asset(self, asset_id: str, campaign_id: str | None = None) -> dict[str, Any]:
        a = await self.repo.get("assets", asset_id, pk=(campaign_id or None) or None)
        if not a and campaign_id:
            a = await self.repo.get("assets", asset_id, pk=None)
        if not a:
            raise NotFound(f"asset {asset_id} not found", code="asset_not_found", params={"id": asset_id})
        return a

    async def asset_bytes(self, asset: dict[str, Any]) -> bytes:
        return await self.s.blobs.get(asset["blob"])

    async def save_asset(self, doc: dict[str, Any]) -> dict[str, Any]:
        return await self.repo.upsert("assets", doc)

    # ------------------------------------------------------------------ audit
    async def audit(self, campaign_id: str | None, actor: Actor | dict[str, Any] | None, action: str, subject: dict[str, Any] | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
        a = actor.to_dict() if isinstance(actor, Actor) else (actor or {"role": "system", "name": "Spotlight"})
        return await self.s.audit.append(campaign_id or "global", a, action, subject, data)

    # ------------------------------------------------------------------ brand brain
    async def brand(self, brand_id: str) -> dict[str, Any]:
        b = await self.repo.get("brands", brand_id, pk=brand_id)
        if not b:
            raise NotFound(f"brand {brand_id} not found", code="brand_not_found", params={"id": brand_id})
        return b

    async def brand_kit(self, brand_id: str) -> dict[str, Any]:
        b = await self.brand(brand_id)
        v = await self.repo.get("brands", f"{brand_id}@{b['active_version']}", pk=brand_id)
        return {**b, "kit": (v or {}).get("kit", {})}

    async def brand_context(self, brand_id: str, query: str, k: int = 4, lang: str = "en") -> dict[str, Any]:
        """Grounding pack for every agent: kit summary, voice, retrieved passages (with citations), learnings — in the campaign language.

        Retrieval prefers passages written in ``lang`` but is cross-lingual (a Polish query can cite an English passage and vice versa)."""
        b = await self.brand_kit(brand_id)
        kit = localized_kit(b["kit"], lang)
        hits = await self.s.vectors.search(brand_id, query, k=k, version=["docs", f"kit-{b['active_version']}", "learnings"], prefer_lang=lang)
        learnings = await self.repo.query("learnings", pk=brand_id, order_by="created_at", desc=True, limit=6)
        learnings = [localize_learning(x, lang) for x in learnings]
        return {
            "brand": {"id": brand_id, "name": b["name"], "version": b["active_version"], "tagline": kit.get("tagline"), "category": kit.get("category")},
            "lang": lang,
            "kit": kit,
            "voice": kit.get("voice", {}),
            "palette": [p["hex"] for p in kit.get("palette", [])],
            "citations": [{"chunk_id": h["id"], "title": h.get("title") or h.get("source"), "source": h.get("source"), "score": h["score"], "text": h["text"], "lang": h.get("lang", "en")} for h in hits],
            "learnings": [{"id": x["id"], "statement": x["statement"], "confidence": x.get("confidence")} for x in learnings],
        }

    async def guardian_context(self, brand_id: str, waivers: list[str] | None = None) -> GuardianContext:
        b = await self.brand_kit(brand_id)
        kit = b["kit"]
        v = kit.get("voice", {})
        logo = kit.get("logo", {})
        packs = {lang: _voice_pack(loc.get("voice") or {}, lang) for lang, loc in (kit.get("i18n") or {}).items()}
        packs.setdefault("pl", _voice_pack({}, "pl"))  # the Polish rules always apply, even for a kit version saved before they existed
        rules = BrandRules(
            palette=[p["hex"] for p in kit.get("palette", [])] or BrandRules().palette,
            forbidden_words=v.get("forbidden_words", []),
            replacements=v.get("replacements", {}),
            max_exclamations=v.get("max_exclamations", 1),
            max_sentence_words=v.get("max_sentence_words", 22),
            logo_min_width_pct=logo.get("min_width_pct", 12.0),
            logo_clear_space_ratio=logo.get("clear_space_ratio", 0.5),
            packs=packs,
        )
        claims = [ClaimRule(**{k: v for k, v in c.items() if k in ClaimRule.model_fields}) for c in await self.repo.query("claims", pk=brand_id)]
        rights = [RightsEntry(**{k: v for k, v in r.items() if k in RightsEntry.model_fields}) for r in await self.repo.query("rights", pk=brand_id)]
        return GuardianContext(brand=rules, claims=claims, rights=rights, waivers=waivers or [])

    # ------------------------------------------------------------------ safety observations (Azure AI Content Safety)
    async def gather_safety(self, subject: GuardianSubject, image_bytes: dict[str, bytes] | None = None, untrusted_text: str | None = None) -> SafetyObs:
        cache: dict[str, Any] = self.s.extras.setdefault("safety_cache", {})
        sem = asyncio.Semaphore(4)
        obs = SafetyObs()

        async def text_one(item_id: str, text: str) -> None:
            key = "t:" + hashlib.sha256(text.encode()).hexdigest()
            if key not in cache:
                async with sem:
                    r = await self.s.safety.analyze_text(text)
                cache[key] = {"max": r.max_severity, "categories": r.categories}
            obs.text[item_id] = {**cache[key]}

        items = [t for t in subject.texts if t.kind != "legal" and t.text.strip()][:40]
        await asyncio.gather(*(text_one(t.id, t.text) for t in items))
        # protected-material detection on the spoken/headline copy as one block (API needs a minimum length)
        block = " ".join(t.text for t in items if t.kind in {"vo", "headline", "body", "dialogue"})
        if block:
            key = "p:" + hashlib.sha256(block.encode()).hexdigest()
            if key not in cache:
                cache[key] = await self.s.safety.protected_material(block)
            if cache[key]:
                for t in items:
                    if t.kind in {"vo", "headline", "body", "dialogue"}:
                        obs.text.setdefault(t.id, {"max": 0, "categories": {}})["protected"] = True
                        break
        if subject.type in {"brief"} or untrusted_text:
            text = untrusted_text or " ".join(t.text for t in items)
            key = "s:" + hashlib.sha256(text.encode()).hexdigest()
            if key not in cache:
                cache[key] = await self.s.safety.shield_prompt(text[:9000])
            if cache[key] and items:
                obs.text.setdefault(items[0].id, {"max": 0, "categories": {}})["attack"] = True
        for vid, data in list((image_bytes or {}).items())[:8]:
            key = "i:" + hashlib.sha256(data).hexdigest()
            if key not in cache:
                r = await self.s.safety.analyze_image(data)
                cache[key] = {"max": r.max_severity, "categories": r.categories}
            obs.images[vid] = {**cache[key]}
        return obs

    @staticmethod
    def dominant(image: bytes) -> list[dict[str, Any]]:
        return col.dominant_colors(image, 6)

    @staticmethod
    def thumbnail(data: bytes, max_px: int = 480) -> bytes:
        from PIL import Image

        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
        return buf.getvalue()


def guess_mime(name: str, default: str = "application/octet-stream") -> str:
    return mimetypes.guess_type(name)[0] or default


def ai_ctx_campaign() -> str | None:
    return current_ctx().campaign_id
