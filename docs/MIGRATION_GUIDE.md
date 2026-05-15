# PMIS Refactor — Migration Guide

Operator-facing how-to for cutting over from the monolith (`PMIS-OpenProject`) to the refactored four-service app (`PMIS-refactor/`).

This guide is the **what + when**. The **how** lives in [CUTOVER_RUNBOOK.md](CUTOVER_RUNBOOK.md) (step-by-step) and [DEPLOY_GUIDE.md](DEPLOY_GUIDE.md) (devops reference).

---

## What this migration is

A one-shot maintenance-window cutover that:

1. Creates four new Postgres schemas (`users`, `project`, `notification`, `masters`).
2. Each service's alembic chain creates empty tables in its owned schema.
3. Data is copied from `public.*` to the new schemas via [`../migrations/01_copy_data.sql`](../migrations/01_copy_data.sql).
4. New services start; FE base URL flips to nginx; monolith stops.
5. `public.*` tables remain (read-only) for a 7-day burn-in.
6. Post-burn-in, [`../migrations/02_drop_legacy.sql`](../migrations/02_drop_legacy.sql) drops the legacy tables.

Estimated downtime: **10–25 minutes** (validated on staging beforehand). Worst-case on a large DB: 60 min.

---

## Prerequisites

- **Postgres 16+** (Q31).
- **Docker / Docker Compose** for building service images.
- **Disk space**: ~2× the size of the prod DB on the same volume during burn-in (legacy `public.*` + new schemas exist simultaneously).
- **`pg_dump` snapshot capability** taken immediately before [`00_create_schemas.sql`](../migrations/00_create_schemas.sql) runs (Q32).
- **A staging Postgres** (`docker-compose.staging.yml` brings one up disposably) for validating migrations before touching prod.
- **Two DB roles**: `pmis_app` (DML) and `pmis_ddl` (DDL).

---

## Pre-cutover checklist

Run through this in the days leading up to the maintenance window:

- [ ] All four services pass `alembic upgrade head` against the staging Postgres
- [ ] `tools/capture_fixtures.py` has harvested fixtures for the 64 FE-called endpoints (from monolith)
- [ ] Each service's parity tests pass against staging (within tolerance)
- [ ] Cross-service smoke test (login → list projects → create milestone → add comment → fetch tree) passes on staging
- [ ] FE branch with updated `endpoint.js` (new `/user/*`, `/project/*`, `/notification/*`, `/masters/*` paths with verb suffixes per PLAN.md §2.4) is ready
- [ ] **Default-role check**: confirm `super_admin`, `admin` retain `MASTER_DATA_VIEW`; for non-admin roles (`org_admin`, `project_admin`, `project_member`, `division_member`), the picker endpoints (`/masters/<resource>/picker`) provide auth-only access without requiring `MASTER_DATA_VIEW` (resolves Risk #11 in PLAN.md §10)
- [ ] Maintenance window scheduled and announced
- [ ] DB snapshot taken (`pg_dump` of the prod DB)
- [ ] Rollback procedure rehearsed on staging

---

## Cutover sequence (maintenance window)

Follow [CUTOVER_RUNBOOK.md](CUTOVER_RUNBOOK.md) step-by-step. Summary:

1. Take a fresh `pg_dump` snapshot.
2. Stop the monolith.
3. Run [`00_create_schemas.sql`](../migrations/00_create_schemas.sql).
4. For each service: `docker compose run --rm pmis-<svc>-management alembic upgrade head`. (Order: notification → masters → users → project.)
5. Run [`01_copy_data.sql`](../migrations/01_copy_data.sql).
6. Run [`03_cleanup_permissions.sql`](../migrations/03_cleanup_permissions.sql).
7. `docker compose up -d` for the new app.
8. Flip FE `VITE_API_BASE_URL` and rebuild FE.
9. Smoke test through the FE (login, list projects, create milestone, navigate dashboard).
10. Green → declare cutover complete. Red → [`99_rollback.sql`](../migrations/99_rollback.sql) + restart monolith.

---

## Burn-in monitoring (7 days)

Watch for:

- 500-level errors mentioning `public.<table>`. None expected — new services do not import from `public`.
- FK violation errors on cross-schema references.
- Slow `revoked_tokens` lookups (Risk #8 in PLAN.md §10).
- Unexpected 403s on masters endpoints (Risk #11).

If a clean 7 days elapses, proceed to post-burn-in cleanup.

---

## Post-burn-in cleanup

After 7 days of clean operation:

1. Operator-confirmed: no error logs referencing `public.<table>`.
2. Run [`02_drop_legacy.sql`](../migrations/02_drop_legacy.sql). This is the **one-way** step that drops every legacy `public.*` table and the old monolith's `alembic_version` table.
3. Take another `pg_dump` snapshot post-drop (rollback boundary).

---

## Rollback procedure

See PLAN.md §8. Summary:

| Window | Action |
|---|---|
| Pre-cutover (staging fail) | Fix in code; do not initiate cutover. |
| In-cutover, data-copy failed | Drop new schemas (`99_rollback.sql`); monolith never stopped if it's before step 2. |
| In-cutover, smoke test failed | `docker compose down`; run `99_rollback.sql`; restart monolith; flip FE env back. ~5–10 min recovery. |
| Post-burn-in failure | Fix forward; rollback requires restore from `02_drop_legacy.sql` boundary snapshot. |

---

## Per-service migration notes

Each service has its own `MIGRATION_LOG.md` (Phase 3 deliverable). Templates in [MIGRATION_LOG.template.md](MIGRATION_LOG.template.md). Located at:

- `services/pmis-notification-management/MIGRATION_LOG.md` (first service ported)
- `services/pmis-masters-management/MIGRATION_LOG.md`
- `services/pmis-user-management/MIGRATION_LOG.md`
- `services/pmis-project-management/MIGRATION_LOG.md`

Each contains the source `path:line` for every ported handler so post-cutover correlation back to the monolith is possible.
