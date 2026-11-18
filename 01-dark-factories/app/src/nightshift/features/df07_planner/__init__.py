from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-07",
    name="Production Planner agent",
    epic="B - Agent swarm",
    priority="P0",
    status="implemented",
    ui_route="/planner",
    api_prefix="/api/planner",
    summary="Finite-capacity scheduling (due dates, priority, setups, routings), continuous re-planning on breakdown / rush order / shortage, "
    "schedule-quality KPIs (tardiness, makespan, utilisation) and a 'why this schedule' explanation. FIFO/static is the A/B baseline.",
    depth="Real scheduler (critical-ratio list scheduling + local search) driving the simulated shop floor.",
    tags=("scheduling",),
)
