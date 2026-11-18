"""Security (CC-21): JWT validation with locally generated keys, role enforcement at the API (default-deny for staff capabilities), the demo role
switcher being inert in Entra mode, HTTP hardening, rate limits and the tamper-evident audit chain."""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from concierge.core import rbac
from concierge.core.config import Settings
from concierge.core.rbac import PERMISSIONS, ROLES, Actor, JwtValidator
from concierge.core.security import RateLimiter, ws_origin_ok
from concierge.main import create_app

TENANT, AUDIENCE = "11111111-2222-3333-4444-555555555555", "api://concierge-test"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWKS = {"keys": [{**RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True), "kid": "k1", "alg": "RS256", "use": "sig"}]}


def token(roles=("Agent",), *, key=KEY, kid="k1", aud=AUDIENCE, iss=None, exp_in=600, **extra) -> str:
    claims = {"iss": iss or f"https://login.microsoftonline.com/{TENANT}/v2.0", "aud": aud, "exp": int(time.time()) + exp_in, "preferred_username": "hannah@contoso-home.example", "roles": list(roles), **extra}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def validator() -> JwtValidator:
    return JwtValidator(TENANT, AUDIENCE, jwks=JWKS)


def test_valid_entra_tokens_map_app_roles_to_concierge_roles(validator):
    a = validator.validate(token(["Agent"]))
    assert (a.role, a.user, a.source) == ("agent", "hannah@contoso-home.example", "entra")
    assert validator.validate(token(["Agent", "Supervisor"])).role == "supervisor", "the more privileged of the mapped roles wins"
    assert validator.validate(token(["Admin", "Agent"])).role == "admin", "the most privileged mapped role wins"
    assert validator.validate(token(["QA"])).role == "qa" and validator.validate(token(["WFM"])).role == "wfm" and validator.validate(token(["Auditor"])).role == "auditor"
    assert validator.validate(token(["Finance"])).role == "customer", "unknown app roles never grant staff access"
    assert validator.validate(token([])).role == "customer"
    v1 = token(["Agent"], iss=f"https://sts.windows.net/{TENANT}/")
    assert validator.validate(v1).role == "agent", "v1.0 issuer accepted"


@pytest.mark.parametrize(
    ("label", "kwargs", "error"),
    [
        ("wrong audience", dict(aud="api://someone-else"), jwt.InvalidAudienceError),
        ("wrong issuer", dict(iss="https://login.microsoftonline.com/other-tenant/v2.0"), jwt.InvalidIssuerError),
        ("expired", dict(exp_in=-30), jwt.ExpiredSignatureError),
        ("unknown signing key id", dict(kid="not-in-jwks"), jwt.InvalidTokenError),
        ("signed with a different key", dict(key=OTHER_KEY), jwt.InvalidSignatureError),
    ],
)
def test_invalid_tokens_are_rejected(validator, label, kwargs, error):
    with pytest.raises(error):
        validator.validate(token(**kwargs))


