"""Identity & RBAC (DF-23): roles enforced in the API, Entra-ready JWT validation, demo role switcher and an audit trail."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request

ROLES = ("operator", "engineer", "plant_manager", "auditor", "admin")
ROLE_LABELS = {
    "operator": "Operator",
    "engineer": "Engineer",
    "plant_manager": "Plant Manager",
    "auditor": "Auditor",
    "admin": "Admin",
}
APP_ROLE_CLAIMS = {
    "Operator": "operator",
    "Engineer": "engineer",
    "PlantManager": "plant_manager",
    "Auditor": "auditor",
    "Admin": "admin",
}

PERMISSIONS: dict[str, set[str]] = {
    "view": set(ROLES),
    "copilot": set(ROLES),
    "kill": {"operator", "engineer", "plant_manager", "admin"},
    "kill_reset": {"plant_manager", "admin"},
    "approve": {"engineer", "plant_manager", "admin"},
    "sim_control": {"engineer", "plant_manager", "admin"},
    "agent_toggle": {"engineer", "plant_manager", "admin"},
    "dial": {"plant_manager", "admin"},
    "policy_edit": {"plant_manager", "admin"},
    "break_glass": {"plant_manager", "admin"},
    "ledger_export": {"auditor", "plant_manager", "admin"},
    "audit_view": {"auditor", "admin"},
    "ab_run": {"engineer", "plant_manager", "admin"},
    "assess": {"engineer", "plant_manager", "admin"},
    "reseed": {"plant_manager", "admin"},
    "ingest": {"engineer", "admin"},
    "fleet_share": {"engineer", "plant_manager", "admin"},
    "report": {"operator", "engineer", "plant_manager", "admin"},
}


class Identity:
    def __init__(self, role: str, subject: str, source: str) -> None:
        self.role, self.subject, self.source = role, subject, source

    def can(self, perm: str) -> bool:
        return self.role in PERMISSIONS.get(perm, set())

    def public(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "label": ROLE_LABELS[self.role],
            "subject": self.subject,
            "source": self.source,
            "permissions": sorted(p for p, roles in PERMISSIONS.items() if self.role in roles),
        }


class JwtValidator:
    """Validates Entra ID access tokens (RS256) against a JWKS; keys can be injected for tests, otherwise fetched from the
    allow-listed Microsoft login endpoint of the configured tenant (no user-supplied URLs are ever fetched)."""

    def __init__(
        self, tenant_id: str = "", audience: str = "", jwks: dict[str, Any] | None = None, issuer: str | None = None
    ) -> None:
        self.tenant_id, self.audience = tenant_id, audience
        self.issuer = issuer or (f"https://login.microsoftonline.com/{tenant_id}/v2.0" if tenant_id else "")
        self._jwks = jwks
        self._static = jwks is not None  # injected keys (tests, air-gapped deployments) are never refreshed
        self._fetched = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.audience and (self.tenant_id or self._jwks))

    def _keys(self) -> dict[str, Any]:
        if self._static:
            return self._jwks or {}
        if self._jwks is None or time.time() - self._fetched > 3600:  # pragma: no cover - network path
            import httpx

            url = f"https://login.microsoftonline.com/{self.tenant_id}/discovery/v2.0/keys"
            self._jwks = httpx.get(url, timeout=5.0).json()
            self._fetched = time.time()
        return self._jwks

    def validate(self, token: str) -> Identity:
        import jwt

        try:
            header = jwt.get_unverified_header(token)
            keys = {k["kid"]: k for k in self._keys().get("keys", [])} if self._jwks or self.tenant_id else {}
            key = keys.get(header.get("kid"))
            if key is None:
                raise HTTPException(401, "unknown signing key")
            public: Any = jwt.algorithms.RSAAlgorithm.from_jwk(key)
            claims = jwt.decode(
                token,
                public,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer or None,
                options={"require": ["exp", "aud"]},
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(401, f"invalid token: {type(exc).__name__}") from exc
        roles = [APP_ROLE_CLAIMS[r] for r in claims.get("roles", []) if r in APP_ROLE_CLAIMS]
        if not roles:
            raise HTTPException(403, "token carries no Nightshift app role")
        best = max(
            roles, key=lambda r: sum(1 for rs in PERMISSIONS.values() if r in rs)
        )  # most privileged claimed role
        return Identity(best, str(claims.get("preferred_username") or claims.get("oid") or "entra-user"), "entra-jwt")


class Rbac:
    def __init__(self, settings: Any, validator: JwtValidator | None = None) -> None:
        self.settings = settings
        self.validator = validator or JwtValidator(settings.entra_tenant_id, settings.entra_audience)
        self.audit_log: list[dict[str, Any]] = []
        self.denied = 0

    def identify(self, request: Request) -> Identity:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer ") and self.validator.enabled:
            return self.validator.validate(auth[7:].strip())
        if self.settings.demo_role_switch:
            role = request.headers.get("x-demo-role", "").strip().lower() or self.settings.default_role
            if role not in ROLES:
                raise HTTPException(400, f"unknown role {role!r}")
            return Identity(role, f"demo-{role}", "demo-switcher")
        return Identity(self.settings.default_role, "anonymous", "default")

    def record(
        self, identity: Identity, action: str, detail: dict[str, Any], plant: str = "", allowed: bool = True
    ) -> dict[str, Any]:
        entry = {
            "t": time.time(),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "role": identity.role,
            "subject": identity.subject,
            "source": identity.source,
            "action": action,
            "plant": plant,
            "allowed": allowed,
            "detail": detail,
        }
        self.audit_log.append(entry)
        del self.audit_log[:-2000]
        return entry


def require(perm: str, audit: str | None = None) -> Callable[..., Any]:
    """FastAPI dependency factory: ``Depends(require('approve', audit='inbox.resolve'))``."""

    async def dep(request: Request) -> Identity:
        rt = request.app.state.rt
        rbac: Rbac = rt.rbac
        ident = rbac.identify(request)
        if not ident.can(perm):
            rbac.denied += 1
            rbac.record(ident, audit or perm, {"path": request.url.path, "required": perm}, allowed=False)
            raise HTTPException(403, f"role '{ident.role}' lacks permission '{perm}'")
        if audit:
            entry = rbac.record(ident, audit, {"path": request.url.path, "method": request.method})
            try:
                rt.writer.enqueue("audit", {"id": f"{int(entry['t'] * 1000)}-{ident.role}", "pk": "audit", **entry})
            except Exception:  # pragma: no cover
                pass
        request.state.identity = ident
        return ident

    return dep


def identity_of(request: Request) -> Identity:
    return getattr(request.state, "identity", None) or request.app.state.rt.rbac.identify(request)
