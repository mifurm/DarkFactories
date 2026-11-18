"""Roles & permissions (CS-22). Demo identity is a self-declared header; in an Entra-protected deployment the
role is read from the Container Apps built-in-auth principal (``X-MS-CLIENT-PRINCIPAL``) claims instead."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from enum import StrEnum

from fastapi import Request

from .errors import Forbidden


class Role(StrEnum):
    ADMIN = "admin"
    BRAND_MANAGER = "brand_manager"
    CREATIVE_DIRECTOR = "creative_director"
    CREATIVE = "creative"
    LEGAL = "legal"
    AGENCY_GUEST = "agency_guest"


ALL = set(Role)
DOERS = {Role.ADMIN, Role.BRAND_MANAGER, Role.CREATIVE_DIRECTOR, Role.CREATIVE}

PERMISSIONS: dict[str, set[Role]] = {
    "brand.write": {Role.ADMIN, Role.BRAND_MANAGER},
    "claims.write": {Role.ADMIN, Role.BRAND_MANAGER, Role.LEGAL},
    "rights.write": {Role.ADMIN, Role.BRAND_MANAGER, Role.LEGAL},
    "campaign.write": DOERS | {Role.AGENCY_GUEST},
    "generate": DOERS | {Role.AGENCY_GUEST},
    "library.write": DOERS | {Role.AGENCY_GUEST},
    "performance.write": DOERS,
    "approve": {Role.ADMIN, Role.BRAND_MANAGER, Role.CREATIVE_DIRECTOR, Role.LEGAL},
    "waive": {Role.ADMIN, Role.LEGAL},
    "budget.write": {Role.ADMIN, Role.BRAND_MANAGER},
    "premium.approve": {Role.ADMIN, Role.BRAND_MANAGER},
    "webhooks.write": {Role.ADMIN},
    "export": DOERS | {Role.LEGAL},
    "admin": {Role.ADMIN},
    "read": ALL,
}

ROLE_LABELS = {
    Role.ADMIN: "Admin",
    Role.BRAND_MANAGER: "Brand Manager",
    Role.CREATIVE_DIRECTOR: "Creative Director",
    Role.CREATIVE: "Creative",
    Role.LEGAL: "Legal / Compliance",
    Role.AGENCY_GUEST: "Agency (guest)",
}


@dataclass(frozen=True)
class Actor:
    role: Role
    name: str

    def can(self, permission: str) -> bool:
        return self.role in PERMISSIONS.get(permission, set())

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role.value, "name": self.name, "label": ROLE_LABELS[self.role]}


def _from_principal(header: str) -> Role | None:
    try:
        data = json.loads(base64.b64decode(header + "=" * (-len(header) % 4)))
    except Exception:
        return None
    for claim in data.get("claims", []):
        if claim.get("typ") in {"roles", "role"} and claim.get("val") in {r.value for r in Role}:
            return Role(claim["val"])
    return None


def get_actor(request: Request) -> Actor:
    h = request.headers
    role: Role | None = None
    if h.get("x-ms-client-principal"):
        role = _from_principal(h["x-ms-client-principal"])
    if role is None:
        raw = (h.get("x-studio-role") or "").strip().lower()
        role = Role(raw) if raw in {r.value for r in Role} else Role.CREATIVE
    name = re.sub(r"[^\w .@'-]", "", h.get("x-studio-user", ""))[:60].strip() or ROLE_LABELS[role]
    return Actor(role, name)


def require(permission: str):
    def dep(request: Request) -> Actor:
        actor = get_actor(request)
        if not actor.can(permission):
            raise Forbidden(
                f"Role '{ROLE_LABELS[actor.role]}' is not allowed to perform '{permission}'.",
                code="role_forbidden",
                hint="Switch role (top-right) or ask an Admin.",
                details={"role": actor.role.value, "permission": permission},
            )
        return actor

    return dep
