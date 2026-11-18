"""CC-04 Transactional tools / skills: tool catalogue, policy, approvals above cap, human tool execution, audit trail."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.rbac import Actor, require
from ...core.registry import EPIC_A, FeatureInfo
from ...engine.models import now
from ...engine.tools import ToolContext

FEATURES = [
    FeatureInfo(
        "CC-04", "Transactional tools / skills", EPIC_A, "P0", "/tools", "/api/tools",
        "23 policy-guarded tools against a mock back-office: per-agent allow-lists, auth levels, refund cap + approvals, confirmation gate, idempotency keys, hash-chained audit.",
    ),
]  # fmt: skip
SEED_ORDER = 10

router = APIRouter(prefix="/api/tools", tags=["tools (CC-04)"])


async def seed(svc: Any, force: bool) -> dict[str, Any]:
    await svc.configs.load()
    return await svc.backoffice.seed(force=force)


class DecisionBody(BaseModel):
    approve: bool
    note: str = Field("", max_length=300)


class ExecuteBody(BaseModel):
    conversation_id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


@router.get("/catalogue")
async def catalogue(request: Request) -> dict[str, Any]:
    svc = request.app.state.services
    cfg = await svc.configs.active()
    return {"config": cfg.id, "agents": cfg.tools, "tools": svc.tools.catalogue(cfg), "policy": cfg.policy}


@router.get("/approvals")
async def approvals(request: Request, status: str | None = None, _: Actor = Depends(require("agent.console", "supervisor"))) -> list[dict[str, Any]]:
    svc = request.app.state.services
    rows = await svc.repo.query("approvals", {"status": status} if status else None, order_by="created_at", desc=True, limit=100)
    return rows


@router.post("/approvals/{approval_id}/decision")
async def decide(approval_id: str, body: DecisionBody, request: Request, actor: Actor = Depends(require("approvals.decide"))) -> dict[str, Any]:
    svc = request.app.state.services
    appr = await svc.repo.get("approvals", approval_id)
    if not appr:
        raise HTTPException(404, "approval not found")
    if appr["status"] != "pending":
        raise HTTPException(409, f"already {appr['status']}")
    conv = await svc.store.get(appr["conv_id"])
    result: dict[str, Any] | None = None
    if body.approve and conv is not None:
        cfg = await svc.configs.get(conv.config_version) or await svc.configs.active()
        ctx = ToolContext(svc=svc, conv=conv, agent="human", actor=f"human:{actor.user}", cfg=cfg, approved=True)
        async with svc.store.lock(conv.id):
            args = dict(appr["args"])
            if appr["kind"] == "refund":
                o = await svc.oms.get_order(appr["order_id"])
                if o and not await svc.backoffice.returns_for(o["id"]):
                    await svc.tools.execute(ctx, "initiate_return", {"order_id": o["id"], "reason": "damaged", "resolution": "refund"})
                out = await svc.tools.execute(ctx, "issue_refund", {"order_id": appr["order_id"], "amount": appr["amount"], "reason": args.get("reason", "approved refund")})
            else:
                out = await svc.tools.execute(ctx, "goodwill_credit", {"amount": appr["amount"], "reason": args.get("reason", "approved goodwill"), "order_id": appr["order_id"]})
            result = {"status": out.status, **out.data}
            conv.add("system_notice", f"A specialist approved the {appr['kind']} of EUR {appr['amount']:.2f}." if out.status in ("ok", "replayed") else f"The approval could not be completed: {out.data.get('error')}", lang=conv.language, author=actor.user, flags=["approval"])
            await svc.store.save(conv)
    elif conv is not None:
        conv.add("system_notice", f"The {appr['kind']} request of EUR {appr['amount']:.2f} was declined by a specialist.", lang=conv.language, author=actor.user, flags=["approval"])
        await svc.store.save(conv)
    appr.update({"status": "approved" if body.approve else "rejected", "decided_by": actor.user, "decided_at": now(), "note": body.note, "result": result})
    await svc.repo.put("approvals", appr)
    await svc.audit.log("approval.decided", actor=actor.user, resource=approval_id, conv_id=appr["conv_id"], detail={"approve": body.approve, "amount": appr["amount"], "result": (result or {}).get("status")})
    await svc.bus.publish("supervisor", {"type": "approval.decided", "approval": appr})
    return appr


@router.post("/execute")
async def execute_as_human(body: ExecuteBody, request: Request, actor: Actor = Depends(require("tools.human"))) -> dict[str, Any]:
    """A human agent triggers a tool (same policy engine and audit as the AI; no autonomous execution by the copilot)."""
    svc = request.app.state.services
    conv = await svc.store.get(body.conversation_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    if conv.handler == "ai" and actor.role == "agent":
        raise HTTPException(409, "take over the conversation first")
    cfg = await svc.configs.get(conv.config_version) or await svc.configs.active()
    ctx = ToolContext(svc=svc, conv=conv, agent="human", actor=f"human:{actor.user}", cfg=cfg)
    async with svc.store.lock(conv.id):
        out = await svc.tools.execute(ctx, body.tool, body.args)
        await svc.store.save(conv)
    return {"status": out.status, "data": out.data, "record": out.record.model_dump()}


@router.get("/audit")
async def tool_audit(request: Request, conversation_id: str | None = None, limit: int = 60, _: Actor = Depends(require("agent.console", "audit.read", "supervisor"))) -> list[dict[str, Any]]:
    svc = request.app.state.services
    rows = await svc.audit.recent(limit=max(1, min(limit, 300)), where={"conv_id": conversation_id} if conversation_id else None)
    return rows


@router.get("/backoffice/orders/{order_id}")
async def get_order(order_id: str, request: Request, _: Actor = Depends(require("crm.read", "crm.read.masked"))) -> dict[str, Any]:
    o = await request.app.state.services.oms.get_order(order_id)
    if o is None:
        raise HTTPException(404, "order not found")
    return o
