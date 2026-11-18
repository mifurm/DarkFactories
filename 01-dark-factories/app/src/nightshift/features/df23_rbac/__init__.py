from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-23",
    name="Identity & RBAC",
    epic="E - Platform & business value",
    priority="P1",
    status="implemented",
    ui_route="/access",
    api_prefix="/api/access",
    summary="Roles (Operator, Engineer, Plant Manager, Auditor, Admin) enforced in the API, Entra-ready JWT validation, a demo role switcher and "
    "an audit trail of privileged actions.",
    depth="Real enforcement; the demo role switcher stands in for Entra sign-in (JWT validation path implemented and tested with a local key).",
    tags=("rbac", "entra"),
)
