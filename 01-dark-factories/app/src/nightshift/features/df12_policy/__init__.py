from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-12",
    name="Autonomy Dial & policy-as-code",
    epic="C - Autonomy governance",
    priority="P0",
    status="implemented",
    ui_route="/policy",
    api_prefix="/api/policy",
    summary="Per-decision-class autonomy levels L0-L5, risk scoring, approval thresholds, blast-radius limits, time-boxed auto-approval, break-glass "
    "and a global kill switch; rules in YAML/JSON evaluated by a small tested policy engine.",
    depth="Real policy engine enforced in the action path (not only in the UI).",
    tags=("policy", "autonomy"),
)
