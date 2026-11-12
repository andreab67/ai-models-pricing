#!/bin/sh
# Source this file to augment public trust roots with the reviewed internal CA.
: "${ADDITIONAL_CA_CERT_BUNDLE:?Missing trusted registry CA}"
test -r /etc/ssl/certs/ca-certificates.crt
cat /etc/ssl/certs/ca-certificates.crt > /tmp/registry-ca-bundle.pem
printf '%s\n' "$ADDITIONAL_CA_CERT_BUNDLE" >> /tmp/registry-ca-bundle.pem
export SSL_CERT_FILE=/tmp/registry-ca-bundle.pem
export CURL_CA_BUNDLE="$SSL_CERT_FILE"
