#!/usr/bin/env bash
# Own only kilo-diff's unprefixed context Secret reference. All other live
# fields remain operator-owned; JSON Patch resourceVersion tests reject races.
set -euo pipefail
umask 077
work=$(mktemp -d)
trap 'rm -f "$work/current.json" "$work/patch.json" "$work/verified.json"; rmdir "$work"' EXIT
kubectl get secret langfuse-context-tracing -n model-pricing -o name >/dev/null
kubectl get cronjob/kilo-diff -n model-pricing -o json > "$work/current.json"
jq -e '
    .metadata.resourceVersion as $revision |
    .spec.jobTemplate.spec.template.spec.containers as $containers |
    [$containers | to_entries[] | select(.value.name == "diff")] as $matches |
    if ($revision | type) != "string" or ($revision | length) == 0 or ($matches | length) != 1
    then error("Unexpected kilo-diff workload identity") else . end |
    $matches[0].key as $index | $matches[0].value as $container |
    if any($container.env[]?; .name | startswith("LANGFUSE_"))
    then error("Explicit operator LANGFUSE settings would override context Secret") else . end |
    ($container.envFrom // []) as $old |
    (($old | map(select(.secretRef.name != "langfuse-context-tracing" or (.prefix // "") != "")))
      + [{secretRef: {name: "langfuse-context-tracing"}}]) as $wanted |
    if $old == $wanted then [] else [
      {op: "test", path: "/metadata/resourceVersion", value: $revision},
      {op: "test", path: ("/spec/jobTemplate/spec/template/spec/containers/" + ($index | tostring) + "/name"), value: "diff"},
      {op: "add", path: ("/spec/jobTemplate/spec/template/spec/containers/" + ($index | tostring) + "/envFrom"), value: $wanted}
    ] end
' "$work/current.json" > "$work/patch.json"
if [ "$(jq length "$work/patch.json")" != 0 ]; then
    kubectl patch cronjob/kilo-diff -n model-pricing --type=json --patch-file "$work/patch.json" >/dev/null
fi
kubectl get cronjob/kilo-diff -n model-pricing -o json > "$work/verified.json"
jq -e '
    [.spec.jobTemplate.spec.template.spec.containers[] | select(.name == "diff")] as $matches |
    ($matches | length) == 1 and
    ($matches[0].envFrom[-1] == {secretRef: {name: "langfuse-context-tracing"}}) and
    (all($matches[0].env[]?; .name | startswith("LANGFUSE_") | not))
' "$work/verified.json" >/dev/null
echo "Verified kilo-diff context Secret reference; other workload fields preserved"
