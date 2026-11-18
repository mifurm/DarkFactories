from nightshift.core.registry import FeatureSpec

FEATURE = FeatureSpec(
    id="DF-25",
    name="IaC & deployment",
    epic="E - Platform & business value",
    priority="P0",
    status="implemented",
    ui_route="/deployment",
    api_prefix="/api/deployment",
    summary="Bicep + azd (remote ACR build), keyless managed-identity wiring, post-deploy smoke tests and teardown; the page shows the live resource "
    "inventory, tags and the latest smoke-test results.",
    depth="Real infrastructure as code deployed to Azure Container Apps, Cosmos DB, Storage, AI Services and Application Insights.",
    tags=("iac", "azd"),
)
