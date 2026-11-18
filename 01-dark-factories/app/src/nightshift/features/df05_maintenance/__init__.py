from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-05",
    name="Predictive Maintenance agent",
    epic="B - Agent swarm",
    priority="P0",
    status="implemented",
    ui_route="/maintenance",
    api_prefix="/api/maintenance",
    summary="Multivariate anomaly detection (robust z, EWMA, isolation-forest), health index, RUL with confidence band, failure-signature "
    "library, spare-part check and automatic work orders placed in planned windows.",
    depth="Real algorithms on simulated sensor streams.",
    tags=("pdm", "rul"),
)
