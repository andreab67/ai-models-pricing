#!/bin/sh
# Accept only the expected health response; never follow redirects.
set -eu
status=$(curl --fail --silent --show-error --connect-timeout 5 --max-time 20 \
    --output /dev/null --write-out '%{http_code}' "$1")
if [ "$status" != 200 ]; then
    echo "Health check returned HTTP $status, expected 200" >&2
    exit 1
fi
