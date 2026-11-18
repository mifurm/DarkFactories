from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-13",
    name="Human-on-the-loop inbox",
    epic="C - Autonomy governance",
    priority="P0",
    status="implemented",
    ui_route="/inbox",
    api_prefix="/api/inbox",
    summary="Approval/escalation queue with options, impact estimate, explanation, SLA timers and auto-escalation; optional Teams incoming-webhook "
    "notifier with Adaptive Card JSON.",
    depth="Real queue and SLA engine; Teams card is built and validated, delivery needs TEAMS_WEBHOOK_URL.",
    tags=("approvals", "teams"),
)
