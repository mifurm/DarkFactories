"""Customer 360 & CRM integration layer (CC-20): connector abstraction (customer / order / case ports) with the mock CRM/OMS, a Dynamics 365 /
Dataverse (OData Web API) adapter and a generic REST/OData adapter whose field mapping is configuration. HTTP adapters take an injectable httpx
transport so they are tested against mocked HTTP; authentication is a bearer-token callable (Entra) - never a stored secret.

Every adapter speaks the same internal model, so the agent tools do not change when the connector is swapped:
  customer: {id, first_name, last_name, name, email, phone, language, market, tier, vulnerable, address{street,postal_code,city,country}, marketing_consent}
  order:    {id, customer_id, status, total, placed_at, items[{name,qty,price}], carrier, tracking_id}
  case:     {id, customer_id, summary, status, priority, created_at}
Resilience: 429/503 honour Retry-After (bounded), 5xx and transport errors retry with back-off, 4xx fail fast; all failures surface as `ConnectorError`
which the tool layer turns into a failed step (and, after repeated failures, an escalation to a human)."""

from __future__ import annotations

import asyncio
import email.utils
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

TokenProvider = Callable[[], Awaitable[str]]
Sleep = Callable[[float], Awaitable[None]]
MAX_PAGES = 10


class ConnectorError(Exception):
    def __init__(self, status: int, message: str, *, retryable: bool = False, source: str = "") -> None:
        self.status, self.retryable, self.source = status, retryable, source
        super().__init__(f"{source or 'connector'}: HTTP {status}: {message}")


class CustomerRecordConnector(Protocol):
    name: str

    async def find_customer(self, query: str) -> dict[str, Any] | None: ...

    async def get_customer(self, customer_id: str) -> dict[str, Any] | None: ...

    async def timeline(self, customer_id: str) -> list[dict[str, Any]]: ...

    async def write_note(self, customer_id: str, text: str, conv_id: str) -> dict[str, Any]: ...

    async def write_task(self, customer_id: str, title: str, owner: str, due_days: int, conv_id: str, idx: int = 0) -> dict[str, Any]: ...


class OrderConnector(Protocol):
    async def get_order(self, order_id: str) -> dict[str, Any] | None: ...

    async def list_orders(self, customer_id: str) -> list[dict[str, Any]]: ...


class CaseConnector(Protocol):
    async def list_cases(self, customer_id: str) -> list[dict[str, Any]]: ...

    async def create_case(self, customer_id: str | None, summary: str, category: str, priority: str, conv_id: str, order_id: str | None = None, notes: list[str] | None = None) -> dict[str, Any]: ...


class CrmConnector(CustomerRecordConnector, OrderConnector, CaseConnector, Protocol):
    """Everything the agent stack needs from a CRM/OMS."""


