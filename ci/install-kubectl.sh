#!/bin/sh
# Official immutable kubectl release for the Linux amd64 CI runner.
set -eu
version=v1.37.0
sha256=6129359f4e1f3848a5572ccb0b26cf28b8ca08cef38c95a765b2f64a2c961a2f
download_dir=$(mktemp -d)
trap 'rm -rf "$download_dir"' EXIT HUP INT TERM
curl -fsSLo "$download_dir/kubectl" "https://dl.k8s.io/release/$version/bin/linux/amd64/kubectl"
printf '%s  %s\n' "$sha256" "$download_dir/kubectl" | sha256sum -c -
install -m 0755 "$download_dir/kubectl" /usr/local/bin/kubectl
