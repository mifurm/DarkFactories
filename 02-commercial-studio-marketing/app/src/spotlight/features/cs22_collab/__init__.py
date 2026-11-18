"""CS-22 Collaboration, roles & integrations — roles/permissions, Teams/Slack-compatible webhook notifications, campaign-pack export, REST API."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...core.jobs import JobContext
from ...core.notify import EVENTS, INTERNAL_SINK, validate_webhook_url
from ...core.studio import campaign_lang
from ...deps import mutate_limit, svc
from ...errors import NotFound, ValidationFailed
from ...i18n import label, t
from ...registry import Feature
from ...roles import PERMISSIONS, Actor, Role, require
from ...util import new_id, now_iso
from ..common import studio
from ..jobs_util import submit_job

router = APIRouter(tags=["CS-22 Collaboration & Integrations"])

ROSTER = [  # fictional demo roster (no real people)
    {"name": "Ava Reyes", "role": "admin", "title": "Studio administrator"},
    {"name": "Noah Lindqvist", "role": "brand_manager", "title": "Brand Manager, Northwind"},
    {"name": "Mira Okonkwo", "role": "creative_director", "title": "Creative Director"},
    {"name": "Jonas Berg", "role": "creative", "title": "Senior creative"},
    {"name": "Priya Nair", "role": "legal", "title": "Legal & compliance reviewer"},
    {"name": "Studio Fabrikam", "role": "agency_guest", "title": "Agency partner (guest)"},
]


@router.get("/api/team/members")
async def members() -> dict[str, Any]:
    return {"members": [{**m, "title": t(f"team.title.{m['role']}")} for m in ROSTER], "note": t("team.note")}


@router.get("/api/team/roles")
async def roles() -> dict[str, Any]:
    return {"roles": [{"id": r.value, "label": label("label.role", r.value), "permissions": sorted(p for p, rs in PERMISSIONS.items() if r in rs)} for r in Role], "permissions": sorted(PERMISSIONS)}


@router.get("/api/team/api")
async def api_info(request: Request) -> dict[str, Any]:
    return {"openapi": "/openapi.json", "docs": "/docs", "auth": t("team.api.auth"), "rate_limits": {"spend_per_ip_per_min": svc(request).settings.rate_per_ip_spend_per_min, "mutate_per_ip_per_min": svc(request).settings.rate_per_ip_mutate_per_min}, "streaming": "SSE: GET /api/stream/jobs/{job_id}", "examples": ["POST /api/campaigns", "POST /api/campaigns/{id}/script/generate?wait=true", "GET /api/library/assets/{id}/content"]}


class HookIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    url: str = Field(max_length=500)
    format: str = Field(default="teams", pattern="^(teams|slack|generic)$")
    events: list[str] = Field(default_factory=lambda: ["*"])
    enabled: bool = True


@router.get("/api/team/webhooks")
async def list_hooks(request: Request) -> dict[str, Any]:
    rows = await studio(request).repo.query("webhooks", {"type": "webhook"}, pk="tenant", order_by="created_at", desc=True)
    return {"webhooks": rows, "events": EVENTS, "internal_sink": INTERNAL_SINK, "allow_list": ["*.webhook.office.com", "*.office.com", "*.logic.azure.com", "hooks.slack.com", "*.slack.com", INTERNAL_SINK]}


@router.post("/api/team/webhooks", dependencies=[Depends(mutate_limit)])
async def create_hook(request: Request, body: HookIn, actor: Actor = Depends(require("webhooks.write"))) -> dict[str, Any]:
    await validate_webhook_url(body.url, svc(request).settings.allow_internal_webhook_sink)
    bad = [e for e in body.events if e != "*" and e not in EVENTS]
    if bad:
        raise ValidationFailed(f"unknown event(s) {bad}", code="bad_event", params={"events": ", ".join(bad)})
    doc = {**body.model_dump(), "id": new_id("whk"), "pk": "tenant", "type": "webhook", "created_by": actor.name, "created_at": now_iso()}
    await studio(request).repo.upsert("webhooks", doc)
    notifier = svc(request).notifier
    notifier.attach()
    await studio(request).audit(None, actor, "webhook.created", {"webhook_id": doc["id"]}, {"name": body.name, "format": body.format})
    return doc


@router.delete("/api/team/webhooks/{hook_id}", dependencies=[Depends(mutate_limit)])
async def delete_hook(request: Request, hook_id: str, actor: Actor = Depends(require("webhooks.write"))) -> dict[str, Any]:
    if not await studio(request).repo.delete("webhooks", hook_id, pk="tenant"):
        raise NotFound("webhook not found", code="webhook_not_found")
    return {"deleted": hook_id}


@router.post("/api/team/webhooks/{hook_id}/test", dependencies=[Depends(mutate_limit)])
async def test_hook(request: Request, hook_id: str, _: Actor = Depends(require("webhooks.write"))) -> dict[str, Any]:
    st = studio(request)
    hook = await st.repo.get("webhooks", hook_id, pk="tenant")
    if not hook:
        raise NotFound("webhook not found", code="webhook_not_found")
    n = svc(request).notifier
    n.attach()
    return await n.dispatcher.send(hook, "approval.requested", {"campaign": t("notify.test.campaign"), "stage": "Script", "stage_id": "script", "by": t("notify.test.by")})  # type: ignore[union-attr]


@router.get("/api/team/deliveries")
async def deliveries(request: Request, limit: int = 30) -> dict[str, Any]:
    rows = await studio(request).repo.query("webhooks", {"type": "delivery"}, pk="tenant", order_by="created_at", desc=True, limit=min(limit, 100))
    return {"deliveries": rows}


# ---------------------------------------------------------------------------------------------- campaign pack export


@router.post("/api/campaigns/{campaign_id}/export", dependencies=[Depends(mutate_limit)])
async def export_pack(request: Request, campaign_id: str, approved_only: bool = False, wait: bool = False, actor: Actor = Depends(require("export"))) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)

    async def run(job: JobContext) -> dict[str, Any]:
        s = svc(request)
        camp = await st.campaign(campaign_id)
        lang = campaign_lang(camp)
        await job.progress(0.1, step="collect", key="job.msg.export.collect")
        assets = await st.repo.query("assets", {"campaign_id": campaign_id}, limit=1000)
        videos = [a for a in assets if a["kind"] == "video" and (a.get("status") == "approved" or not approved_only)]
        extra = [a for a in assets if a["kind"] in {"subtitle"} or (a["kind"] == "image" and ("storyboard" in a.get("tags", []) or "poster" in a.get("tags", [])))]
        arts = {k: await st.latest(campaign_id, k) for k in ("brief", "strategy", "script", "storyboard", "voice")}
        files: dict[str, bytes] = {}
        for a in videos + extra:
            folder = {"video": "videos", "subtitle": "captions", "image": "keyframes"}[a["kind"]]
            files[f"{folder}/{a['name']}"] = await st.asset_bytes(a)
        for a in videos:
            prov = await st.repo.query("provenance", {"asset_id": a["id"]}, order_by="created_at", desc=True, limit=1)
            if prov:
                files[f"provenance/{a['name']}.c2pa.json"] = json.dumps({"manifest": prov[0]["manifest"], "manifest_hash": prov[0]["manifest_hash"], "signature": prov[0]["signature"]}, indent=2).encode()
        await job.progress(0.6, step="build", key="job.msg.export.build")
        perf = await st.repo.query("performance", {"campaign_id": campaign_id}, pk=campaign_id, limit=5000)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "platform", "variant_id", "impressions", "clicks", "views", "completes", "conversions", "spend", "revenue"])
        for r in perf:
            w.writerow([r.get(c, "") for c in ("date", "platform", "variant_id", "impressions", "clicks", "views", "completes", "conversions", "spend", "revenue")])
        files["performance.csv"] = buf.getvalue().encode()
        summary = {"campaign": {k: camp.get(k) for k in ("id", "name", "markets", "channels", "status")}, "brief": (arts["brief"] or {}).get("fields"), "territory": next((t for t in (arts["strategy"] or {}).get("territories", []) if t["id"] == (arts["strategy"] or {}).get("selected_territory_id")), None), "script": {k: (arts["script"] or {}).get(k) for k in ("title", "duration_s", "beats", "cta", "legal")}, "approved_only": approved_only, "exported_at": now_iso(), "synthetic_data": True}
        files["campaign.json"] = json.dumps(summary, indent=2, default=str).encode()
        manifest = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
        files["manifest.json"] = json.dumps({"files": manifest, "generator": "SwarmAI Spotlight", "note": t("export.manifest_note", lang)}, indent=2, ensure_ascii=False).encode()
        files["README.txt"] = t("export.readme", lang).encode()
        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in files.items():
                z.writestr(name, data)
        await job.progress(0.9, step="store", key="job.msg.export.store")
        asset = await st.put_asset(campaign_id=campaign_id, name=f"campaign-pack-{campaign_id}.zip", data=zbuf.getvalue(), mime="application/zip", kind="archive", actor=actor, tags=["export", "campaign-pack"], source="export", index=False, meta={"files": len(files), "approved_only": approved_only})
        await st.audit(campaign_id, actor, "campaign.exported", {"asset_id": asset["id"]}, {"files": len(files), "size": asset["size"]})
        _ = s
        return {"asset_id": asset["id"], "files": sorted(files), "size": asset["size"], "download": f"/api/library/assets/{asset['id']}/content?download=true"}

    return await submit_job(request, "campaign.export", run, campaign_id, "job.title.export", "CS-22", wait)


@router.get("/api/campaigns/{campaign_id}/exports")
async def exports(request: Request, campaign_id: str) -> dict[str, Any]:
    rows = await studio(request).repo.query("assets", {"campaign_id": campaign_id, "kind": "archive"}, order_by="created_at", desc=True, limit=20)
    return {"exports": [{k: v for k, v in r.items() if k != "blob"} for r in rows]}


FEATURE = Feature(id="CS-22", summary="Roles (Admin, Brand Manager, Creative Director, Creative, Legal, Agency guest) enforced on the API, Teams/Slack-compatible webhooks (SSRF-guarded), campaign-pack zip export, REST API + OpenAPI.", router=router)
