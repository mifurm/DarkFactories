#!/usr/bin/env bash
# Ensures the resource group and EVERY taggable resource in it - including the alert rules and system topics that Azure creates by itself
# (Log Analytics daily-cap alert, Application Insights smart-detector rules, Storage availability alert) - carry the governance + common tags.
# Run by the azd `postprovision` hook (see azure.yaml); safe to run any time (idempotent, merge semantics).
set -euo pipefail

SUB="${AZURE_SUBSCRIPTION_ID:-1217c203-6c76-47b4-b61c-9bba62dc8e02}"
RG="${AZURE_RESOURCE_GROUP:-rg-swarmai-darkfactory}"
TAGS=(SecurityControl=Ignore SecurityExemption=StorageAccountKeyAccess project=SwarmAI concept=darkfactory owner=michalfu environment=demo)

az tag update --subscription "$SUB" --resource-id "/subscriptions/$SUB/resourceGroups/$RG" --operation merge --tags "${TAGS[@]}" -o none
echo "resource group $RG tagged"

n=0
while IFS= read -r id; do
  [ -z "$id" ] && continue
  if az tag update --subscription "$SUB" --resource-id "$id" --operation merge --tags "${TAGS[@]}" -o none 2>/dev/null; then
    echo "tagged: ${id##*/}"
    n=$((n + 1))
  else
    echo "not taggable (skipped): ${id##*/}"
  fi
done < <(az resource list --subscription "$SUB" -g "$RG" --query "[?tags.SecurityControl==null || tags.SecurityExemption==null].id" -o tsv)
echo "done: $n resource(s) tagged"
