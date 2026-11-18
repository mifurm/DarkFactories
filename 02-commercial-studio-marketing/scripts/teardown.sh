#!/usr/bin/env bash
# Tear down everything created by scripts/deploy.sh (resource group, Cosmos data, blobs, container registry, AI deployments).
#
#   scripts/teardown.sh          # asks for nothing: use only on the demo environment
#
# `--purge` also purges the soft-deleted Azure AI Services account so the name/quota is released immediately.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${AZURE_SUBSCRIPTION_ID:?set AZURE_SUBSCRIPTION_ID}"
export AZURE_ENV_NAME="${AZURE_ENV_NAME:-studio}"
azd env select "$AZURE_ENV_NAME"
azd down --force --purge --no-prompt
echo "Removed. Verify: az group exists -n ${AZURE_RESOURCE_GROUP:-rg-swarmai-studio} --subscription $AZURE_SUBSCRIPTION_ID"
