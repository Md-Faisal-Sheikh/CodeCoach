#!/usr/bin/env bash
# Launch the CodeCoach server. Seeds the database on first run.
set -euo pipefail
cd "$(dirname "$0")"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

# Load .env if present (export every assignment).
if [[ -f .env ]]; then
  set -a; source .env; set +a
fi

# Seed only if the DB has no users yet (idempotent).
python3 -m app.seed || true

echo "CodeCoach on http://${HOST}:${PORT}  (Ctrl-C to stop)"
exec uvicorn app.main:app --host "$HOST" --port "$PORT"
