"""Connector contract tests (CC-20): the same suite runs against the mock CRM/OMS, the Dynamics 365 / Dataverse adapter and the generic REST adapter,
the HTTP ones against in-process mocked servers (no tenant, no network). Adapter-specific checks cover OData query construction, paging, auth header,
4xx/5xx handling and 429 Retry-After throttling. Used by the unit tests and by the CRM page ("Run contract tests")."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .crm import ConnectorError, DataverseConnector, GenericRestConnector, MockCrmConnector

GUID = "5a1f0c2e-1b7d-4c1e-9f0a-0a1b2c3d4e5f"
EMAIL = "anna.becker@example.com"
ORDER = "CH-100231"
BASE = "https://org.crm4.dynamics.com"


# ------------------------------------------------------------------------------------------------------- fake Dataverse server
class FakeDataverse:
    """Minimal OData v4 server: contacts, salesorders (server-driven paging), incidents, annotations, tasks, throttling and error injection."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.throttled = False
        self.transport = httpx.MockTransport(self.handle)
        self.contact = {"contactid": GUID, "firstname": "Anna", "lastname": "Becker", "fullname": "Anna Becker", "emailaddress1": EMAIL, "telephone1": "+49 30 5550 4412", "address1_line1": "Lindenstraße 12", "address1_postalcode": "10969", "address1_city": "Berlin", "address1_country": "DE", "cc_language": "de", "cc_vip": False, "cc_vulnerable": False}  # fmt: skip

    def handle(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if req.headers.get("Authorization") != "Bearer test-token":
            return httpx.Response(401, json={"error": {"message": "unauthorised"}})
        path, params = req.url.path.replace("/api/data/v9.2", ""), dict(req.url.params)
        if path == f"/contacts({'throttle'})":
            if not self.throttled:
                self.throttled = True
                return httpx.Response(429, headers={"Retry-After": "2"}, json={"error": {"message": "throttled"}})
            return httpx.Response(200, json={**self.contact, "contactid": "throttle"})
        if path == "/contacts(boom)":
            return httpx.Response(500, json={"error": {"message": "server error"}})
        if path == "/contacts(bad)":
            return httpx.Response(400, json={"error": {"message": "bad request"}})
        if path == f"/contacts({GUID})":
            return httpx.Response(200, json=self.contact)
        if path.startswith("/contacts("):
            return httpx.Response(404, json={"error": {"message": "not found"}})
        if req.method == "GET" and path == "/contacts":
            f = params.get("$filter", "")
            return httpx.Response(200, json={"value": [self.contact] if f"'{EMAIL}'" in f else []})
        if req.method == "GET" and path == "/salesorders":
            f = params.get("$filter", "")
            if "ordernumber eq" in f:
                return httpx.Response(200, json={"value": [{"salesorderid": "so-1", "ordernumber": ORDER, "statecode": 3, "totalamount": 379.0, "createdon": "2026-10-02T09:00:00Z", "_customerid_value": GUID, "cc_carrier": "NordFreight", "cc_trackingid": "NO123", "order_details": [{"productname": "Nordby 2-seater sofa (grey)", "quantity": 1, "priceperunit": 379.0}]}]})
            if "$skiptoken" in params:
                return httpx.Response(200, json={"value": [{"ordernumber": "CH-100233", "statecode": 1, "totalamount": 59.0, "createdon": "2026-08-01T09:00:00Z", "_customerid_value": GUID}]})
            nxt = f"{BASE}/api/data/v9.2/salesorders?$filter=_customerid_value eq {GUID}&$skiptoken=2"
            return httpx.Response(200, json={"value": [{"ordernumber": ORDER, "statecode": 3, "totalamount": 379.0, "createdon": "2026-10-02T09:00:00Z", "_customerid_value": GUID}, {"ordernumber": "CH-100232", "statecode": 2, "totalamount": 129.0, "createdon": "2026-09-02T09:00:00Z", "_customerid_value": GUID}], "@odata.nextLink": nxt})
        if req.method == "GET" and path == "/incidents":
            return httpx.Response(200, json={"value": [{"incidentid": "i-1", "ticketnumber": "CAS-0001", "title": "Damaged on delivery", "statecode": 0, "prioritycode": 1, "createdon": "2026-10-05T10:00:00Z"}]})
        if req.method == "GET" and path == "/annotations":
            return httpx.Response(200, json={"value": [{"annotationid": "a-1", "subject": "Concierge wrap-up", "notetext": "Refund issued", "createdon": "2026-10-06T10:00:00Z"}]})
        if req.method == "POST" and path in ("/annotations", "/tasks", "/incidents"):
            return httpx.Response(204, headers={"OData-EntityId": f"{BASE}/api/data/v9.2{path}(new-id)"})
        return httpx.Response(404, json={"error": {"message": f"no route {req.method} {path}"}})


async def _token() -> str:
    return "test-token"


# ------------------------------------------------------------------------------------------------------- fake generic REST server
class FakeRest:
    """A non-OData CRM with its own field names (nested) and cursor paging; the connector maps it by configuration only."""

    FIELD_MAP = {"id": "cust_id", "first_name": "profile.given", "last_name": "profile.family", "email": "profile.mail", "phone": "profile.tel", "language": "prefs.lang", "market": "prefs.market", "tier": "segment", "vulnerable": "flags.vulnerable", "address.street": "addr.line", "address.postal_code": "addr.zip", "address.city": "addr.town", "address.country": "addr.cc"}  # fmt: skip
    ORDER_MAP = {"id": "order_no", "customer_id": "cust_id", "status": "state", "total": "amount", "placed_at": "created", "carrier": "carrier", "tracking_id": "tracking"}

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self.handle)
        self.customer = {"cust_id": "C-77", "profile": {"given": "Anna", "family": "Becker", "mail": EMAIL, "tel": "+49 30 5550 4412"}, "prefs": {"lang": "de", "market": "DE"}, "segment": "standard", "flags": {"vulnerable": False}, "addr": {"line": "Lindenstraße 12", "zip": "10969", "town": "Berlin", "cc": "DE"}}  # fmt: skip

    def handle(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        path = req.url.path
        if path == "/customers" and req.method == "GET":
            return httpx.Response(200, json={"items": [self.customer] if req.url.params.get("q") == EMAIL else []})
        if path == "/customers/C-77":
            return httpx.Response(200, json=self.customer)
        if path.startswith("/customers/") and path.count("/") == 2:
            return httpx.Response(404, json={"error": "not found"})
        if path == "/customers/C-77/orders":
            if req.url.params.get("cursor") == "2":
                return httpx.Response(200, json={"items": [{"order_no": "CH-100233", "cust_id": "C-77", "state": "processing", "amount": 59.0, "created": "2026-08-01T09:00:00Z"}]})
            return httpx.Response(200, json={"items": [{"order_no": ORDER, "cust_id": "C-77", "state": "delivered", "amount": 379.0, "created": "2026-10-02T09:00:00Z", "carrier": "NordFreight", "tracking": "NO123", "items": [{"name": "Nordby 2-seater sofa (grey)", "qty": 1, "price": 379.0}]}], "next": "/customers/C-77/orders?cursor=2"})
        if path == f"/orders/{ORDER}":
            return httpx.Response(200, json={"order_no": ORDER, "cust_id": "C-77", "state": "delivered", "amount": 379.0, "created": "2026-10-02T09:00:00Z"})
        if path.startswith("/orders/"):
            return httpx.Response(404, json={"error": "not found"})
        if path == "/customers/C-77/cases" and req.method == "GET":
            return httpx.Response(200, json={"items": [{"id": "K-1", "summary": "Damaged on delivery", "status": "open", "priority": "high", "created_at": "2026-10-05T10:00:00Z"}]})
        if path == "/customers/C-77/timeline":
            return httpx.Response(200, json={"items": [{"ts": "2026-10-05T10:00:00Z", "type": "case", "title": "Case opened"}, {"ts": "2026-10-06T10:00:00Z", "type": "note", "title": "Wrap-up"}]})
        if req.method == "POST" and path.startswith("/customers/C-77/"):
            return httpx.Response(201, json={"id": "new-1"})
        return httpx.Response(404, json={"error": f"no route {path}"})


# ------------------------------------------------------------------------------------------------------- the contract
def _check(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


async def run_contract(conn: Any, *, email: str, customer_id: str, order_id: str, unknown_customer: str, label: str) -> list[dict[str, Any]]:
    """The behaviour every connector must provide (the agent tools rely on exactly this)."""
    out: list[dict[str, Any]] = []
    found = await conn.find_customer(email)
    out.append(_check(f"{label}: find_customer by e-mail", bool(found) and found["email"] == email and found.get("id"), json.dumps({k: found.get(k) for k in ("id", "email")}) if found else "none"))
    cust = await conn.get_customer(customer_id)
    need = ("id", "first_name", "email", "phone", "language", "tier", "address")
    out.append(_check(f"{label}: get_customer returns the internal model", bool(cust) and all(k in cust for k in need) and isinstance(cust["address"], dict) and "postal_code" in cust["address"], ""))
    out.append(_check(f"{label}: get_customer(unknown) -> None", await conn.get_customer(unknown_customer) is None))
    order = await conn.get_order(order_id)
    out.append(_check(f"{label}: get_order", bool(order) and order["id"] == order_id and "status" in order and "total" in order, ""))
    orders = await conn.list_orders(customer_id)
    out.append(_check(f"{label}: list_orders (all pages)", len(orders) >= 1 and all("id" in o and "status" in o for o in orders), f"{len(orders)} orders"))
    tl = await conn.timeline(customer_id)
    out.append(_check(f"{label}: timeline newest first", bool(tl) and all(tl[i]["ts"] >= tl[i + 1]["ts"] for i in range(len(tl) - 1)), f"{len(tl)} events"))
    note = await conn.write_note(customer_id, "Refund issued; customer informed.", "cv_contract")
    out.append(_check(f"{label}: write_note", bool(note), ""))
    task = await conn.write_task(customer_id, "Call back about the pickup", "AG-01", 2, "cv_contract")
    out.append(_check(f"{label}: write_task", bool(task), ""))
    case = await conn.create_case(customer_id, "Damaged on delivery", "damage", "high", "cv_contract", order_id, ["Photos received"])
    out.append(_check(f"{label}: create_case", bool(case), ""))
    cases = await conn.list_cases(customer_id)
    out.append(_check(f"{label}: list_cases", isinstance(cases, list) and len(cases) >= 1, f"{len(cases)} cases"))
    return out


async def dataverse_checks() -> list[dict[str, Any]]:
    """OData query construction, headers, paging, throttling and error handling against the fake Dataverse."""
    srv = FakeDataverse()
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    conn = DataverseConnector(BASE, _token, srv.transport, sleep=fake_sleep)
    out = await run_contract(conn, email=EMAIL, customer_id=GUID, order_id=ORDER, unknown_customer="00000000-0000-0000-0000-000000000000", label="dataverse")
    reqs = srv.requests
    out.append(_check("dataverse: bearer token + OData version headers on every request", all(r.headers.get("Authorization") == "Bearer test-token" and r.headers.get("OData-Version") == "4.0" for r in reqs), f"{len(reqs)} requests"))
    find = next(r for r in reqs if r.url.path.endswith("/contacts") and "$filter" in r.url.params)
    out.append(_check("dataverse: contact lookup uses $filter/$select/$top", "emailaddress1 eq" in find.url.params["$filter"] and "$select" in find.url.params and find.url.params.get("$top") == "1", find.url.params["$filter"]))
    qn = [r for r in reqs if r.url.path.endswith("/salesorders") and "_customerid_value" in r.url.params.get("$filter", "")]
    out.append(_check("dataverse: paging follows @odata.nextLink", len(qn) == 2 and "$skiptoken" in qn[1].url.params, f"{len(qn)} page requests"))
    out.append(_check("dataverse: orders $expand order details, newest first", "order_details" in qn[0].url.params.get("$expand", "") and qn[0].url.params.get("$orderby") == "createdon desc"))
    await srv_escape(conn, srv)
    notes = [r for r in reqs if r.method == "POST" and r.url.path.endswith("/annotations")]
    body = json.loads(notes[0].content) if notes else {}
    out.append(_check("dataverse: note payload binds the contact (objectid_contact@odata.bind)", body.get("objectid_contact@odata.bind") == f"/contacts({GUID})" and "notetext" in body, json.dumps(body)[:120]))
    inc = [r for r in reqs if r.method == "POST" and r.url.path.endswith("/incidents")]
    ibody = json.loads(inc[0].content) if inc else {}
    out.append(_check("dataverse: case payload (incident) binds customerid_contact", ibody.get("customerid_contact@odata.bind") == f"/contacts({GUID})" and ibody.get("prioritycode") == 1, json.dumps(ibody)[:120]))
    # throttling: 429 + Retry-After then success
    t0 = len(srv.requests)
    got = await conn.get_customer("throttle")
    out.append(_check("dataverse: 429 honours Retry-After then succeeds", bool(got) and sleeps and sleeps[-1] == 2.0 and len(srv.requests) - t0 == 2, f"slept {sleeps}"))
    # 5xx -> retries then ConnectorError
    t0, s0 = len(srv.requests), len(sleeps)
    try:
        await conn.get_customer("boom")
        ok, status = False, 0
    except ConnectorError as exc:
        ok, status = exc.retryable, exc.status
    out.append(_check("dataverse: 5xx retried with back-off, then ConnectorError(retryable)", ok and status == 500 and len(srv.requests) - t0 == 4 and len(sleeps) - s0 == 3, f"{len(srv.requests) - t0} attempts"))
    # 4xx -> fail fast
    t0 = len(srv.requests)
    try:
        await conn.get_customer("bad")
        ok, status = False, 0
    except ConnectorError as exc:
        ok, status = not exc.retryable, exc.status
    out.append(_check("dataverse: 4xx fails fast (no retry)", ok and status == 400 and len(srv.requests) - t0 == 1, ""))
    # auth failure
    async def bad_token() -> str:
        return "wrong"

    bad = DataverseConnector(BASE, bad_token, srv.transport, sleep=fake_sleep)
    try:
        await bad.get_customer(GUID)
        ok401 = False
    except ConnectorError as exc:
        ok401 = exc.status == 401
    out.append(_check("dataverse: 401 surfaces as ConnectorError", ok401))
    return out


async def srv_escape(conn: DataverseConnector, srv: FakeDataverse) -> None:
    await conn.find_customer("o'brien@example.com")  # quote must be doubled in the OData filter
    last = srv.requests[-1]
    assert "o''brien@example.com" in last.url.params["$filter"]


async def rest_checks() -> list[dict[str, Any]]:
    srv = FakeRest()
    conn = GenericRestConnector("https://crm.example.test", _token, FakeRest.FIELD_MAP, srv.transport, order_map=FakeRest.ORDER_MAP)
    out = await run_contract(conn, email=EMAIL, customer_id="C-77", order_id=ORDER, unknown_customer="C-00", label="generic-rest")
    cust = await conn.get_customer("C-77")
    out.append(_check("generic-rest: arbitrary nested JSON mapped by configuration", bool(cust) and cust["first_name"] == "Anna" and cust["address"]["city"] == "Berlin" and cust["language"] == "de", ""))
    pages = [r for r in srv.requests if r.url.path == "/customers/C-77/orders"]
    out.append(_check("generic-rest: follows the `next` cursor", len(pages) >= 2 and pages[1].url.params.get("cursor") == "2", f"{len(pages)} requests"))
    out.append(_check("generic-rest: bearer token sent", all(r.headers.get("Authorization") == "Bearer test-token" for r in srv.requests)))
    return out


async def mock_checks(backoffice: Any) -> list[dict[str, Any]]:
    conn = MockCrmConnector(backoffice)
    cust = await backoffice.get_customer("CU-1001")
    return await run_contract(conn, email=cust["email"], customer_id="CU-1001", order_id=ORDER, unknown_customer="CU-0000", label="mock-crm")


async def contract_report(backoffice: Any) -> dict[str, Any]:
    t0 = time.perf_counter()
    report: dict[str, Any] = {}
    for name, fn in (("mock-crm", lambda: mock_checks(backoffice)), ("dynamics365-dataverse", dataverse_checks), ("generic-rest", rest_checks)):
        try:
            checks = await fn()
        except Exception as exc:  # a crashing adapter is a failed adapter, not a failed report
            checks = [_check(f"{name}: suite crashed", False, f"{type(exc).__name__}: {exc}"[:200])]
        report[name] = {"passed": sum(c["ok"] for c in checks), "total": len(checks), "checks": checks}
    report["summary"] = {"passed": sum(r["passed"] for r in report.values() if "total" in r), "total": sum(r["total"] for r in report.values() if "total" in r), "ms": round((time.perf_counter() - t0) * 1000)}
    return report
