from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-19",
    name="KPI engine",
    epic="D - Copilot & insight",
    priority="P0",
    status="implemented",
    ui_route="/kpis",
    api_prefix="/api/kpi",
    summary="OEE (A x P x Q), throughput, FPY, scrap, MTBF/MTTR, OTIF, energy and CO2 per unit and EUR impact per asset/line/plant, with windows, "
    "trends and persisted snapshots.",
    depth="Real KPI computation from simulator counters.",
    tags=("oee", "kpi"),
)
