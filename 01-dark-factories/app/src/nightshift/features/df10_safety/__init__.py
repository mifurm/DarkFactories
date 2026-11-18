from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-10",
    name="Safety & Compliance Sentinel",
    epic="B - Agent swarm",
    priority="P0",
    status="implemented",
    ui_route="/safety",
    api_prefix="/api/safety",
    summary="Safety zones and human-intrusion handling (safe-stop / slow), forbidden-setpoint guards, protected-asset rules, simulated cyber-hygiene "
    "checks, immutable audit hooks and a veto over every other agent.",
    depth="Real rules engine on simulated zone sensors; the plant's hard-wired interlocks are modelled, not replaced.",
    tags=("safety", "veto"),
)
