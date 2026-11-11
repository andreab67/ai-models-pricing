#!/usr/bin/env bash
# Render an isolated image override; never apply unrelated live resource fields.
set -euo pipefail
[[ $# = 4 || $# = 6 ]] || { echo "usage: $0 <api-repository> <web-repository> <full-sha> <output>" >&2; exit 1; }
api=$1
web=$2
sha=$3
out=$4
for image in "$api" "$web"; do
    [[ "$image" =~ ^[a-z0-9./:_-]+$ && "${image##*/}" != *:* ]] || {
        echo "invalid image repository" >&2; exit 1;
    }
done
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "expected a full commit SHA" >&2; exit 1; }
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
render_dir="$(mktemp -d)"
trap 'rm -rf "$render_dir"' EXIT
cp -R "$repo/k8s" "$render_dir/k8s"
(
    cd "$render_dir/k8s/overlays/prod"
    kustomize edit set image \
        "gitlab.andrea-house.com:5050/root/model-pricing/api=$api:$sha" \
        "gitlab.andrea-house.com:5050/root/model-pricing/web=$web:$sha"
    if [[ $# = 6 ]]; then
        [[ "$5" =~ ^sha256:[0-9a-f]{64}$ && "$6" =~ ^sha256:[0-9a-f]{64}$ ]] || {
            echo "invalid image digest" >&2; exit 1;
        }
        kustomize edit set image \
            "gitlab.andrea-house.com:5050/root/model-pricing/api=$api@$5" \
            "gitlab.andrea-house.com:5050/root/model-pricing/web=$web@$6"
    fi
)
kustomize build "$render_dir/k8s/overlays/prod" >"$out"
# Refuse an unrecognized workload image rather than validating a partial render.
images="$(grep -E '^[[:space:]]*(-[[:space:]]+)?image:' "$out")"
while IFS= read -r line; do
    api_expected="$api:$sha"; web_expected="$web:$sha"
    if [[ $# = 6 ]]; then api_expected="$api@$5"; web_expected="$web@$6"; fi
    [[ "$line" == *"$api_expected" || "$line" == *"$web_expected" ]] || {
        echo "rendered image does not match the build SHA" >&2; exit 1;
    }
done <<<"$images"
