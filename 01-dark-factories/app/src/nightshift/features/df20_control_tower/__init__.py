from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-20",
    name="Control Tower UI",
    epic="E - Platform & business value",
    priority="P0",
    status="implemented",
    ui_route="/",
    api_prefix="/api/tower",
    summary="Live plant map (SVG) with machine cards, KPI tiles, agent activity stream, fault console, Autonomy Dial, approvals inbox, ledger "
    "explorer, twin what-if panel and copilot panel in a dark control-room design.",
    depth="Real UI fed by SSE from the live in-process simulation.",
    tags=("ui",),
)
