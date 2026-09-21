#!/usr/bin/env bash
# Start backend + frontend for local development. Ctrl-C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$ROOT/.venv/bin/python" "$ROOT/scripts/check_infra.py"

cleanup() { kill 0; }
trap cleanup EXIT

(cd "$ROOT/backend" && "$ROOT/.venv/bin/uvicorn" main:app --reload --port 8000) &
(cd "$ROOT/frontend" && npm run dev) &

wait
