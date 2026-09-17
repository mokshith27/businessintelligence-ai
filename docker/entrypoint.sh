#!/bin/sh
# BusinessIntelligence.ai container entrypoint.
# Seeds the warehouse once, then runs the requested command.
set -e

if [ ! -f /repo/backend/data/warehouse/businessintelligence.duckdb ]; then
  echo "[entrypoint] Seeding deterministic warehouse (first run only)..."
  python /repo/docker/seed.py
fi

exec "$@"