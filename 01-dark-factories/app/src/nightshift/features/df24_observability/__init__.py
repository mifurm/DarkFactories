from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-24",
    name="Observability & FinOps",
    epic="E - Platform & business value",
    priority="P1",
    status="implemented",
    ui_route="/observability",
    api_prefix="/api/observability",
    summary="OpenTelemetry to Application Insights, per-agent latency and decision counters, per-feature request metrics, LLM token/US$ meter "
    "with a daily budget guard and health endpoints.",
    depth="Real telemetry to Application Insights (Entra-authenticated) and an in-app metrics view.",
    tags=("otel", "finops"),
)
