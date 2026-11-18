from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-03",
    name="Digital twin & what-if engine",
    epic="A - Plant digital twin & telemetry",
    priority="P0",
    status="implemented",
    ui_route="/twin",
    api_prefix="/api/twin",
    summary="Live asset graph (hierarchy, state, health, KPIs) plus fork() and simulate_ahead(actions, horizon) returning KPI deltas on a forked "
    "twin with common random numbers; used by the Supervisor for sim-first validation.",
    depth="Real fork/simulate on the in-process simulator state (snapshot/restore).",
    tags=("what-if", "sim-first"),
)