def _retry_after(resp: httpx.Response, default: float = 1.0) -> float:
    raw = resp.headers.get("Retry-After")
    if not raw:
        return default
    if raw.strip().isdigit():
        return float(raw)
    try:
        when = email.utils.parsedate_to_datetime(raw)
        return max(0.0, (when - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError):
        return default


async def send_with_retry(
    http: httpx.AsyncClient, method: str, url: str, *, headers: dict[str, str], source: str, retries: int = 3, sleep: Sleep = asyncio.sleep, max_wait: float = 30.0, allow_404: bool = False, **kw: Any,
) -> httpx.Response | None:  # fmt: skip
    """429/503 honour Retry-After; 5xx and transport errors back off; other 4xx fail fast; 404 can be tolerated (returns None)."""
    attempt = 0
    while True:
        try:
            resp = await http.request(method, url, headers=headers, **kw)
        except httpx.TransportError as exc:
            if attempt >= retries:
                raise ConnectorError(0, f"transport error {type(exc).__name__}", retryable=True, source=source) from exc
            await sleep(min(0.2 * 2**attempt, max_wait))
            attempt += 1
            continue
        if resp.status_code in (429, 503) and attempt < retries:
            await sleep(min(_retry_after(resp), max_wait))
            attempt += 1
            continue
        if resp.status_code >= 500 and attempt < retries:
            await sleep(min(0.2 * 2**attempt, max_wait))
            attempt += 1
            continue
        if resp.status_code == 404 and allow_404:
            return None
        if resp.status_code >= 400:
            raise ConnectorError(resp.status_code, resp.text[:200], retryable=resp.status_code == 429 or resp.status_code >= 500, source=source)
        return resp


def _epoch(value: Any) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


# ------------------------------------------------------------------------------------------------------------- mock CRM / OMS
class MockCrmConnector:
    """CRM/OMS backed by the in-app back-office collections (Cosmos DB): returns the internal model unchanged."""

    name = "mock-crm"

    def __init__(self, backoffice: Any) -> None:
        self.bo = backoffice
        self.chaos = False  # simulated outage switch (CC-20 graceful-degradation demo)

    def _up(self) -> None:
        if self.chaos:
            raise ConnectorError(503, "CRM unavailable (simulated outage)", retryable=True, source=self.name)

    async def find_customer(self, query: str) -> dict[str, Any] | None:
        self._up()
        return await self.bo.find_customer(query)

    async def get_customer(self, customer_id: str) -> dict[str, Any] | None:
        self._up()
        return await self.bo.get_customer(customer_id)

    async def get_order(self, order_id: str) -> dict[str, Any] | None:
        self._up()
        return await self.bo.get_order(order_id)

    async def list_orders(self, customer_id: str) -> list[dict[str, Any]]:
        self._up()
        return await self.bo.list_orders(customer_id)

    async def list_cases(self, customer_id: str) -> list[dict[str, Any]]:
        self._up()
        return await self.bo.tickets_for(customer_id)

    async def create_case(self, customer_id: str | None, summary: str, category: str, priority: str, conv_id: str, order_id: str | None = None, notes: list[str] | None = None) -> dict[str, Any]:
        self._up()
        return await self.bo.create_ticket(customer_id, summary, category, priority, conv_id, order_id, notes or [])

    async def timeline(self, customer_id: str) -> list[dict[str, Any]]:
        self._up()
        events = await self.bo.timeline(customer_id)
        notes = await self.bo.repo.query("bo_tickets", {"customer_id": customer_id, "kind": {"$in": ["note", "task"]}})
        for n in notes:
            events.append({"ts": n["created_at"], "type": n["kind"], "id": n["id"], "title": ("CRM note" if n["kind"] == "note" else f"Task: {n['summary']}"), "detail": n.get("text") or n["summary"]})
        events.sort(key=lambda e: e["ts"], reverse=True)
        return events

    async def write_note(self, customer_id: str, text: str, conv_id: str) -> dict[str, Any]:
        doc = {"id": f"NOTE-{conv_id}", "kind": "note", "customer_id": customer_id, "summary": "Conversation wrap-up", "text": text[:2000], "category": "note", "priority": "low", "status": "closed", "notes": [], "created_at": time.time(), "conv_id": conv_id, "order_id": None}
        await self.bo.repo.put("bo_tickets", doc)  # deterministic id => re-running wrap-up is idempotent
        return doc

    async def write_task(self, customer_id: str, title: str, owner: str, due_days: int, conv_id: str, idx: int = 0) -> dict[str, Any]:
        doc = {"id": f"TASK-{conv_id}-{idx}", "kind": "task", "customer_id": customer_id, "summary": title, "owner": owner, "due_at": time.time() + due_days * 86400, "category": "task", "priority": "normal", "status": "open", "notes": [], "created_at": time.time(), "conv_id": conv_id, "order_id": None}
        await self.bo.repo.put("bo_tickets", doc)
        return doc


# ------------------------------------------------------------------------------------------------------------- Dynamics 365 / Dataverse
CONTACT_SELECT = "contactid,firstname,lastname,fullname,emailaddress1,telephone1,address1_line1,address1_postalcode,address1_city,address1_country,cc_language,cc_vip,cc_vulnerable,donotemail,donotphone,donotsendmm"
ORDER_SELECT = "salesorderid,ordernumber,statecode,totalamount,createdon,_customerid_value,cc_carrier,cc_trackingid"


class DataverseConnector:
    """Dynamics 365 / Dataverse Web API (OData v4): contacts (customers), salesorders (orders), incidents (cases), annotations (notes) and tasks."""

    name = "dynamics365-dataverse"
    STATE = {0: "processing", 1: "processing", 2: "shipped", 3: "delivered", 4: "cancelled"}

    def __init__(self, base_url: str, token_provider: TokenProvider, transport: httpx.AsyncBaseTransport | None = None, *, sleep: Sleep = asyncio.sleep, page_size: int = 50) -> None:
        self.base = base_url.rstrip("/") + "/api/data/v9.2"
        self._token = token_provider
        self._http = httpx.AsyncClient(transport=transport, timeout=15)
        self._sleep = sleep
        self.page_size = page_size

    async def _req(self, method: str, path: str, *, allow_404: bool = False, **kw: Any) -> httpx.Response | None:
        headers = {"Authorization": f"Bearer {await self._token()}", "OData-MaxVersion": "4.0", "OData-Version": "4.0", "Accept": "application/json", **kw.pop("headers", {})}
        return await send_with_retry(self._http, method, f"{self.base}{path}", headers=headers, source=self.name, sleep=self._sleep, allow_404=allow_404, **kw)

    async def _all(self, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
        """Follows @odata.nextLink (server-driven paging) up to MAX_PAGES pages."""
        rows: list[dict[str, Any]] = []
        resp = await self._req("GET", path, params=params, headers={"Prefer": f"odata.maxpagesize={self.page_size}"})
        for _ in range(MAX_PAGES):
            assert resp is not None
            data = resp.json()
            rows += data.get("value", [])
            nxt = data.get("@odata.nextLink")
            if not nxt:
                break
            headers = {"Authorization": f"Bearer {await self._token()}", "OData-MaxVersion": "4.0", "OData-Version": "4.0", "Accept": "application/json", "Prefer": f"odata.maxpagesize={self.page_size}"}
            resp = await send_with_retry(self._http, "GET", nxt, headers=headers, source=self.name, sleep=self._sleep)
        return rows

    @staticmethod
    def _esc(value: str) -> str:
        return value.replace("'", "''")

    @staticmethod
    def map_contact(c: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": c.get("contactid"), "first_name": c.get("firstname"), "last_name": c.get("lastname"), "name": c.get("fullname"), "email": c.get("emailaddress1"), "phone": c.get("telephone1"),
            "language": c.get("cc_language") or "en", "market": c.get("address1_country"), "tier": "vip" if c.get("cc_vip") else "standard", "vulnerable": bool(c.get("cc_vulnerable")),
            "address": {"street": c.get("address1_line1"), "postal_code": c.get("address1_postalcode"), "city": c.get("address1_city"), "country": c.get("address1_country")},
            "marketing_consent": {"email": not c.get("donotemail", False), "voice": not c.get("donotphone", False), "sms": not c.get("donotsendmm", False)}, "source": DataverseConnector.name,
        }  # fmt: skip

    def map_order(self, o: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": o.get("ordernumber"), "customer_id": o.get("_customerid_value"), "status": self.STATE.get(o.get("statecode"), "unknown"), "total": o.get("totalamount"), "placed_at": _epoch(o.get("createdon")),
            "items": [{"name": d.get("productname"), "qty": d.get("quantity"), "price": d.get("priceperunit")} for d in o.get("order_details", [])], "carrier": o.get("cc_carrier"), "tracking_id": o.get("cc_trackingid"), "source": self.name,
        }  # fmt: skip

    async def find_customer(self, query: str) -> dict[str, Any] | None:
        q = query.strip()
        if q.upper().startswith("CH-"):
            rows = await self._all("/salesorders", {"$filter": f"ordernumber eq '{self._esc(q.upper())}'", "$select": "_customerid_value", "$top": "1"})
            return await self.get_customer(rows[0]["_customerid_value"]) if rows else None
        safe = self._esc(q)
        rows = await self._all("/contacts", {"$filter": f"emailaddress1 eq '{safe}' or telephone1 eq '{safe}'", "$select": CONTACT_SELECT, "$top": "1"})
        return self.map_contact(rows[0]) if rows else None

    async def get_customer(self, customer_id: str) -> dict[str, Any] | None:
        r = await self._req("GET", f"/contacts({customer_id})", params={"$select": CONTACT_SELECT}, allow_404=True)
        return self.map_contact(r.json()) if r is not None else None

    async def list_orders(self, customer_id: str) -> list[dict[str, Any]]:
        rows = await self._all("/salesorders", {"$filter": f"_customerid_value eq {customer_id}", "$select": ORDER_SELECT, "$expand": "order_details($select=productname,quantity,priceperunit)", "$orderby": "createdon desc"})
        return [self.map_order(o) for o in rows]

    async def get_order(self, order_id: str) -> dict[str, Any] | None:
        rows = await self._all("/salesorders", {"$filter": f"ordernumber eq '{self._esc(order_id.upper())}'", "$select": ORDER_SELECT, "$expand": "order_details($select=productname,quantity,priceperunit)", "$top": "1"})
        return self.map_order(rows[0]) if rows else None

    async def list_cases(self, customer_id: str) -> list[dict[str, Any]]:
        rows = await self._all("/incidents", {"$filter": f"_customerid_value eq {customer_id}", "$select": "incidentid,ticketnumber,title,statecode,prioritycode,createdon", "$orderby": "createdon desc"})
        return [{"id": r.get("ticketnumber") or r.get("incidentid"), "customer_id": customer_id, "summary": r.get("title"), "status": {0: "open", 1: "closed", 2: "cancelled"}.get(r.get("statecode"), "open"), "priority": {1: "high", 2: "normal", 3: "low"}.get(r.get("prioritycode"), "normal"), "created_at": _epoch(r.get("createdon"))} for r in rows]

    async def create_case(self, customer_id: str | None, summary: str, category: str, priority: str, conv_id: str, order_id: str | None = None, notes: list[str] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"title": summary[:200], "description": "\n".join(notes or [])[:2000] or f"Created by Concierge ({conv_id})", "prioritycode": {"high": 1, "normal": 2, "low": 3}.get(priority, 2), "caseorigincode": 3}
        if customer_id:
            body["customerid_contact@odata.bind"] = f"/contacts({customer_id})"
        r = await self._req("POST", "/incidents", json=body)
        assert r is not None
        return {"id": r.headers.get("OData-EntityId", ""), "status": r.status_code, "summary": summary, "customer_id": customer_id}

    async def timeline(self, customer_id: str) -> list[dict[str, Any]]:
        notes = await self._all("/annotations", {"$filter": f"_objectid_value eq {customer_id}", "$select": "annotationid,subject,notetext,createdon", "$orderby": "createdon desc"})
        cases = await self.list_cases(customer_id)
        events = [{"ts": _epoch(a.get("createdon")), "type": "note", "id": a.get("annotationid"), "title": a.get("subject"), "detail": a.get("notetext")} for a in notes]
        events += [{"ts": c["created_at"], "type": "case", "id": c["id"], "title": c["summary"], "detail": c["status"]} for c in cases]
        return sorted(events, key=lambda e: e["ts"], reverse=True)

    async def write_note(self, customer_id: str, text: str, conv_id: str) -> dict[str, Any]:
        body = {"subject": f"Concierge wrap-up {conv_id}", "notetext": text[:2000], "objectid_contact@odata.bind": f"/contacts({customer_id})"}
        r = await self._req("POST", "/annotations", json=body)
        assert r is not None
        return {"id": r.headers.get("OData-EntityId", ""), "status": r.status_code}

    async def write_task(self, customer_id: str, title: str, owner: str, due_days: int, conv_id: str, idx: int = 0) -> dict[str, Any]:
        body = {"subject": title, "description": f"Created by Concierge ({conv_id}); owner {owner}", "scheduledend": datetime.fromtimestamp(time.time() + due_days * 86400, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "regardingobjectid_contact_task@odata.bind": f"/contacts({customer_id})"}
        r = await self._req("POST", "/tasks", json=body)
        assert r is not None
        return {"id": r.headers.get("OData-EntityId", ""), "status": r.status_code}


# ------------------------------------------------------------------------------------------------------------- generic REST / OData
DEFAULT_FIELD_MAP = {"id": "id", "first_name": "first_name", "last_name": "last_name", "name": "name", "email": "email", "phone": "phone", "language": "language", "market": "market", "tier": "tier"}
DEFAULT_ORDER_MAP = {"id": "id", "customer_id": "customer_id", "status": "status", "total": "total", "placed_at": "placed_at", "carrier": "carrier", "tracking_id": "tracking_id"}


def _dig(raw: dict[str, Any], path: str) -> Any:
    cur: Any = raw
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


class GenericRestConnector:
    """Configurable REST/OData connector: external field names (dotted paths allowed) are mapped onto the internal model by configuration."""

    name = "generic-rest"

    def __init__(
        self, base_url: str, token_provider: TokenProvider | None = None, field_map: dict[str, str] | None = None, transport: httpx.AsyncBaseTransport | None = None, odata: bool = False, *,
        order_map: dict[str, str] | None = None, sleep: Sleep = asyncio.sleep,
    ) -> None:  # fmt: skip
        self.base = base_url.rstrip("/")
        self._token = token_provider
        self.map = field_map or dict(DEFAULT_FIELD_MAP)
        self.order_map = order_map or dict(DEFAULT_ORDER_MAP)
        self.odata = odata
        self._http = httpx.AsyncClient(transport=transport, timeout=15)
        self._sleep = sleep

    async def _req(self, method: str, path: str, *, allow_404: bool = False, **kw: Any) -> httpx.Response | None:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {await self._token()}"
        return await send_with_retry(self._http, method, f"{self.base}{path}" if path.startswith("/") else path, headers=headers, source=self.name, sleep=self._sleep, allow_404=allow_404, **kw)

    def _norm(self, raw: dict[str, Any]) -> dict[str, Any]:
        out = {internal: _dig(raw, external) for internal, external in self.map.items()}
        if not out.get("name"):
            out["name"] = " ".join(x for x in (out.get("first_name"), out.get("last_name")) if x) or None
        out.setdefault("tier", "standard")
        out["tier"] = out["tier"] or "standard"
        out["vulnerable"] = bool(_dig(raw, self.map.get("vulnerable", "vulnerable")))
        out["address"] = {k: _dig(raw, self.map.get(f"address.{k}", f"address.{k}")) for k in ("street", "postal_code", "city", "country")}
        out["source"] = self.name
        return out

    def _norm_order(self, raw: dict[str, Any]) -> dict[str, Any]:
        out = {internal: _dig(raw, external) for internal, external in self.order_map.items()}
        out["placed_at"] = _epoch(out.get("placed_at"))
        out["items"] = [{"name": i.get("name"), "qty": i.get("qty", 1), "price": i.get("price")} for i in raw.get("items", []) if isinstance(i, dict)]
        out["source"] = self.name
        return out

    async def _pages(self, path: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        resp = await self._req("GET", path, params=params)
        for _ in range(MAX_PAGES):
            assert resp is not None
            data = resp.json()
            rows += data.get("value", data.get("items", data if isinstance(data, list) else []))
            nxt = data.get("@odata.nextLink") or data.get("next") if isinstance(data, dict) else None
            if not nxt:
                break
            resp = await self._req("GET", nxt)
        return rows

    async def find_customer(self, query: str) -> dict[str, Any] | None:
        params = {"$filter": f"email eq '{query.replace(chr(39), chr(39) * 2)}'", "$top": "1"} if self.odata else {"q": query, "limit": "1"}
        rows = await self._pages("/customers", params)
        return self._norm(rows[0]) if rows else None

    async def get_customer(self, customer_id: str) -> dict[str, Any] | None:
        r = await self._req("GET", f"/customers/{customer_id}", allow_404=True)
        return self._norm(r.json()) if r is not None else None

    async def list_orders(self, customer_id: str) -> list[dict[str, Any]]:
        return [self._norm_order(o) for o in await self._pages(f"/customers/{customer_id}/orders")]

    async def get_order(self, order_id: str) -> dict[str, Any] | None:
        r = await self._req("GET", f"/orders/{order_id}", allow_404=True)
        return self._norm_order(r.json()) if r is not None else None

    async def list_cases(self, customer_id: str) -> list[dict[str, Any]]:
        rows = await self._pages(f"/customers/{customer_id}/cases")
        return [{"id": c.get("id"), "customer_id": customer_id, "summary": c.get("summary") or c.get("title"), "status": c.get("status", "open"), "priority": c.get("priority", "normal"), "created_at": _epoch(c.get("created_at"))} for c in rows]

    async def create_case(self, customer_id: str | None, summary: str, category: str, priority: str, conv_id: str, order_id: str | None = None, notes: list[str] | None = None) -> dict[str, Any]:
        r = await self._req("POST", f"/customers/{customer_id}/cases", json={"summary": summary[:200], "category": category, "priority": priority, "order_id": order_id, "notes": notes or [], "source_conversation": conv_id})
        assert r is not None
        return {"status": r.status_code, **(r.json() if r.content else {})}

    async def timeline(self, customer_id: str) -> list[dict[str, Any]]:
        rows = await self._pages(f"/customers/{customer_id}/timeline")
        return sorted(({**e, "ts": _epoch(e.get("ts"))} for e in rows), key=lambda e: e["ts"], reverse=True)

    async def write_note(self, customer_id: str, text: str, conv_id: str) -> dict[str, Any]:
        r = await self._req("POST", f"/customers/{customer_id}/notes", json={"text": text[:2000], "source_conversation": conv_id})
        assert r is not None
        return {"status": r.status_code, **(r.json() if r.content else {})}

    async def write_task(self, customer_id: str, title: str, owner: str, due_days: int, conv_id: str, idx: int = 0) -> dict[str, Any]:
        r = await self._req("POST", f"/customers/{customer_id}/tasks", json={"title": title, "owner": owner, "due_in_days": due_days, "source_conversation": conv_id})
        assert r is not None
        return {"status": r.status_code, **(r.json() if r.content else {})}


# ------------------------------------------------------------------------------------------------------------- facade used by the tools
class ConnectorBackOffice:
    """Back-office facade seen by the agent tools: customer, order and case access goes through the configured connector (swappable); the
    transactional OMS operations (returns, appointments, refunds, credits) pass through to the order-management port."""

    def __init__(self, bo: Any, crm: Any) -> None:
        self._bo, self.crm = bo, crm

    async def get_customer(self, cid: str) -> dict[str, Any] | None:
        return await self.crm.get_customer(cid) if cid else None

    async def find_customer(self, identifier: str) -> dict[str, Any] | None:
        return await self.crm.find_customer(identifier)

    async def get_order(self, oid: str) -> dict[str, Any] | None:
        return await self.crm.get_order(oid)

    async def list_orders(self, cid: str) -> list[dict[str, Any]]:
        return await self.crm.list_orders(cid)

    async def tickets_for(self, cid: str) -> list[dict[str, Any]]:
        return await self.crm.list_cases(cid)

    async def create_ticket(self, customer_id: str | None, summary: str, category: str, priority: str, conv_id: str, order_id: str | None = None, notes: list[str] | None = None) -> dict[str, Any]:
        return await self.crm.create_case(customer_id, summary, category, priority, conv_id, order_id, notes)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._bo, name)
