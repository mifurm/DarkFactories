from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-14",
    name="Decision Ledger",
    epic="C - Autonomy governance",
    priority="P0",
    status="implemented",
    ui_route="/ledger",
    api_prefix="/api/ledger",
    summary="Append-only, hash-chained ledger of every observation, proposal, decision, action and outcome with rationale and counterfactual; "
    "query by asset/agent/time/outcome, JSONL export and verify-chain API; persisted to Cosmos DB.",
    depth="Real SHA-256 hash chain, persisted; tamper detection is tested.",
    tags=("audit", "tamper-evident"),
)
