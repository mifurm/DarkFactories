from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-09",
    name="Energy & Sustainability agent",
    epic="B - Agent swarm",
    priority="P1",
    status="implemented",
    ui_route="/energy",
    api_prefix="/api/energy",
    summary="ToU- and carbon-aware load shifting of deferrable processes, peak-demand shaving, kWh and CO2e per unit KPIs.",
    depth="Real optimisation over a simulated tariff/carbon curve; energy is conserved in the model.",
    tags=("energy", "carbon"),
)
