"""CC-21 Security, identity, RBAC: roles enforced at the API (default deny for staff capabilities), Entra-ready JWT validation, demo role switcher
(clearly labelled, switchable off), access audit, retention settings. The endpoint matrix is introspected from the live route table, never hand-written."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.routing import APIRoute

from ...core.rbac import PERMISSIONS, ROLES, Actor, actor_from_request, require
from ...core.registry import EPIC_E, FeatureInfo
from ..compliance import RETENTION

FEATURES = [
    FeatureInfo(
        "CC-21", "Security, identity, RBAC", EPIC_E, "P1", "/security", "/api/security",
        "Seven roles enforced at the API, Entra-ready JWT validation (issuer, audience, signature via JWKS, expiry, roles), clearly labelled demo role switcher, access audit for transcript/record views, retention settings, managed-identity-only access to Azure.",
    ),
]  # fmt: skip

router = APIRouter(prefix="/api/security", tags=["security (CC-21)"])

ROLE_BLURB = {
    "customer": "Anonymous end customer using the widget / call page", "agent": "Human agent: console, assist, wrap-up, customer 360", "supervisor": "Supervisor: live console, take-over, approvals, whisper",
    "qa": "QA analyst: reviews, calibration, VoC", "wfm": "Workforce planner: forecast and staffing", "admin": "Administrator: everything incl. configuration, seeding, outage simulation",
    "auditor": "Read-only auditor: audit logs, QA, metrics, masked customer data",
}  # fmt: skip


def _iter_routes(routes: Any, prefix: str = ""):
    """FastAPI >= 0.16x nests included routers lazily (`_IncludedRouter`); walk them to reach every APIRoute with its full path."""
    for r in routes:
        if isinstance(r, APIRoute):
            yield prefix, r
        elif hasattr(r, "original_router"):
            yield from _iter_routes(r.original_router.routes, prefix + (getattr(r.include_context, "prefix", "") or ""))


def endpoint_matrix(app: Any) -> list[dict[str, Any]]:
    """One row per HTTP endpoint: the permissions it requires (`public` when it has no `require(...)` dependency) and the roles that pass."""
    rows = []
    for prefix, route in _iter_routes(app.routes):
        perms: tuple[str, ...] = ()
        for dep in route.dependant.dependencies:
            p = getattr(dep.call, "permissions", None)
            if p:
                perms = tuple(p)
        allowed = [r for r in ROLES if not perms or "*" in PERMISSIONS[r] or any(p in PERMISSIONS[r] for p in perms)]
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            rows.append({"method": method, "path": prefix + route.path, "requires": list(perms) or None, "public": not perms, "roles": allowed})
    return sorted(rows, key=lambda r: (r["path"], r["method"]))


@router.get("/whoami")
async def whoami(request: Request) -> dict[str, Any]:
    a = actor_from_request(request)
    perms = sorted(PERMISSIONS.get(a.role, set()))
    s = request.app.state.services.settings
    return {"role": a.role, "user": a.user, "source": a.source, "permissions": perms, "auth_mode": s.auth_mode, "label": "demo authentication (role switcher)" if a.source == "demo" else "Microsoft Entra ID"}


@router.get("/matrix")
async def matrix(request: Request, _: Actor = Depends(require("security.read", "audit.read"))) -> dict[str, Any]:
    rows = endpoint_matrix(request.app)
    groups: dict[str, dict[str, Any]] = {}
    for r in rows:
        g = "/".join(r["path"].split("/")[:3]) if r["path"].startswith("/api/") else r["path"]
        grp = groups.setdefault(g, {"group": g, "endpoints": 0, "public": 0, "roles_any": set()})
        grp["endpoints"] += 1
        grp["public"] += r["public"]
        if not r["public"]:
            grp["roles_any"].update(r["roles"])
    return {
        "roles": [{"role": r, "description": ROLE_BLURB[r], "permissions": sorted(PERMISSIONS[r])} for r in ROLES], "endpoints": rows, "groups": [{**g, "roles_any": sorted(g["roles_any"])} for g in groups.values()],
        "totals": {"endpoints": len(rows), "public": sum(r["public"] for r in rows), "protected": sum(not r["public"] for r in rows)},
        "principle": "staff capabilities are default-deny: an endpoint without a role requirement is public by design (health, chat start, KB search, customer-facing flows) and listed here",
    }  # fmt: skip


@router.get("/settings")
async def settings(request: Request, _: Actor = Depends(require("security.read", "audit.read"))) -> dict[str, Any]:
    svc = request.app.state.services
    s = svc.settings
    return {
        "auth_mode": s.auth_mode, "demo_role_switcher": s.auth_mode == "demo", "demo_label": "demo authentication - the role switcher is for the sandbox only; set AUTH_MODE=entra for real deployments",
        "entra": {"tenant_id": s.entra_tenant_id or None, "audience": s.entra_audience or None, "validation": "RS256 signature via tenant JWKS, issuer, audience, expiry and role claims (app roles)", "container_apps_builtin_auth": "az containerapp auth microsoft update ... (Authentication blade) - documented in README"},
        "identity": {"azure_access": "user-assigned managed identity + RBAC (Cosmos data plane, Storage Blob Data Contributor, Cognitive Services OpenAI/Speech/User, AcrPull, Monitoring Metrics Publisher)", "keys": "none: no API keys or connection strings; Cosmos local auth, Storage shared-key use and Application Insights local auth are not used"},
        "transport": {"tls": "HTTPS only (Container Apps ingress), TLS 1.2+", "headers": ["Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy"], "ws_origin_check": True, "rate_limits": {"per_ip_per_min": s.rate_limit_ip_per_min, "ai_per_ip_per_min": s.rate_limit_ai_ip_per_min, "global_per_min": s.rate_limit_global_per_min}},
        "retention": RETENTION, "access_audit": "who viewed which transcript / record (Agent, Supervisor, QA, Auditor) - GET /api/security/access-audit",
    }  # fmt: skip


@router.get("/access-audit")
async def access_audit(request: Request, limit: int = 100, action: str | None = None, _: Actor = Depends(require("audit.read", "security.read"))) -> dict[str, Any]:
    svc = request.app.state.services
    where = {"action": action} if action else None
    rows = await svc.access_audit.recent(max(1, min(limit, 300)), where)
    return {"entries": rows, "verify": await svc.access_audit.verify(), "readonly": True}
