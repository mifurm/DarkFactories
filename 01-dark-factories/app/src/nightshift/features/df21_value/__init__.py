from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-21",
    name="Value realization & ACR/ROI calculator",
    epic="E - Platform & business value",
    priority="P0",
    status="implemented",
    ui_route="/value",
    api_prefix="/api/value",
    summary="(a) A/B replay: N seeds with the swarm OFF vs ON on the same fault schedule with measured deltas and confidence intervals; "
    "(b) business-case calculator (ROI, payback, NPV, IRR and Azure ACR by service family) using the vendored business-case model.",
    depth="A/B is a real paired simulation experiment on synthetic data; the calculator runs the vendored business-case/model.py.",
    tags=("roi", "acr", "ab-replay"),
)
