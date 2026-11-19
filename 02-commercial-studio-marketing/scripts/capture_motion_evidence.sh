#!/usr/bin/env bash
# Capture the Azure facts behind the Cinematic-motion layer (CS-25) into app/evidence/motion-azure-resources.txt.
# Read-only: only `az ... show / list` calls. Needs an `az login` session with Reader on the resource group and
# Storage Blob / Queue Data Reader on the storage account (Entra auth; the storage account has shared-key access off).
#
#   AZURE_SUBSCRIPTION_ID=<id> scripts/capture_motion_evidence.sh
set -euo pipefail
cd "$(dirname "$0")/.."

: "${AZURE_SUBSCRIPTION_ID:?set AZURE_SUBSCRIPTION_ID to the target subscription id}"
SUB="$AZURE_SUBSCRIPTION_ID"
RG="${AZURE_RESOURCE_GROUP:-rg-swarmai-studio}"
APP="ca-studio-motion"
OUT="app/evidence/motion-azure-resources.txt"

az() { command az "$@" --subscription "$SUB"; }
q() { "$@" 2>&1 | grep -v '^WARNING' || true; }

ENV="$(az containerapp env list -g "$RG" --query '[0].name' -o tsv)"
ST="$(az storage account list -g "$RG" --query '[0].name' -o tsv)"
ACR="$(az acr list -g "$RG" --query '[0].name' -o tsv)"
WORKER_ID="$(az identity show -g "$RG" -n id-studio-motion --query principalId -o tsv)"
APP_ID="$(az identity show -g "$RG" -n id-studio-app --query principalId -o tsv)"

{
  echo "# Cinematic motion (CS-25): deployed Azure resources — captured $(date -u +%Y-%m-%dT%H:%M:%SZ) with az (subscription $SUB, $RG)"
  echo
  echo "## Container Apps environment workload profiles"
  q az containerapp env workload-profile list -g "$RG" -n "$ENV" --query '[].name' -o table
  echo
  echo "## $APP (GPU worker): profile, ingress, identity, scale rule, grace, resources, image"
  q az containerapp show -g "$RG" -n "$APP" --query "{profile:properties.workloadProfileName, ingress:properties.configuration.ingress, identity:keys(identity.userAssignedIdentities), graceSeconds:properties.template.terminationGracePeriodSeconds, scale:properties.template.scale, resources:properties.template.containers[0].resources, image:properties.template.containers[0].image}" -o json
  echo
  echo "## Storage: shared key / public access / TLS"
  q az storage account show -g "$RG" -n "$ST" --query '{allowSharedKeyAccess:allowSharedKeyAccess, allowBlobPublicAccess:allowBlobPublicAccess, defaultToOAuthAuthentication:defaultToOAuthAuthentication, minimumTlsVersion:minimumTlsVersion}' -o json
  echo
  echo "## Queue and blob containers (Entra auth)"
  q az storage queue list --account-name "$ST" --auth-mode login --query '[].name' -o tsv
  q az storage container list --account-name "$ST" --auth-mode login --query '[].{Name:name}' -o table
  echo
  echo "## Lifecycle policy (transport blobs expire after 3 days)"
  q az storage account management-policy show -g "$RG" --account-name "$ST" --query 'policy.rules[].{name:name, deleteAfterDays:definition.actions.baseBlob.delete.daysAfterModificationGreaterThan, prefix:definition.filters.prefixMatch}' -o json
  echo
  echo "## Role assignments on the storage account (worker = id-studio-motion, Studio = id-studio-app). Expect: data roles on the 3 motion containers + the queue only; account scope only for the Studio app's Blob role"
  for pair in "id-studio-motion:$WORKER_ID" "id-studio-app:$APP_ID"; do
    echo "-- ${pair%%:*} (${pair##*:})"
    q az role assignment list --assignee "${pair##*:}" --all \
      --query "[?contains(scope,'$ST') || contains(scope,'$ACR')].{role:roleDefinitionName,scope:scope}" -o tsv \
      | sed -E "s#/subscriptions/[^/]+/resourcegroups/[^/]+/providers/Microsoft\\.(Storage|ContainerRegistry)/(storageAccounts|registries)/##I"
  done
  echo
  echo "## Container Registry"
  q az acr show -n "$ACR" --query '{sku:sku.name, adminUserEnabled:adminUserEnabled}' -o json
  q az acr repository list -n "$ACR" -o tsv
  echo
  echo "## Resource tags: untagged resources (expect 0)"
  q az resource list -g "$RG" --query "[?tags.SecurityControl!='Ignore' || tags.SecurityExemption!='StorageAccountKeyAccess'] | length(@)" -o tsv
} > "$OUT"

echo "wrote $OUT"
