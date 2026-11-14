#!/bin/sh
# Accept only HTTP 200; give the ingress up to five bounded GET attempts to
# observe newly ready endpoints. Never retry auth, TLS, redirects or other errors.
set -eu
attempt=1
while :; do
    rc=0
    status=$(curl --fail --silent --show-error --connect-timeout 5 --max-time 20 \
        --output /dev/null --write-out '%{http_code}' "$1") || rc=$?
    if [ "$rc" = 0 ] && [ "$status" = 200 ]; then
        exit 0
    fi
    case "$status" in
        502|503|504)
            if [ "$attempt" -lt 5 ]; then
                attempt=$((attempt + 1))
                sleep 2
                continue
            fi
            ;;
    esac
    echo "Health check returned HTTP $status, expected 200" >&2
    if [ "$rc" = 0 ]; then rc=1; fi
    exit "$rc"
done
