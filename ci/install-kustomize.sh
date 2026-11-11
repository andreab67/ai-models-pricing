#!/bin/sh
# Official release asset and published checksum, Linux amd64 CI runner.
set -eu
version=5.8.3
sha256=cb9e31198d3f63b44848bd0afc4c8efc56e6cfef9c93a4a39a211940e6decd61
download_dir=$(mktemp -d)
trap 'rm -rf "$download_dir"' EXIT HUP INT TERM
curl -fsSLo "$download_dir/kustomize.tar.gz" \
  "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize/v$version/kustomize_v${version}_linux_amd64.tar.gz"
printf '%s  %s\n' "$sha256" "$download_dir/kustomize.tar.gz" | sha256sum -c -
tar -xzf "$download_dir/kustomize.tar.gz" -C "$download_dir" kustomize
install -m 0755 "$download_dir/kustomize" /usr/local/bin/kustomize
