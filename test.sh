#!/usr/bin/env bash
# Runs the complete offline test suite.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

exec python -m pytest -q
