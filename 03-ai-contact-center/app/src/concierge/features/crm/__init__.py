"""CC-20 Customer 360 & CRM integration layer: connector registry + contract-test runner, merged customer timeline with role-based PII masking,
simulated-outage switch for the graceful-degradation demo."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ...core.rbac import Actor, require
from ...core.redaction import mask_email, mask_phone
from ...core.registry import EPIC_E, FeatureInfo
from ...engine.crm import ConnectorError
from ...engine.crm_contract import contract_report

FEATURES = [
    FeatureInfo(
        "CC-20", "Customer 360 & CRM integration layer", EPIC_E, "P1", "/customers", "/api/crm",
        "Connector abstraction (customer / order / case ports) with a mock CRM/OMS, a Dynamics 365 / Dataverse OData adapter and a config-driven generic REST adapter - verified by a contract suite against mocked HTTP; merged customer timeline with role-based PII masking.",
    ),
]  # fmt: skip

router = APIRouter(prefix="/api/crm", tags=["crm (CC-20)"])


def _mask(cust: dict[str, Any]) -> dict[str, Any]:
    out = dict(cust)
    out["email"] = mask_email(cust.get("email") or "")
    out["phone"] = mask_phone(cust.get("phone") or "")
    addr = dict(cust.get("address") or {})
    if addr:
        addr["street"] = "•••• " + str(addr.get("street", ""))[-3:] if addr.get("street") else None
        out["address"] = addr
    out["masked"] = True
    return out


def _view(cust: dict[str, Any], actor: Actor) -> dict[str, Any]:
    keep = {k: cust.get(k) for k in ("id", "first_name", "last_name", "name", "email", "phone", "language", "market", "tier", "vulnerable", "address", "marketing_consent")}
    keep["name"] = keep.get("name") or f"{keep.get('first_name', '')} {keep.get('last_name', '')}".strip()
    return keep if actor.can("crm.read") else _mask(keep)


@router.get("/connectors")
async def connectors(request: Request, _: Actor = Depends(require("crm.read", "crm.read.masked"))) -> dict[str, Any]:
    svc = request.app.state.services
    crm = svc.ext["crm"]
    return {
        "active": crm.name, "outage_simulated": bool(getattr(crm, "chaos", False)),
        "ports": {"CustomerRecordConnector": ["find_customer", "get_customer", "timeline", "write_note", "write_task"], "OrderConnector": ["get_order", "list_orders"], "CaseConnector": ["list_cases", "create_case"]},
        "adapters": [
            {"name": "mock-crm", "kind": "in-app (Cosmos DB)", "status": "active", "note": "mock CRM/OMS behind the connector interface"},
            {"name": "dynamics365-dataverse", "kind": "OData v4 Web API (contacts, salesorders, incidents, annotations, tasks)", "status": "contract-tested against mocked HTTP", "note": "no tenant connected; auth = Entra bearer token (managed identity)"},
            {"name": "generic-rest", "kind": "REST / OData, field mapping by configuration (dotted paths)", "status": "contract-tested against mocked HTTP", "note": "cursor and @odata.nextLink paging; Retry-After throttling"},
        ],
        "tools_through_connector": ["lookup_order", "verify (customer lookup)", "check_return_eligibility", "create_ticket", "wrap-up notes/tasks (CC-09)"],
        "resilience": "429/503 honour Retry-After, 5xx and transport errors back off, 4xx fail fast; a failed connector call is a failed tool step and repeated failures escalate to a human",
    }  # fmt: skip


@router.post("/contract-tests")
async def contract_tests(request: Request, _: Actor = Depends(require("crm.read"))) -> dict[str, Any]:
    return await contract_report(request.app.state.services.backoffice)


class ChaosBody(BaseModel):
    on: bool


@router.post("/outage")
async def outage(body: ChaosBody, request: Request, actor: Actor = Depends(require("admin"))) -> dict[str, Any]:
    """Simulate a CRM outage: customer/order reads fail with ConnectorError -> tool failures -> escalation to a human (never a crash)."""
    svc = request.app.state.services
    svc.ext["crm"].chaos = body.on
    await svc.audit.log("crm.outage_simulation", actor=f"{actor.role}:{actor.user}", detail={"on": body.on})
    return {"outage_simulated": body.on}


@router.get("/customers")
async def search(request: Request, q: str = "", actor: Actor = Depends(require("crm.read", "crm.read.masked"))) -> list[dict[str, Any]]:
    svc = request.app.state.services
    custs = await svc.repo.query("bo_customers")
    needle = q.strip().lower()
    digits = "".join(c for c in needle if c.isdigit())
    rows = []
    for c in sorted(custs, key=lambda x: x["id"]):
        hay = f"{c['id']} {c.get('name', '')} {c['email']} {c['market']}".lower()
        if not needle or needle in hay or (len(digits) >= 4 and digits in "".join(ch for ch in c["phone"] if ch.isdigit())):
            v = _view(c, actor)
            rows.append({"id": c["id"], "name": v["name"], "tier": c["tier"], "market": c["market"], "language": c["language"], "email": v["email"], "city": (c.get("address") or {}).get("city"), "vulnerable": bool(c.get("vulnerable")), "note": c.get("note")})
        if len(rows) >= 25:
            break
    return rows


@router.get("/customers/{customer_id}/360")
async def customer_360(customer_id: str, request: Request, reveal: str | None = None, actor: Actor = Depends(require("crm.read", "crm.read.masked"))) -> dict[str, Any]:
    svc = request.app.state.services
    try:
        cust = await svc.oms.get_customer(customer_id)
        orders = await svc.oms.list_orders(customer_id) if cust else []
        events = await svc.ext["crm"].timeline(customer_id) if cust else []
    except ConnectorError as exc:
        raise HTTPException(502, {"error": "connector_unavailable", "message": str(exc)}) from exc
    if cust is None:
        raise HTTPException(404, "customer not found")
    convs = [d for d in await svc.repo.query("conversations", order_by="updated_at", desc=True, limit=300) if (d.get("identity") or {}).get("customer_id") == customer_id and not d.get("eval_run_id")]
    interactions = []
    for d in convs:
        first = next((m["text"] for m in d["messages"] if m["role"] == "customer"), "")
        interactions.append({"ts": d["created_at"], "type": "conversation", "id": d["id"], "title": f"{d['channel'].replace('_', ' ')} - {(d.get('understanding') or {}).get('intent', 'contact')}", "detail": first[:140], "handler": d["handler"], "status": d["status"], "sentiment": (d.get("sentiment_trajectory") or [0])[-1], "qa": (d.get("qa") or {}).get("overall"), "ai": d["handler"] == "ai"})  # fmt: skip
    timeline = sorted([*events, *interactions], key=lambda e: e["ts"], reverse=True)
    view = _view(cust, actor)
    if reveal in ("phone", "email") and actor.can("crm.read"):
        await svc.access_audit.log("pii.reveal", actor=f"{actor.role}:{actor.user}", resource=customer_id, detail={"field": reveal})
    await svc.access_audit.log("crm.customer_viewed", actor=f"{actor.role}:{actor.user}", resource=customer_id, detail={"masked": bool(view.get("masked"))})
    sent = [i["sentiment"] for i in interactions]
    return {
        "customer": view, "orders": [{"id": o["id"], "status": o["status"], "total": o.get("total"), "placed_at": o.get("placed_at"), "items": [i["name"] if isinstance(i, dict) else i for i in o.get("items", [])][:3]} for o in orders],
        "timeline": timeline[:120], "stats": {"orders": len(orders), "interactions": len(interactions), "ai_interactions": sum(1 for i in interactions if i["ai"]), "avg_sentiment": round(sum(sent) / len(sent), 2) if sent else None, "last_contact": interactions[0]["ts"] if interactions else None, "generated_at": time.time()},
        "connector": svc.ext["crm"].name, "masking": "full" if actor.can("crm.read") else "masked (role has no PII access)",
    }  # fmt: skip
