#!/usr/bin/env bash
# Container entrypoint: create the PMC project, replicate its team assignments,
# and (optionally) override the D9/D10 resource cost values to the sheet.
#
#   COST_OVERRIDE=false (default) -> resource costs are whatever the server
#       computes from the uploaded rate card + contract-year snapshot.
#   COST_OVERRIDE=true            -> after creation, each D9/D10 resource line's
#       monthly_rate/computed_cost is overwritten to the resource-alignment
#       sheet value (needs DB access — see DB_* env below).
#
# Team replication runs from TEAM_SOURCE_PID (default = PMC-copy); set it to
# "none" to skip.
set -euo pipefail

PID_FILE="$(mktemp)"
export PMIS_PID_FILE="$PID_FILE"

# 1) create the project (any extra flags, e.g. --name "...", pass straight through)
bash /app/setup-pmc.sh --yes "$@"

# setup-pmc.sh wrote the created id + the resolved bases/creds here
# shellcheck disable=SC1090
source "$PID_FILE"
[ -n "${PID:-}" ] || { echo "entrypoint: could not read created project id" >&2; exit 1; }

# 2) replicate team owners/approvers from a source project (default PMC-copy)
TEAM_SOURCE_PID="${TEAM_SOURCE_PID:-acabf366-6a30-485d-80de-bb90e4cf9f1d}"
if [ -n "$TEAM_SOURCE_PID" ] && [ "$(printf '%s' "$TEAM_SOURCE_PID" | tr A-Z a-z)" != "none" ]; then
  echo "── replicating team assignments from $TEAM_SOURCE_PID ──"
  python3 /app/replicate-teams.py "$USER_BASE" "$PROJ_BASE" \
    "$LOGIN_USER" "$LOGIN_PASS" "$OTP" "$TEAM_SOURCE_PID" "$PID" \
    || echo "!! team replication failed (project still created) — check TEAM_SOURCE_PID"
else
  echo "TEAM_SOURCE_PID=none — skipping team replication."
fi

# 3) optional cost override -> sheet-exact D9/D10 resource costs (direct DB write)
COST_OVERRIDE="${COST_OVERRIDE:-false}"
if [ "$(printf '%s' "$COST_OVERRIDE" | tr A-Z a-z)" = "true" ]; then
  DB_HOST="${DB_HOST:-10.1.131.199}"; DB_PORT="${DB_PORT:-5432}"
  DB_USER="${DB_USER:-pmis_user}";    DB_NAME="${DB_NAME:-pmis_db}"
  DB_PASS="${DB_PASS:-aadhaarpmis2026}"
  echo "── COST_OVERRIDE=true: setting D9/D10 resource costs to the sheet (DB $DB_HOST:$DB_PORT/$DB_NAME) ──"
  python3 /app/gen-ratefix-sql.py /app/d9-d10-rate-fix.json "$PID" > /tmp/ratefix.sql
  PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f /tmp/ratefix.sql
  echo "cost override applied (finance now matches the sheet)."
else
  echo "COST_OVERRIDE=false — resource costs left as computed by the server."
fi

echo "──────────────────────────────────────────────"
echo "project ready: $PID"
