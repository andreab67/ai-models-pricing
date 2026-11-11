#!/bin/sh
# Regenerate on the runtime interpreter and Linux platform.
set -eu
cd "$(dirname "$0")/../api"
python -c 'import sys; assert sys.version_info[:2] == (3, 14), "Use Python 3.14 to regenerate locks"'
export CUSTOM_COMPILE_COMMAND="sh ci/compile-locks.sh"
pip-compile --generate-hashes --allow-unsafe --strip-extras --resolver=backtracking \
  --output-file=requirements.lock pyproject.toml
pip-compile --extra=dev --constraint=requirements.lock --generate-hashes --allow-unsafe \
  --strip-extras --resolver=backtracking --output-file=requirements-dev.lock \
  pyproject.toml requirements-tools.in
