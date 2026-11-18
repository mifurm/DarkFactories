"""CS-13 Approval workflow & audit trail — stage gates, roles, comments, SLAs, versioned assets, hash-chained audit log."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...core.gates import GATE_BY_ID, GATES, stage_overview
from ...core.guardian_service import (
    evaluate,
    subject_from_brief,
    subject_from_copy,
    subject_from_script,
    subject_from_spot,
    subject_from_storyboard,
    subject_from_strategy,
    summarize,
)
from ...deps import mutate_limit, svc
from ...errors import AppError, Conflict, Forbidden, GuardianBlocked, NotFound, ValidationFailed
from ...registry import Feature
from ...roles import Actor, Role, get_actor, require
from ...util import new_id, now, now_iso, parse_iso
from ..common import studio

router = APIRouter(tags=["CS-13 Approvals & Audit"])
ADMIN_ACTS_AS = {Role.ADMIN}


async def _fresh_guardian(st: Any, s: Any, camp: dict[str, Any], art: dict[str, Any]) -> dict[str, Any]:
    kind = art["kind"]
    images: dict[str, bytes] = {}
    if kind == "brief":
        subject = subject_from_brief(camp, art)
    elif kind == "strategy":
        subject = subject_from_strategy(camp, art)
    elif kind == "script":
        subject = subject_from_script(camp, art)
    elif kind == "copy":
        subject = subject_from_copy(camp, art)
    elif kind == "storyboard":
        subject, images = await subject_from_storyboard(st, camp, art)
    else:
        subject = subject_from_spot(camp, art, markets=art.get("markets"))
    report, _ = await evaluate(s, subject, image_bytes=images, persist=True, untrusted_text=art.get("raw_text") if kind == "brief" else None)
    art["guardian"] = summarize(report)
    await st.save_artifact(art)
    return {"report": report, "blocking": [f for f in report.findings if f.severity == "block" and not f.waived]}


def _sla(doc: dict[str, Any]) -> str:
    if doc["state"] != "pending":
        return "closed"
    due = parse_iso(doc.get("sla_due"))
    if not due:
        return "on_track"
    left = (due - now()).total_seconds()
    return "overdue" if left < 0 else ("due_soon" if left < 6 * 3600 else "on_track")


def _public(doc: dict[str, Any]) -> dict[str, Any]:
    return {**doc, "sla_state": _sla(doc), "pending_roles": [r for r in doc["required_roles"] if r not in {d["role"] for d in doc.get("decisions", []) if d["decision"] == "approve"}]}


class RequestIn(BaseModel):
    stage: str
    artifact_id: str | None = None
    note: str = Field(default="", max_length=500)


@router.post("/api/campaigns/{campaign_id}/approvals", dependencies=[Depends(mutate_limit)])
async def request_approval(request: Request, campaign_id: str, body: RequestIn, actor: Actor = Depends(require("campaign.write"))) -> dict[str, Any]:
    st = studio(request)
    s = svc(request)
    camp = await st.campaign(campaign_id)
    gate = GATE_BY_ID.get(body.stage)
    if not gate:
        raise ValidationFailed(f"unknown stage {body.stage!r}; use one of {[g['id'] for g in GATES]}", code="bad_stage")
    art = await (st.artifact(campaign_id, body.artifact_id, gate["kind"]) if body.artifact_id else st.gate_artifact(camp, gate["kind"]))
    if not art:
        raise NotFound(f"nothing to approve yet for stage '{gate['label']}'", code="artifact_missing")
    existing = await st.repo.query("approvals", {"type": "approval", "artifact_id": art["id"], "stage": body.stage, "state": "pending"}, pk=campaign_id)
    if existing:
        raise Conflict("An approval request is already pending for this version.", code="already_pending", details={"approval_id": existing[0]["id"]})
    g = await _fresh_guardian(st, s, camp, art)
    rep = g["report"]
    art["status"] = "in_review"
    await st.save_artifact(art)
    doc = {
        "id": new_id("apr"), "pk": campaign_id, "campaign_id": campaign_id, "type": "approval", "stage": body.stage, "stage_label": gate["label"], "artifact_id": art["id"], "artifact_kind": art["kind"], "artifact_version": art["version"], "title": art.get("title") or gate["label"],
        "requested_by": actor.to_dict(), "required_roles": gate["roles"], "state": "pending", "decisions": [], "comments": ([{"by": actor.name, "role": actor.role.value, "text": body.note, "at": now_iso()}] if body.note else []),
        "sla_hours": gate["sla_hours"], "sla_due": (now() + timedelta(hours=gate["sla_hours"])).isoformat(timespec="seconds"), "guardian_snapshot": {"verdict": rep.verdict, "score": rep.score, "blocks": len(g["blocking"])}, "created_at": now_iso(),
    }
    await st.repo.upsert("approvals", doc)
    await st.audit(campaign_id, actor, "approval.requested", {"approval_id": doc["id"], "stage": body.stage, "artifact_id": art["id"]}, {"guardian": rep.verdict, "roles": gate["roles"]})
    await s.notifier.emit("approval.requested", {"campaign_id": campaign_id, "campaign": camp["name"], "stage": gate["label"], "roles": gate["roles"], "guardian": rep.verdict})
    return _public(doc)


@router.get("/api/approvals")
async def inbox(request: Request, state: str | None = None, mine: bool = False, campaign_id: str | None = None) -> dict[str, Any]:
    st = studio(request)
    actor = get_actor(request)
    where: dict[str, Any] = {"type": "approval"}
    if state:
        where["state"] = state
    if campaign_id:
        where["campaign_id"] = campaign_id
    rows = await st.repo.query("approvals", where, pk=campaign_id, order_by="created_at", desc=True, limit=200)
    camps = {c["id"]: c["name"] for c in await st.repo.query("campaigns")}
    out = []
    for r in rows:
        p = _public(r)
        p["campaign_name"] = camps.get(r["campaign_id"], r["campaign_id"])
        p["actionable"] = r["state"] == "pending" and (actor.role in ADMIN_ACTS_AS or actor.role.value in p["pending_roles"])
        if mine and not p["actionable"]:
            continue
        out.append(p)
    return {"approvals": out, "role": actor.role.value, "counts": {k: sum(1 for x in out if x["state"] == k) for k in ("pending", "approved", "rejected", "changes_requested")}, "overdue": sum(1 for x in out if x["sla_state"] == "overdue")}


@router.get("/api/campaigns/{campaign_id}/approvals")
async def campaign_approvals(request: Request, campaign_id: str) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)
    rows = await st.repo.query("approvals", {"type": "approval"}, pk=campaign_id, order_by="created_at", desc=True)
    return {"approvals": [_public(r) for r in rows], "pipeline": await stage_overview(st, campaign_id), "gates": GATES}


class DecideIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject|request_changes)$")
    comment: str = Field(default="", max_length=800)
    as_role: str | None = None


@router.post("/api/approvals/{approval_id}/decide", dependencies=[Depends(mutate_limit)])
async def decide(request: Request, approval_id: str, body: DecideIn, actor: Actor = Depends(require("approve"))) -> dict[str, Any]:
    st = studio(request)
    s = svc(request)
    doc = await st.repo.get("approvals", approval_id)
    if not doc or doc.get("type") != "approval":
        raise NotFound("approval not found", code="approval_not_found")
    if doc["state"] != "pending":
        raise Conflict(f"This request is already {doc['state']}.", code="already_decided")
    pending = [r for r in doc["required_roles"] if r not in {d["role"] for d in doc["decisions"] if d["decision"] == "approve"}]
    if actor.role == Role.ADMIN:
        role = body.as_role if body.as_role in pending else (pending[0] if pending else doc["required_roles"][0])
    elif actor.role.value in pending:
        role = actor.role.value
    else:
        raise Forbidden(f"Only {', '.join(pending)} may decide this gate (you are {actor.role.value}).", code="role_forbidden", details={"required_roles": pending})
    camp = await st.campaign(doc["campaign_id"])
    art = await st.artifact(doc["campaign_id"], doc["artifact_id"])
    if body.decision == "approve":
        # gate ordering: earlier gates must be approved first
        order = [g["id"] for g in GATES]
        for earlier in order[: order.index(doc["stage"])]:
            ov = next(o for o in await stage_overview(st, doc["campaign_id"]) if o["gate"] == earlier)
            if ov["artifact_status"] != "approved":
                raise Conflict(f"The '{GATE_BY_ID[earlier]['label']}' gate must be approved before '{doc['stage_label']}'.", code="gate_order", details={"blocked_by": earlier})
        g = await _fresh_guardian(st, s, camp, art)
        if g["blocking"]:
            await st.audit(doc["campaign_id"], actor, "approval.refused_guardian", {"approval_id": approval_id}, {"blocking": [f.rule_id for f in g["blocking"]]})
            raise GuardianBlocked(
                f"Cannot approve with {len(g['blocking'])} open Guardian failure(s): " + "; ".join(f.message for f in g["blocking"][:3]),
                code="guardian_blocked", hint="Run auto-revise, fix the findings, or have Legal waive them with a justification.", details={"findings": [{"id": f.id, "rule": f.rule_id, "message": f.message} for f in g["blocking"]]},
            )
    entry = {"role": role, "by": actor.name, "acted_as": actor.role.value, "decision": body.decision, "comment": body.comment, "at": now_iso()}
    doc["decisions"].append(entry)
    if body.comment:
        doc["comments"].append({"by": actor.name, "role": actor.role.value, "text": body.comment, "at": now_iso()})
    if body.decision == "reject":
        doc["state"], art["status"] = "rejected", "rejected"
    elif body.decision == "request_changes":
        doc["state"], art["status"] = "changes_requested", "draft"
    else:
        done = {d["role"] for d in doc["decisions"] if d["decision"] == "approve"}
        if set(doc["required_roles"]) <= done:
            doc["state"], art["status"] = "approved", "approved"
            doc["closed_at"] = now_iso()
        else:
            art["status"] = "in_review"
    await st.repo.upsert("approvals", doc)
    await st.save_artifact(art)
    if doc["state"] == "approved":
        await _on_approved(st, camp, doc, art)
    await st.audit(doc["campaign_id"], actor, f"approval.{body.decision}", {"approval_id": approval_id, "stage": doc["stage"], "artifact_id": art["id"]}, {"role": role, "state": doc["state"], "comment": body.comment})
    await s.notifier.emit(f"approval.{doc['state']}", {"campaign_id": doc["campaign_id"], "campaign": camp["name"], "stage": doc["stage_label"], "by": actor.name, "decision": body.decision})
    return _public(doc)


async def _on_approved(st: Any, camp: dict[str, Any], doc: dict[str, Any], art: dict[str, Any]) -> None:
    order = [g["id"] for g in GATES]
    nxt = {"brief": "strategy", "concept": "script", "script": "storyboard", "storyboard": "production", "final": "published"}
    camp["stage"] = nxt.get(doc["stage"], camp.get("stage"))
    if doc["stage"] == "final":
        camp["status"] = "approved"
        if art["kind"] == "spot":
            for key in ("video", "srt", "poster"):
                a = await st.asset(art["assets"][key], camp["id"])
                a["status"] = "approved"
                await st.save_asset(a)
    await st.save_campaign(camp)
    _ = order


class CommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=800)


@router.post("/api/approvals/{approval_id}/comment", dependencies=[Depends(mutate_limit)])
async def comment(request: Request, approval_id: str, body: CommentIn, actor: Actor = Depends(require("campaign.write"))) -> dict[str, Any]:
    st = studio(request)
    doc = await st.repo.get("approvals", approval_id)
    if not doc:
        raise NotFound("approval not found", code="approval_not_found")
    doc["comments"].append({"by": actor.name, "role": actor.role.value, "text": body.text, "at": now_iso()})
    await st.repo.upsert("approvals", doc)
    await st.audit(doc["campaign_id"], actor, "approval.commented", {"approval_id": approval_id}, {"text": body.text[:200]})
    return _public(doc)


@router.get("/api/campaigns/{campaign_id}/audit")
async def audit_log(request: Request, campaign_id: str, limit: int = 100) -> dict[str, Any]:
    s = svc(request)
    entries = await s.audit.entries(campaign_id)
    ver = await s.audit.verify(campaign_id)
    return {"chain": campaign_id, "verification": ver, "entries": list(reversed(entries))[: min(limit, 500)], "total": len(entries)}


@router.get("/api/audit/verify")
async def verify_chain(request: Request, chain: str = "global") -> dict[str, Any]:
    return await svc(request).audit.verify(chain)


@router.get("/api/audit/chains")
async def chains(request: Request) -> dict[str, Any]:
    st = studio(request)
    names = ["global", *[c["id"] for c in await st.repo.query("campaigns")]]
    return {"chains": [await svc(request).audit.verify(n) for n in names]}


__all__ = ["AppError"]
FEATURE = Feature(id="CS-13", summary="Stage gates (brief→concept→script→storyboard→final), roles, comments, SLAs, versioned assets, Guardian-gated approvals, immutable hash-chained audit log.", router=router)
