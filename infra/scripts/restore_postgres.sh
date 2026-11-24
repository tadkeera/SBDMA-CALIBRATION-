#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# SBDMA Calibration Platform — PostgreSQL restore (documented, tested procedure)
#
#   ./restore_postgres.sh /srv/backups/sbdma_sbdma_calibration_20261125T020000Z.dump
#
# Point-in-Time Recovery (PITR) instead of a logical restore:
#   1. stop the api + worker pods (no writes during recovery)
#   2. restore the base backup into PGDATA
#   3. set recovery_target_time in postgresql.auto.conf
#   4. add restore_command reading the archived WAL
#   5. start postgres; it replays WAL up to the target timestamp and promotes
#   6. verify: SELECT count(*) FROM audit_logs; and run /api/v1/health
# Recovery is ALWAYS performed on a clone first. Restoring over production
# without a verified clone is prohibited by the QA SOP.
# ─────────────────────────────────────────────────────────────────────────────
set -Eeuo pipefail

DUMP_FILE="${1:?usage: restore_postgres.sh <dump-file>}"
: "${POSTGRES_USER:=sbdma}"
: "${POSTGRES_DB:=sbdma_calibration}"
: "${POSTGRES_HOST:=postgres}"

if [[ ! -f "${DUMP_FILE}" ]]; then
  echo "dump not found: ${DUMP_FILE}" >&2
  exit 1
fi

if [[ -f "${DUMP_FILE}.sha256" ]]; then
  echo "==> verifying checksum"
  sha256sum -c "${DUMP_FILE}.sha256"
fi

echo "==> restore target: ${POSTGRES_DB} on ${POSTGRES_HOST}"
read -r -p "Type the database name to confirm the destructive restore: " CONFIRM
[[ "${CONFIRM}" == "${POSTGRES_DB}" ]] || { echo "aborted"; exit 1; }

echo "==> terminating active connections"
psql --host="${POSTGRES_HOST}" --username="${POSTGRES_USER}" --dbname=postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${POSTGRES_DB}' AND pid <> pg_backend_pid();"

echo "==> recreating database"
psql --host="${POSTGRES_HOST}" --username="${POSTGRES_USER}" --dbname=postgres -c "DROP DATABASE IF EXISTS ${POSTGRES_DB};"
psql --host="${POSTGRES_HOST}" --username="${POSTGRES_USER}" --dbname=postgres -c "CREATE DATABASE ${POSTGRES_DB} ENCODING 'UTF8' TEMPLATE template0;"

echo "==> restoring (single transaction, exit on first error)"
pg_restore \
  --host="${POSTGRES_HOST}" \
  --username="${POSTGRES_USER}" \
  --dbname="${POSTGRES_DB}" \
  --single-transaction \
  --exit-on-error \
  --no-owner \
  --verbose \
  "${DUMP_FILE}"

echo "==> post-restore verification"
psql --host="${POSTGRES_HOST}" --username="${POSTGRES_USER}" --dbname="${POSTGRES_DB}" <<'SQL'
SELECT 'departments' AS table_name, count(*) FROM lab_departments
UNION ALL SELECT 'instruments', count(*) FROM instruments
UNION ALL SELECT 'protocols', count(*) FROM calibration_protocols
UNION ALL SELECT 'runs', count(*) FROM calibration_runs
UNION ALL SELECT 'audit_logs', count(*) FROM audit_logs;
SQL

echo "==> restore complete. Re-run /api/v1/health and the QA smoke checklist."