def test_algorithm_confusion_and_unsigned_tokens_are_rejected(validator):
    hs = jwt.encode({"iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "aud": AUDIENCE, "exp": int(time.time()) + 60, "roles": ["Admin"]}, "shared-secret-padded-to-32-bytes!!", algorithm="HS256", headers={"kid": "k1"})
    with pytest.raises(jwt.PyJWTError):
        validator.validate(hs)
    unsigned = jwt.encode({"iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "aud": AUDIENCE, "exp": int(time.time()) + 60, "roles": ["Admin"]}, None, algorithm="none", headers={"kid": "k1"})
    with pytest.raises(jwt.PyJWTError):
        validator.validate(unsigned)
    with pytest.raises(jwt.PyJWTError):
        validator.validate("not.a.jwt")


# ----------------------------------------------------------------------------------------------------------- API level
@pytest.fixture
def demo_client():
    with TestClient(create_app(Settings(mode="offline"))) as c:
        yield c


@pytest.fixture
def entra_client(validator):
    rbac.set_validator(validator)
    try:
        with TestClient(create_app(Settings(mode="offline", auth_mode="entra"))) as c:
            yield c
    finally:
        rbac.set_validator(None)


def call(c, method, path, role=None, **kw):
    return c.request(method, path, headers={"X-Demo-Role": role} if role else {}, **kw)


# role -> (allowed GETs, forbidden GETs)
ROLE_MATRIX = {
    "customer": ([], ["/api/assist/console", "/api/supervisor/overview", "/api/qa/reviews", "/api/wfm/queues", "/api/security/matrix", "/api/outbound/overview", "/api/evals/runs", "/api/crm/connectors", "/api/rollout/configs"]),
    "agent": (["/api/assist/console?agent_id=AG-08", "/api/kb/stats"], ["/api/supervisor/overview", "/api/qa/reviews", "/api/wfm/queues", "/api/security/access-audit", "/api/evals/runs"]),
    "supervisor": (["/api/supervisor/overview", "/api/outbound/overview", "/api/qa/reviews", "/api/wfm/queues"], ["/api/security/access-audit", "/api/security/matrix"]),
    "qa": (["/api/qa/reviews", "/api/voc/summary"], ["/api/supervisor/overview", "/api/outbound/overview", "/api/wfm/queues"]),
    "wfm": (["/api/wfm/queues"], ["/api/qa/reviews", "/api/supervisor/overview", "/api/outbound/overview"]),
    "auditor": (["/api/security/access-audit", "/api/qa/reviews"], ["/api/supervisor/overview", "/api/assist/console"]),
    "admin": (["/api/supervisor/overview", "/api/qa/reviews", "/api/wfm/queues", "/api/security/access-audit", "/api/outbound/overview"], []),
}


@pytest.mark.parametrize("role", ROLES)
def test_role_matrix_is_enforced_at_the_api(demo_client, role):
    allowed, forbidden = ROLE_MATRIX[role]
    for path in allowed:
        assert call(demo_client, "GET", path, role).status_code == 200, (role, path)
    for path in forbidden:
        r = call(demo_client, "GET", path, role)
        assert r.status_code == 403 and r.json()["detail"]["error"] == "forbidden", (role, path, r.status_code)


def test_every_protected_endpoint_denies_the_anonymous_customer(demo_client):
    matrix = call(demo_client, "GET", "/api/security/matrix", "admin").json()
    protected = [e for e in matrix["endpoints"] if e["requires"] and e["method"] == "GET"]
    assert len(protected) >= 60 and matrix["totals"]["protected"] >= 100
    leaks = []
    for e in protected:
        path = e["path"].replace("{conv_id}", "cv_x").replace("{run_id}", "r").replace("{agent_id}", "AG-01").replace("{customer_id}", "CU-1001")
        path = path.replace("{conv}", "cv_x").replace("{doc_id}", "d").replace("{chunk_id:path}", "c").replace("{call_id}", "c")
        path = "/".join("x" if p.startswith("{") else p for p in path.split("/"))
        r = call(demo_client, "GET", path, "customer")
        if r.status_code != 403:
            leaks.append((path, r.status_code))
    assert not leaks, leaks


def test_post_endpoints_for_staff_actions_reject_customers_and_auditors(demo_client):
    for role in ("customer", "auditor"):
        assert call(demo_client, "POST", "/api/outbound/kill-switch", role, json={"on": True}).status_code == 403
        assert call(demo_client, "POST", "/api/outbound/events", role, json={"trigger": "shipment_delayed"}).status_code == 403
        assert call(demo_client, "POST", "/api/crm/outage", role, json={"on": True}).status_code == 403
        assert call(demo_client, "POST", "/api/evals/runs", role, json={"suite": "core"}).status_code == 403
    assert call(demo_client, "GET", "/api/outbound/overview", "admin").json()["kill_switch"] is False


def test_demo_role_header_is_ignored_in_entra_mode_and_tokens_decide(entra_client, validator):
    assert call(entra_client, "GET", "/api/supervisor/overview", "admin").status_code == 403, "the demo switcher cannot grant access in Entra mode"
    who = entra_client.get("/api/security/whoami", headers={"X-Demo-Role": "admin"}).json()
    assert who["role"] == "customer" and who["source"] == "entra"
    ok = entra_client.get("/api/assist/console?agent_id=AG-08", headers={"Authorization": f"Bearer {token(['Agent'])}"})
    assert ok.status_code == 200
    sup_only = entra_client.get("/api/supervisor/overview", headers={"Authorization": f"Bearer {token(['Agent'])}"})
    assert sup_only.status_code == 403
    assert entra_client.get("/api/supervisor/overview", headers={"Authorization": f"Bearer {token(['Supervisor'])}"}).status_code == 200
    bad = entra_client.get("/api/supervisor/overview", headers={"Authorization": f"Bearer {token(['Admin'], aud='api://other')}"})
    assert bad.status_code == 401
    assert entra_client.get("/api/security/settings", headers={"Authorization": f"Bearer {token(['Admin'])}"}).json()["auth_mode"] == "entra"


def test_permissions_table_is_consistent():
    assert set(PERMISSIONS) == set(ROLES) and PERMISSIONS["admin"] == {"*"}
    assert Actor("admin", "u", "demo").can("anything") and not Actor("customer", "u", "demo").can("agent.console")
    assert not Actor("auditor", "u", "demo").can("outbound.write") and not Actor("auditor", "u", "demo").can("approvals.decide")
    assert Actor("supervisor", "u", "demo").can("approvals.decide") and not Actor("agent", "u", "demo").can("approvals.decide")
    assert not Actor("nobody", "u", "demo").can("chat")


# ---------------------------------------------------------------------------------------------------------- hardening
def test_security_headers_request_ids_and_no_store_on_api(demo_client):
    r = demo_client.get("/healthz")
    h = {k.lower(): v for k, v in r.headers.items()}
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "SAMEORIGIN" and h["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in h["content-security-policy"] and "max-age=" in h["strict-transport-security"]
    assert "microphone=(self)" in h["permissions-policy"] and h["x-request-id"]
    api = demo_client.get("/api/meta", headers={"X-Request-ID": "abc123"})
    assert api.headers["cache-control"] == "no-store" and api.headers["x-request-id"] == "abc123"


def test_request_body_limit_and_rate_limiter():
    with TestClient(create_app(Settings(mode="offline", max_body_bytes=2000))) as c:
        r = c.post("/api/chat/sessions", content=b"x" * 5000, headers={"content-type": "application/json"})
        assert r.status_code == 413 and r.json()["error"] == "payload_too_large"
    lim = RateLimiter()
    assert [lim.allow("k", 3, 60) for _ in range(5)] == [True, True, True, False, False]
    assert lim.allow("other", 3, 60) and lim.allow("k", 3, window=0.0) is True
    lim.reset()
    assert lim.allow("k", 1, 60)


def test_per_ip_mutating_rate_limit_returns_429_with_retry_after():
    with TestClient(create_app(Settings(mode="offline", rate_limit_ip_per_min=5, rate_limit_ai_ip_per_min=1000))) as c:
        codes = [c.post("/api/chat/sessions", json={"language": "en"}).status_code for _ in range(8)]
        assert codes[:5] == [200] * 5 and set(codes[5:]) == {429}
        r = c.post("/api/chat/sessions", json={"language": "en"})
        assert r.headers["retry-after"] == "30" and r.json()["scope"] == "ip-mutating"
        assert c.get("/healthz").status_code == 200, "health probes are never rate limited"


def test_websocket_origin_check():
    assert ws_origin_ok({"host": "app.example.com", "origin": "https://app.example.com"})
    assert not ws_origin_ok({"host": "app.example.com", "origin": "https://evil.example.org"})
    assert ws_origin_ok({"host": "app.example.com"}), "non-browser clients send no Origin"


async def test_audit_chain_is_tamper_evident(svc):
    for i in range(5):
        await svc.audit.log("test.event", actor="t", resource=f"r{i}", detail={"i": i})
    assert (await svc.audit.verify())["ok"]
    rows = await svc.repo.query("audit", order_by="seq")
    rows[2]["resource"] = "tampered"
    await svc.repo.put("audit", rows[2])
    broken = await svc.audit.verify()
    assert broken["ok"] is False and broken["broken_at_seq"] == rows[2]["seq"]
