#!/usr/bin/env bash
# Image-only deploy: preserve operator-owned fields outside the image references.
# kubectl set image supports Deployments, init containers and CronJobs:
# https://kubernetes.io/docs/reference/kubectl/generated/kubectl_set/kubectl_set_image/
set -euo pipefail
: "${IMAGE_API:?IMAGE_API required}"
: "${IMAGE_WEB:?IMAGE_WEB required}"
: "${CI_COMMIT_SHA:?CI_COMMIT_SHA required}"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rendered="${DEPLOY_RENDERED_FILE:-$repo/rendered-prod.yaml}"
api_digest=$(sh "$repo/ci/read-image-digest.sh" build-api "$IMAGE_API" "$CI_COMMIT_SHA")
web_digest=$(sh "$repo/ci/read-image-digest.sh" build-web "$IMAGE_WEB" "$CI_COMMIT_SHA")
echo "Deploying commit $CI_COMMIT_SHA as $IMAGE_API@$api_digest and $IMAGE_WEB@$web_digest"
bash "$repo/scripts/render-prod-overlay.sh" "$IMAGE_API" "$IMAGE_WEB" "$CI_COMMIT_SHA" "$rendered" "$api_digest" "$web_digest"
api="$IMAGE_API@$api_digest"
web="$IMAGE_WEB@$web_digest"
kubectl set image deployment/api "migrate=$api" "api=$api" -n model-pricing
kubectl set image deployment/web "web=$web" -n model-pricing
api_rc=0
web_rc=0
kubectl rollout status deployment/api -n model-pricing --timeout=120s || api_rc=$?
kubectl rollout status deployment/web -n model-pricing --timeout=120s || web_rc=$?
if [[ "$api_rc" != 0 || "$web_rc" != 0 ]]; then
    echo "Rollout failed; reverting to previous revision" >&2
    kubectl rollout undo deployment/api -n model-pricing || true
    kubectl rollout undo deployment/web -n model-pricing || true
    exit 1
fi
# Move scheduled jobs only after the API migration and both rollouts are ready.
kubectl set image cronjob/refresh-pricing "refresh=$api" -n model-pricing
kubectl set image cronjob/daily-report "report=$api" -n model-pricing
kubectl set image cronjob/kilo-diff "diff=$api" -n model-pricing
verify() {
    local resource=$1
    local path=$2
    local expected=$3
    local live
    live="$(kubectl get "$resource" -n model-pricing -o "jsonpath=$path")"
    [[ "$live" = "$expected" ]] || { echo "live image mismatch: $resource" >&2; exit 1; }
}
verify deployment/api '{.spec.template.spec.initContainers[0].image}' "$api"
verify deployment/api '{.spec.template.spec.containers[0].image}' "$api"
verify deployment/web '{.spec.template.spec.containers[0].image}' "$web"
for job in refresh-pricing daily-report kilo-diff; do
    verify "cronjob/$job" '{.spec.jobTemplate.spec.template.spec.containers[0].image}' "$api"
done
