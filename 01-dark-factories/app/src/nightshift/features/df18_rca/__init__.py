from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-18",
    name="Root-cause analysis assistant",
    epic="D - Copilot & insight",
    priority="P1",
    status="implemented",
    ui_route="/rca",
    api_prefix="/api/rca",
    summary="Event correlation (temporal causal graph over a plant topology prior), loss Pareto and ranked hypotheses with evidence; the LLM only narrates.",
    depth="Real correlation and ranking; narration optional.",
    tags=("rca", "causal"),
)
