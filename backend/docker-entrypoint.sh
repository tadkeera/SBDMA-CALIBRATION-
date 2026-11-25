#!/bin/sh
# Migrations must finish before any worker starts, otherwise a beat/worker can
# query a partially migrated schema.
set -e

echo "[entrypoint] alembic upgrade head"
alembic upgrade head

if [ "${SBDMA_SEED_ON_START:-false}" = "true" ]; then
  echo "[entrypoint] seeding reference data"
  python -m app.seed
fi

exec "$@"
