"""Roles & access control (CC-21): demo role switcher (header) or Entra-ready JWT validation (JWKS / app roles)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import HTTPException, Request

ROLES = ["customer", "agent", "supervisor", "qa", "wfm", "admin", "auditor"]

# Capability matrix (documented in /api/security/matrix and the Security page)
PERMISSIONS: dict[str, set[str]] = {
    "customer": {"chat", "voice", "identity.self"},
    "agent": {"agent.console", "assist", "wrapup.edit", "kb.read", "crm.read", "handoff.accept", "tools.human", "metrics.read", "outbound.read"},
    "supervisor": {"agent.console", "assist", "supervisor", "approvals.decide", "kb.read", "crm.read", "metrics.read", "qa.read", "wfm.read", "outbound.write", "outbound.read", "voc.read", "voc.write", "rollout.read", "evals.read", "evals.run", "tools.human", "handoff.accept", "wrapup.edit"},
    "qa": {"qa.read", "qa.write", "voc.read", "voc.write", "metrics.read", "kb.read", "evals.read", "crm.read"},
    "wfm": {"wfm.read", "wfm.write", "metrics.read", "voc.read"},
    "admin": {"*"},
    "auditor": {"audit.read", "qa.read", "metrics.read", "voc.read", "compliance.read", "security.read", "evals.read", "rollout.read", "kb.read", "wfm.read", "crm.read.masked"},
}


@dataclass
class Actor:
    role: str
    user: str
    source: str  # demo | entra | system

    def can(self, permission: str) -> bool:
        perms = PERMISSIONS.get(self.role, set())
        return "*" in perms or permission in perms


class JwtValidator:
    """Validates Entra ID access tokens (RS256) against the tenant JWKS; app roles -> Concierge roles."""

    def __init__(self, tenant_id: str, audience: str, jwks_uri: str | None = None, jwks: dict | None = None) -> None:
        self.tenant_id = tenant_id
        self.audience = audience
        self.jwks_uri = jwks_uri or f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        self._jwks = jwks
        self._fetched = time.time() if jwks is not None else 0.0  # injected keys (tests, air-gapped setups) are never re-fetched

    def _keys(self) -> dict:
        if self._jwks is None or time.time() - self._fetched > 3600:
            resp = httpx.get(self.jwks_uri, timeout=10)
            resp.raise_for_status()
            self._jwks = resp.json()
            self._fetched = time.time()
        return self._jwks

    def validate(self, token: str) -> Actor:
        header = jwt.get_unverified_header(token)
        key = next((k for k in self._keys().get("keys", []) if k.get("kid") == header.get("kid")), None)
        if key is None:
            raise jwt.InvalidTokenError("unknown signing key")
        public = jwt.PyJWK(key).key
        claims = jwt.decode(
            token,
            public,
            algorithms=["RS256"],
            audience=self.audience,
            issuer=[f"https://login.microsoftonline.com/{self.tenant_id}/v2.0", f"https://sts.windows.net/{self.tenant_id}/"],
            options={"require": ["exp", "iss", "aud"]},
        )
        roles = [r.lower() for r in claims.get("roles", []) if r.lower() in ROLES]
        role = next((r for r in ("admin", "supervisor", "qa", "wfm", "auditor", "agent") if r in roles), "customer")
        return Actor(role=role, user=str(claims.get("preferred_username") or claims.get("oid") or "unknown"), source="entra")


_validator: JwtValidator | None = None


def set_validator(v: JwtValidator | None) -> None:
    global _validator
    _validator = v


def actor_from_request(request: Request) -> Actor:
    settings = request.app.state.services.settings
    if settings.auth_mode == "entra":
        auth = request.headers.get("authorization", "")
        # Container Apps built-in auth forwards the verified principal; otherwise validate the bearer token ourselves.
        if not auth.lower().startswith("bearer ") or _validator is None:
            return Actor("customer", "anonymous", "entra")
        try:
            return _validator.validate(auth[7:])
        except jwt.PyJWTError as exc:
            raise HTTPException(401, f"invalid token: {exc}") from exc
    role = request.headers.get("x-demo-role", "customer").strip().lower()
    if role not in ROLES:
        role = "customer"
    user = request.headers.get("x-demo-user", f"demo-{role}")[:60]
    return Actor(role, user, "demo")


def require(*permissions: str):
    """FastAPI dependency: caller must hold at least one of the permissions."""

    def dep(request: Request) -> Actor:
        actor = actor_from_request(request)
        if not any(actor.can(p) for p in permissions):
            raise HTTPException(403, {"error": "forbidden", "role": actor.role, "needs_one_of": list(permissions)})
        request.state.actor = actor
        return actor

    dep.permissions = permissions  # type: ignore[attr-defined]  # introspected by the security matrix endpoint
    return dep


def describe_matrix() -> dict[str, Any]:
    return {"roles": ROLES, "permissions": {r: sorted(p) for r, p in PERMISSIONS.items()}}
