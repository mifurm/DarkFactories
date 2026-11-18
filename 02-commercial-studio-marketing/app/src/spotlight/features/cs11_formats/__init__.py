"""CS-11 Format factory & versioning — 16:9 / 9:16 / 1:1 / 4:5 reframes and 6/15/30 s cutdowns from the master, version tree."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...core.guardian_service import evaluate, subject_from_spot, summarize
from ...core.jobs import JobContext
from ...deps import mutate_limit, spend_limit
from ...domain.formats import plan_cutdown, reframe
from ...errors import GuardianBlocked, NotFound, ValidationFailed
from ...i18n import render_message, t
from ...registry import Feature
from ...roles import Actor, require
from ...video.spec import ASPECTS, SAFE_AREAS, RenderSpec
from ..common import studio
from ..cs08_spot import post_render, render_spec_to_asset, spot_quality
from ..jobs_util import submit_job

router = APIRouter(prefix="/api/campaigns/{campaign_id}/formats", tags=["CS-11 Format Factory"])


def _format_progress(label: str, variant: dict[str, Any], n: int, total: int) -> dict[str, Any]:
    """Catalog key + params for the 'rendering this version' progress line (a cutdown is named by its length, an aspect by its ratio)."""
    if variant.get("cutdown_s") is not None:
        return {"key": "job.msg.formats.cutdown", "params": {"seconds": variant["cutdown_s"], "n": n + 1, "total": total}}
    return {"key": "job.msg.formats.render", "params": {"label": label, "n": n + 1, "total": total}}


class FormatsIn(BaseModel):
    spot_id: str | None = None
    aspects: list[str] = Field(default_factory=lambda: ["9:16", "1:1", "4:5"])
    cutdowns: list[int] = Field(default_factory=lambda: [6])
    cutdown_aspect: str = "16:9"


async def _master(st: Any, camp: dict[str, Any], spot_id: str | None) -> dict[str, Any]:
    art = await (st.artifact(camp["id"], spot_id, "spot") if spot_id else st.gate_artifact(camp, "spot"))
    if not art:
        raise ValidationFailed("Render the master spot first (CS-08).", code="master_missing")
    return art


@router.post("/generate", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def generate(request: Request, campaign_id: str, body: FormatsIn | None = None, wait: bool = False, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    body = body or FormatsIn()
    bad = [a for a in body.aspects if a not in ASPECTS] + ([body.cutdown_aspect] if body.cutdown_aspect not in ASPECTS else [])
    if bad:
        raise ValidationFailed(f"unsupported aspect(s) {bad}; use {list(ASPECTS)}", code="bad_aspect", params={"aspects": ", ".join(bad), "supported": ", ".join(ASPECTS)})
    if len(body.aspects) + len(body.cutdowns) > 8:
        raise ValidationFailed("at most 8 versions per request", code="too_many")
    st = studio(request)
    camp = await st.campaign(campaign_id)
    master = await _master(st, camp, body.spot_id)
    if (master.get("guardian") or {}).get("verdict") == "block":
        raise GuardianBlocked("The master spot has open Guardian failures; fix them (auto-revise) before deriving formats.", code="guardian_blocked", key="err.guardian_blocked.master")

    async def run(job: JobContext) -> dict[str, Any]:
        s = request.app.state.services
        camp = await st.campaign(campaign_id)
        master = await _master(st, camp, body.spot_id)
        base = RenderSpec.model_validate(master["spec"])
        plan: list[tuple[str, RenderSpec, dict[str, Any], dict[str, Any]]] = []
        for a in body.aspects:
            if a == base.aspect:
                continue
            plan.append((f"{a}", reframe(base, a), {"aspect": a, "lang": base.lang, "cutdown_s": None}, {}))
        for c in body.cutdowns:
            spec, info = plan_cutdown(reframe(base, body.cutdown_aspect) if body.cutdown_aspect != base.aspect else base, c)
            plan.append((f"{c}s cutdown", spec, {"aspect": spec.aspect, "lang": base.lang, "cutdown_s": c}, info))
        out = []
        cinematic = base.quality == "cinematic"  # a cinematic master gives cinematic versions: clips natively per aspect, cutdowns from the cached clips
        for n, (label, spec, variant, info) in enumerate(plan):
            lo, hi = 0.05 + 0.9 * n / max(1, len(plan)), 0.05 + 0.9 * (n + 1) / max(1, len(plan))
            await job.progress(lo, step=label, **_format_progress(label, variant, n, len(plan)))
            art = await render_spec_to_asset(s, st, camp, spec, script_id=master.get("script_id"), storyboard_id=master.get("storyboard_id"), voice_id=master.get("voice_id"), talent=master.get("talent", []), actor=actor, job=job.slice(lo, hi) if cinematic else None, parent_id=master["id"], lineage_kind=spec.lineage.kind, variant=variant, markets=master.get("markets"))
            art["format_notes"] = info
            art = await post_render(s, st, camp, art, actor)
            out.append({"artifact_id": art["id"], "label": label, "aspect": spec.aspect, "duration": art["probe"]["duration"], "guardian": art["guardian"]["verdict"], "video_asset_id": art["assets"]["video"]})
        await st.audit(campaign_id, actor, "formats.generated", {"master": master["id"]}, {"versions": [o["label"] for o in out]})
        return {"versions": out, "master_id": master["id"]}

    return await submit_job(request, "formats.generate", run, campaign_id, "job.title.formats", "CS-11", wait, timeout=178, title_params={"formats": len(body.aspects), "cutdowns": len(body.cutdowns)}, lane="motion" if spot_quality(master) == "cinematic" else None)


@router.get("/tree")
async def tree(request: Request, campaign_id: str) -> dict[str, Any]:
    """Version tree: master → formats / cutdowns / localized versions."""
    st = studio(request)
    await st.campaign(campaign_id)
    spots = await st.artifacts(campaign_id, "spot")
    nodes = []
    for a in spots:
        v = a.get("variant") or {}
        label = " · ".join(x for x in [v.get("aspect"), (t("format.label.cutdown", s=v["cutdown_s"]) if v.get("cutdown_s") else None), (v.get("lang", "").upper() if a.get("lineage_kind") == "localized" else None)] if x) or t("format.label.master")
        lineage = a["spec"].get("lineage") or {}
        keys = lineage.get("note_keys") or []
        notes = [render_message(k.get("key"), k.get("params"), n) for k, n in zip(keys, lineage.get("notes", []), strict=False)] if keys else lineage.get("notes", [])
        nodes.append({"id": a["id"], "parent_id": a.get("parent_id"), "kind": a.get("lineage_kind", "master"), "label": label, "aspect": a["spec"]["aspect"], "lang": a["spec"]["lang"], "duration": a["probe"]["duration"], "status": a["status"], "guardian": a.get("guardian"), "video_asset_id": a["assets"]["video"], "poster_asset_id": a["assets"]["poster"], "created_at": a["created_at"], "version": a["version"], "notes": notes})
    return {"nodes": nodes, "roots": [n["id"] for n in nodes if not n["parent_id"]]}


class ApproveVersions(BaseModel):
    spot_ids: list[str] = Field(min_length=1, max_length=20)


@router.post("/versions/approve", dependencies=[Depends(mutate_limit)])
async def approve_versions(request: Request, campaign_id: str, body: ApproveVersions, actor: Actor = Depends(require("approve"))) -> dict[str, Any]:
    """Approve derived versions (formats / cutdowns / localizations). Blocked while the Guardian has open failures."""
    s = request.app.state.services
    st = studio(request)
    camp = await st.campaign(campaign_id)
    done, refused = [], []
    for sid in body.spot_ids:
        art = await st.artifact(campaign_id, sid, "spot")
        report, _ = await evaluate(s, subject_from_spot(camp, art, markets=art.get("markets")))
        art["guardian"] = summarize(report)
        if report.verdict == "block":
            refused.append({"id": sid, "reason": "open Guardian failures", "rules": [f.rule_id for f in report.findings if f.severity == "block" and not f.waived]})
            await st.save_artifact(art)
            continue
        art["status"] = "approved"
        await st.save_artifact(art)
        for key in ("video", "srt", "poster"):
            a = await st.asset(art["assets"][key], campaign_id)
            a["status"] = "approved"
            await st.save_asset(a)
        done.append(sid)
        await st.audit(campaign_id, actor, "formats.version_approved", {"artifact_id": sid}, {"label": (art.get("variant") or {})})
    if not done and refused:
        raise GuardianBlocked("None of the versions could be approved: open Guardian failures.", code="guardian_blocked", details={"refused": refused}, key="err.guardian_blocked.versions")
    return {"approved": done, "refused": refused}


@router.get("/templates")
async def templates(request: Request, campaign_id: str) -> dict[str, Any]:
    return {"aspects": {a: {"size": list(sz), "safe_area": SAFE_AREAS[a]} for a, sz in ASPECTS.items()}, "overlays": ["logo bug (top-right, safe area)", "AI-disclosure badge (top-left)", "burned-in captions (bottom safe area)", "legal supers (above captions)", "brand end card (logo, tagline, CTA, URL, legal)"], "cutdowns": [6, 15, 30]}


__all__ = ["NotFound"]
FEATURE = Feature(id="CS-11", summary="Reframe a master to 16:9/9:16/1:1/4:5 with per-scene focal points + safe areas, 6/15/30 s cutdowns by scene priority, template overlays, version tree.", router=router)
