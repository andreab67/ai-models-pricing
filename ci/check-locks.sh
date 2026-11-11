#!/bin/sh
# Verify declared dependencies using the resolver, without editing the checkout.
set -eu
project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
check_dir=$(mktemp -d)
trap 'rm -rf "$check_dir"' EXIT HUP INT TERM
mkdir "$check_dir/ci" "$check_dir/api"
cp "$project_dir"/api/pyproject.toml "$project_dir"/api/requirements* "$check_dir/api/"
cp "$project_dir/ci/compile-locks.sh" "$check_dir/ci/"
cd "$check_dir/api"
for file in requirements.lock requirements-dev.lock; do
  sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "$file" > "$file.before"
done
sh ../ci/compile-locks.sh
for file in requirements.lock requirements-dev.lock; do
  sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "$file" > "$file.after"
  diff -u "$file.before" "$file.after"
done
