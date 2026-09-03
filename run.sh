#!/usr/bin/env bash
# Starts the service using the configured port (default 8080).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "Python 3 was not found (expected 'python' or 'python3')." >&2
  exit 127
fi

exec "$PYTHON_BIN" -m uvicorn app:app --host 0.0.0.0 --port "${PORT:-8080}"
