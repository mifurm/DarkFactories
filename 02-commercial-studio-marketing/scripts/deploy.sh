#!/usr/bin/env bash
# Idempotent provision + deploy of SwarmAI Commercial Studio (Spotlight) to Azure.
#
#   scripts/deploy.sh                 # provision infra (Bicep) -> tag platform-created resources -> build+deploy the app
#   scripts/deploy.sh --app-only      # skip provisioning (fast code redeploy, ~3 min)
#
# Prerequisites: az + azd installed and signed in (az login / azd auth login), Contributor (or Owner) on the subscription.
# Everything is keyless: the container app uses a user-assigned managed identity; no secrets are created or stored.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${AZURE_SUBSCRIPTION_ID:?set AZURE_SUBSCRIPTION_ID to the target subscription id}"
export AZURE_ENV_NAME="${AZURE_ENV_NAME:-studio}"
export AZURE_LOCATION="${AZURE_LOCATION:-swedencentral}"
export AZURE_RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-swarmai-studio}"
RG="$AZURE_RESOURCE_GROUP"

azd env select "$AZURE_ENV_NAME" >/dev/null 2>&1 || azd env new "$AZURE_ENV_NAME" --location "$AZURE_LOCATION" --subscription "$AZURE_SUBSCRIPTION_ID" --no-prompt
azd env set AZURE_PRINCIPAL_ID "$(az ad signed-in-user show --query id -o tsv)" >/dev/null

if [[ "${1:-}" != "--app-only" ]]; then
  echo "==> azd provision (idempotent: unchanged resources are left alone)"
  azd provision --no-prompt

  # Governance tags: the RG and every taggable resource carry SecurityControl=Ignore, SecurityExemption=StorageAccountKeyAccess,
  # project, concept, owner, environment (Bicep `commonTags`). Azure Monitor creates two alert resources on its own
  # (Log Analytics daily-cap alert, Storage availability alert) that Bicep does not manage -> tag them here.
  echo "==> ensuring governance tags on platform-created resources"
  TAGS=(SecurityControl=Ignore SecurityExemption=StorageAccountKeyAccess project=SwarmAI concept=studio owner=michalfu environment=demo)
  while IFS= read -r id; do
    [[ -z "$id" ]] && continue
    echo "   tagging $id"
    az tag update --resource-id "$id" --operation merge --tags "${TAGS[@]}" --subscription "$AZURE_SUBSCRIPTION_ID" -o none || true
  done < <(az resource list -g "$RG" --subscription "$AZURE_SUBSCRIPTION_ID" --query "[?tags.SecurityControl==null].id" -o tsv)
fi

echo "==> azd deploy web (remote ACR build; no local Docker needed)"
azd deploy web --no-prompt

URL="https://$(az containerapp show -g "$RG" -n ca-studio-web --subscription "$AZURE_SUBSCRIPTION_ID" --query properties.configuration.ingress.fqdn -o tsv)"
echo "==> deployed: $URL"
curl -fsS "$URL/healthz" && echo
curl -fsS "$URL/readyz?deep=true" | python3 -c "import sys,json; d=json.load(sys.stdin); print('readyz:', d['status'], 'mode=' + d['mode'], {k: v['ok'] for k, v in d['dependencies'].items()})"
echo "Next: python scripts/smoke_test.py --base-url $URL --expect-mode azure"
