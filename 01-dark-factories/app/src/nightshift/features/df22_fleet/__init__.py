from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-22",
    name="Multi-plant fleet",
    epic="E - Platform & business value",
    priority="P1",
    status="implemented",
    ui_route="/fleet",
    api_prefix="/api/fleet",
    summary="Three simulated plants with different profiles, fleet KPIs, benchmarking and cross-plant playbook sharing (failure signatures learned "
    "at one plant reused at another).",
    depth="Three real simulation instances in one process; fleet scale-out is documented (partition plants across replicas).",
    tags=("fleet", "benchmark"),
)
