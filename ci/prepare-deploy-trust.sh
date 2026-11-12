#!/bin/bash
# Source in the deploy job so curl retains the additive bundle for the smoke.
source "$(dirname "${BASH_SOURCE[0]}")/trust-registry.sh"
printf '%s\n' "$ADDITIONAL_CA_CERT_BUNDLE" | openssl x509 -noout -checkend 0 >/dev/null || return 1
sh "$(dirname "${BASH_SOURCE[0]}")/healthcheck.sh" "$1"
