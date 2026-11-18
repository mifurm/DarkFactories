from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-01",
    name="Factory simulator",
    epic="A - Plant digital twin & telemetry",
    priority="P0",
    status="implemented",
    ui_route="/simulator",
    api_prefix="/api/sim",
    summary="Seeded, deterministic discrete-time simulation of the Contoso Precision Components KAT-1 plant (20 assets, 3 lines, orders with "
    "routings), degradation, sensors, quality, energy, ToU tariff and carbon curves, fault-injection library, time acceleration, "
    "pause/step, snapshot/restore and a control API for agent actions.",
    depth="Real software; the physics is a calibrated stochastic model - no physical plant is connected.",
    tags=("simulation", "digital-twin"),
)
