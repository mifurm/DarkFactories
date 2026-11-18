from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-06",
    name="Quality Guardian agent",
    epic="B - Agent swarm",
    priority="P0",
    status="implemented",
    ui_route="/quality",
    api_prefix="/api/quality",
    summary="SPC (X-bar/R, Cpk, Western Electric rules), drift detection, bounded setpoint compensation, lot quarantine/containment and vision "
    "inspection of synthetic part images with Azure OpenAI multimodal plus a human-review queue for low-confidence calls.",
    depth="SPC and containment are real on simulated measurements; vision uses real Azure OpenAI on PIL-generated synthetic images (classical-CV fallback offline).",
    tags=("spc", "vision"),
)
