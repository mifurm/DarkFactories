from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-17",
    name="Shift handover & executive digest",
    epic="D - Copilot & insight",
    priority="P1",
    status="implemented",
    ui_route="/handover",
    api_prefix="/api/handover",
    summary="On-demand and scheduled (shift boundary) shift reports generated from structured KPI/ledger input with LLM narration and a "
    "deterministic template fallback; HTML and Markdown export.",
    depth="Real generation and scheduling; numbers are deterministic, only the prose is model-written.",
    tags=("report",),
)
