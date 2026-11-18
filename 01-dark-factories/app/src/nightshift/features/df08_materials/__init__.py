from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-08",
    name="Materials & Logistics agent",
    epic="B - Agent swarm",
    priority="P1",
    status="implemented",
    ui_route="/materials",
    api_prefix="/api/materials",
    summary="BOM and inventory with min/max, reorder, AMR dispatch to feed cells, supplier-delay mitigation (expedite / alternate source) and kitting.",
    depth="Real policies over a simulated warehouse and 3 simulated AMRs.",
    tags=("inventory", "amr"),
)
