#!/usr/bin/env bash
# Rebuild the disposable database the end-to-end suite runs against.
#
# The suite needs a known starting point: no runs, no enrolments, and accounts whose
# passwords it knows. Recreating the database is cheaper and more honest than trying
# to clean one, and it keeps the suite from depending on the state a previous run
# left behind.
#
#   ./e2e/prepare-db.sh            # drop, create, migrate, seed
#   KEEP=1 ./e2e/prepare-db.sh     # migrate + seed an existing database
#
# Credentials come from e2e/fixtures/accounts.json, the same file the browser specs
# read, so the seeder and the suite cannot drift apart.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

E2E_DATABASE_URL="${E2E_DATABASE_URL:-postgresql+asyncpg://sbdma:sbdma_dev_pw@127.0.0.1:5432/sbdma_e2e}"
DB_NAME="$(python3 -c "import sys,urllib.parse as u;print(u.urlparse(sys.argv[1].replace('+asyncpg','')).path.lstrip('/'))" "$E2E_DATABASE_URL")"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON=python3

echo "==> target database: $DB_NAME"

# ---- seeded passwords: one source of truth -----------------------------------
eval "$("$PYTHON" - "$ROOT/e2e/fixtures/accounts.json" <<'PY'
import json, sys, shlex
data = json.load(open(sys.argv[1]))
for key, entry in data.items():
    if key.startswith("_") or not isinstance(entry, dict):
        continue
    print(f"export {entry['env']}={shlex.quote(entry['password'])}")
PY
)"
# The seeder flags every account must_change_password unless told otherwise; the
# suite signs in as-is, so the flag stays off for this throwaway database.
export SBDMA_SEED_FORCE_PASSWORD_CHANGE=0
export SBDMA_CREDENTIALS_FILE="${SBDMA_CREDENTIALS_FILE:-/tmp/sbdma-e2e-credentials.txt}"

if [[ "${KEEP:-0}" != "1" ]]; then
  echo "==> dropping and recreating $DB_NAME"
  PGPASSWORD="${PGPASSWORD:-sbdma_dev_pw}" dropdb --if-exists -h 127.0.0.1 -U "${PGUSER:-sbdma}" "$DB_NAME" 2>/dev/null || {
    echo "dropdb failed — if the app role lacks CREATEDB, run: sudo -u postgres dropdb $DB_NAME" >&2
  }
  PGPASSWORD="${PGPASSWORD:-sbdma_dev_pw}" createdb -h 127.0.0.1 -U "${PGUSER:-sbdma}" "$DB_NAME" || {
    echo "createdb failed — create the database once with a role that may: sudo -u postgres createdb -O sbdma $DB_NAME" >&2
    exit 1
  }
fi

echo "==> migrations"
cd "$ROOT/backend"
DATABASE_URL="$E2E_DATABASE_URL" "$PYTHON" -m alembic upgrade head

echo "==> seed"
DATABASE_URL="$E2E_DATABASE_URL" "$PYTHON" -m app.seed

echo "==> done: $(PGPASSWORD="${PGPASSWORD:-sbdma_dev_pw}" psql -h 127.0.0.1 -U "${PGUSER:-sbdma}" -d "$DB_NAME" -tAc \
  "select count(*) from information_schema.tables where table_schema='public'") tables"
