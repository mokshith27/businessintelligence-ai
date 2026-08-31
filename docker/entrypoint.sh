#!/bin/sh
# BusinessIntelligence.ai container entrypoint.
# Seeds the warehouse once, then runs the requested command.
set -e

if [ ! -f /app/data/warehouse/businessintelligence.duckdb ]; then
  echo "[entrypoint] Seeding deterministic warehouse (first run only)..."
  python /app/docker/seed.py
fi

exec "$@"