#!/bin/sh
# Explicit needs constrain transport; validate producer and full image identity too.
# Usage: read-image-digest.sh <job-slug> <expected-repository> <full-commit-sha>
set -eu
if [ "$#" -ne 3 ]; then
  echo "Expected build job slug, image repository and full commit SHA" >&2
  exit 1
fi
producer=$1
repository=$2
commit=$3
case "$producer" in *[!a-z0-9-]*|''|-*|*-) echo "Invalid build job slug" >&2; exit 1 ;; esac
[ "${#producer}" -le 63 ] || { echo "Invalid build job slug" >&2; exit 1; }
case "$repository" in *[!a-z0-9/._:-]*|'') echo "Invalid expected image repository" >&2; exit 1 ;; esac
case "$commit" in *[!0-9a-f]*|'') echo "Invalid expected commit SHA" >&2; exit 1 ;; esac
[ "${#commit}" -eq 40 ] || { echo "Expected full commit SHA" >&2; exit 1; }
set -- image-metadata-"$producer"-*.json
if [ "$#" != 1 ] || [ ! -f "$1" ]; then
  echo "Expected exactly one image metadata artifact for $producer" >&2
  exit 1
fi
job_id=${1#image-metadata-"$producer"-}
job_id=${job_id%.json}
case "$job_id" in *[!0-9]*|'') echo "Expected exact producer and numeric build job ID" >&2; exit 1 ;; esac
if ! jq -ser --arg expected "$repository:$commit" '
  if length == 1 and (.[0] | type) == "object" then
    .[0] | if .["image.name"] == $expected then
      .["containerimage.digest"] | strings | select(test("\\Asha256:[0-9a-f]{64}\\z"))
    else error("Unexpected image identity") end
  else error("Expected one metadata object") end
' "$1" 2>/dev/null; then
  echo "Invalid build metadata identity or digest" >&2
  exit 1
fi
