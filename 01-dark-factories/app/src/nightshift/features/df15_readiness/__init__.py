from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-15",
    name="Lights-Out Readiness Assessment",
    epic="C - Autonomy governance",
    priority="P1",
    status="implemented",
    ui_route="/readiness",
    api_prefix="/api/readiness",
    summary="Questionnaire plus auto-measured signals from the running simulation (data coverage, MTBF, scrap, automation share...), radar score "
    "across six dimensions, gap analysis, recommended roadmap and export.",
    depth="Real scoring model; the measured signals come from the simulated plant.",
    tags=("assessment", "roadmap"),
)
