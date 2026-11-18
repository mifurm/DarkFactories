from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-16",
    name='"Ask the Factory" copilot',
    epic="D - Copilot & insight",
    priority="P0",
    status="implemented",
    ui_route="/copilot",
    api_prefix="/api/copilot",
    summary="Azure OpenAI tool-calling over KPIs, assets, ledger, twin and what-if with streaming answers grounded in ledger/asset citations; "
    "read-only by default, 'propose action' routes into the policy and approval flow.",
    depth="Real Azure OpenAI (gpt-5.4-mini / gpt-5.4) tool calling; deterministic tool planner when offline or over budget.",
    tags=("copilot", "tool-calling"),
)
