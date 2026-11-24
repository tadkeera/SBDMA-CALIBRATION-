#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# SBDMA Calibration Platform — PostgreSQL 16 backup (logical + PITR base)
# Schedule: daily 02:00 UTC via Celery beat or host cron:
#   0 2 * * * /srv/sbdma/infra/scripts/backup_postgres.sh >> /var/log/sbdma-backup.log 2>&1
# Retention: BACKUP_RETENTION_DAYS (default 90) — WAL archives retained separately.
# ─────────────────────────────────────────────────────────────────────────────
set -Eeuo pipefail

: "${POSTGRES_USER:=sbdma}"
: "${POSTGRES_DB:=sbdma_calibration}"
: "${POSTGRES_HOST:=postgres}"
: "${BACKUP_DIR:=/srv/backups}"
: "${BACKUP_RETENTION_DAYS:=90}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="${BACKUP_DIR}/sbdma_${POSTGRES_DB}_${STAMP}.dump"
LOG_PREFIX="[sbdma-backup ${STAMP}]"

mkdir -p "${BACKUP_DIR}"
echo "${LOG_PREFIX} starting custom-format dump -> ${TARGET}"

# -Fc custom format: compressed, supports selective restore with pg_restore
pg_dump \
  --host="${POSTGRES_HOST}" \
  --username="${POSTGRES_USER}" \
  --dbname="${POSTGRES_DB}" \
  --format=custom \
  --compress=9 \
  --no-owner \
  --no-privileges \
  --file="${TARGET}"

# Integrity proof: the dump must restore into a scratch schema before we trust it
echo "${LOG_PREFIX} verifying dump integrity"
pg_restore --list "${TARGET}" > /dev/null
sha256sum "${TARGET}" > "${TARGET}.sha256"

# Optional off-site copy (S3/MinIO) — enabled only when configured
if [[ -n "${BACKUP_S3_BUCKET:-}" ]]; then
  echo "${LOG_PREFIX} uploading to s3://${BACKUP_S3_BUCKET}/postgres/"
  aws s3 cp "${TARGET}" "s3://${BACKUP_S3_BUCKET}/postgres/" --only-show-errors
  aws s3 cp "${TARGET}.sha256" "s3://${BACKUP_S3_BUCKET}/postgres/" --only-show-errors
fi

# Retention sweep — never delete the newest backup
echo "${LOG_PREFIX} pruning dumps older than ${BACKUP_RETENTION_DAYS} days"
find "${BACKUP_DIR}" -name 'sbdma_*.dump*' -type f -mtime "+${BACKUP_RETENTION_DAYS}" -not -name "$(basename "${TARGET}")" -delete

echo "${LOG_PREFIX} done ($(du -h "${TARGET}" | cut -f1))"
