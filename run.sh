#!/usr/bin/env bash
# Starts the service using the configured port (default 8080).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

exec python -m uvicorn app:app --host 0.0.0.0 --port "${PORT:-8080}"
