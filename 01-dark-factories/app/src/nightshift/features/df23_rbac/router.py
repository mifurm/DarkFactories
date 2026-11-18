from typing import Any

from fastapi import APIRouter, Depends, Request

from nightshift.core.deps import get_rt
from nightshift.features.df23_rbac.rbac import PERMISSIONS, ROLE_LABELS, ROLES, Identity, identity_of, require

router = APIRouter(prefix="/api/access", tags=["DF-23 rbac"])


@router.get("/me")
async def me(request: Request) -> dict[str, Any]:
    return identity_of(request).public()


@router.get("/roles")
async def roles(rt=Depends(get_rt)) -> dict[str, Any]:
    return {
        "roles": [
            {"id": r, "label": ROLE_LABELS[r], "permissions": sorted(p for p, rs in PERMISSIONS.items() if r in rs)}
            for r in ROLES
        ],
        "permissions": {p: sorted(rs) for p, rs in PERMISSIONS.items()},
        "auth": {
            "demo_role_switcher": rt.settings.demo_role_switch,
            "entra_jwt_validation": rt.rbac.validator.enabled,
            "default_role": rt.settings.default_role,
        },
    }


@router.get("/audit")
async def audit(
    limit: int = 100, rt=Depends(get_rt), ident: Identity = Depends(require("audit_view"))
) -> dict[str, Any]:
    items = rt.rbac.audit_log[-max(1, min(limit, 500)) :][::-1]
    return {"items": items, "denied_total": rt.rbac.denied, "entries": len(rt.rbac.audit_log)}
