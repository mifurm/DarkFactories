#!/usr/bin/env bash
# Build the GPU motion worker image in ACR and roll it out to ca-studio-motion (serverless A100, scale-to-zero, no ingress).
#
#   scripts/deploy_motion.sh            # image tag = git-<short sha>
#   scripts/deploy_motion.sh v2         # explicit tag
#
# The environment holds quota for ONE A100: a new revision cannot get a GPU while the previous replica is still running or
# terminating, so the script waits until the worker has scaled to zero (queue empty + cooldown) before it switches the image.
# Keyless: the build runs in ACR (no local Docker), the app pulls with its managed identity.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${AZURE_SUBSCRIPTION_ID:?set AZURE_SUBSCRIPTION_ID to the target subscription id}"
RG="${AZURE_RESOURCE_GROUP:-rg-swarmai-studio}"
APP="ca-studio-motion"
ACR="$(az acr list -g "$RG" --subscription "$AZURE_SUBSCRIPTION_ID" --query '[0].name' -o tsv)"
TAG="${1:-git-$(git rev-parse --short HEAD)}"
REPO="swarmai-studio/motion-worker"
IMAGE="$ACR.azurecr.io/$REPO:$TAG"

echo "==> az acr build $IMAGE (base image pulled from MCR inside Azure)"
az acr build --registry "$ACR" --subscription "$AZURE_SUBSCRIPTION_ID" --image "$REPO:$TAG" --file motion-worker/Dockerfile motion-worker --no-logs -o none
echo "    built."

echo "==> waiting for the worker to be idle (0 replicas) so the new revision can take the single A100"
for _ in $(seq 1 90); do
  n="$(az containerapp replica list -g "$RG" -n "$APP" --subscription "$AZURE_SUBSCRIPTION_ID" --query 'length(@)' -o tsv 2>/dev/null || echo 0)"
  [[ "$n" == "0" ]] && break
  echo "    replicas=$n ..."
  sleep 20
done

echo "==> rolling out $IMAGE"
az containerapp update -g "$RG" -n "$APP" --subscription "$AZURE_SUBSCRIPTION_ID" --image "$IMAGE" -o none
az containerapp revision list -g "$RG" -n "$APP" --subscription "$AZURE_SUBSCRIPTION_ID" \
  --query "[?properties.active].{revision:name,created:properties.createdTime,health:properties.healthState}" -o table
echo "Next: warm up with  curl -X POST <studio>/api/motion/warmup  (first start downloads the model weights once, ~5 min), then render a Cinematic spot."
