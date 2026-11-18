from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-04",
    name="Swarm runtime & Shift Supervisor",
    epic="B - Agent swarm",
    priority="P0",
    status="implemented",
    ui_route="/swarm",
    api_prefix="/api/swarm",
    summary="Agent base class (perceive -> propose -> respond), blackboard, Proposal objects with rationale/evidence/impact/risk/cost/expiry, "
    "conflict detection and explicit utility arbitration, rate limits, per-agent metrics; deterministic with optional LLM narration.",
    depth="Real orchestration; arbitration is an explicit weighted-utility algorithm, the LLM only narrates.",
    tags=("agents", "orchestration"),
)
