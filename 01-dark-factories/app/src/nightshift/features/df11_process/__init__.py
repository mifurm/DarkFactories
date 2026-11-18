from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-11",
    name="Process Optimizer agent",
    epic="B - Agent swarm",
    priority="P2",
    status="implemented",
    ui_route="/process",
    api_prefix="/api/process",
    summary="Bounded recipe/parameter optimisation (yield vs energy vs cycle time) with trust-region safe exploration and rollback on regression.",
    depth="Real optimiser over a simulated response surface for the injection-moulding presses.",
    tags=("optimisation",),
)
