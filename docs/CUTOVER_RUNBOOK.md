# PMIS Refactor — Cutover Runbook

Step-by-step script for the maintenance-window cutover. Each step is operator-gated with a checkbox.

**Total expected downtime: 10–25 minutes.** Worst-case on a large DB: 60 min.

**Roles:** "Operator" = the human running these steps. "DBA" = whoever owns the prod Postgres backup.

---

## Pre-flight (T-24h)

- [ ] Staging DB (`docker-compose.staging.yml`) seeded with a clone of prod (sanitized if needed).
- [ ] All four services pass `alembic upgrade head` against staging.
- [ ] Parity tests pass against staging.
- [ ] FE branch with updated `endpoint.js` is in CI green.
- [ ] Maintenance window announced to users (15-min unavailability minimum).
- [ ] On-call notified.

## T-0: Cutover start

### Step 1 — Snapshot (DBA-owned, Q32)

- [ ] DBA takes a `pg_dump` of prod DB:
  ```bash
  pg_dump -h <prod-host> -U pmis_app -d pmis -Fc -f pmis_pre_cutover_$(date +%Y%m%d_%H%M).dump
  ```
- [ ] Snapshot copied to a safe location (NOT the same volume as prod).
- [ ] Snapshot integrity verified:
  ```bash
  pg_restore --list pmis_pre_cutover_*.dump | head -20
  ```

### Step 2 — Stop monolith

- [ ] Stop the monolith and any partial-extraction services:
  ```bash
  cd /path/to/PMIS-OpenProject && docker-compose down
  ```
- [ ] Confirm no application is writing to prod DB:
  ```sql
  SELECT pid, usename, application_name, state, query_start
  FROM pg_stat_activity
  WHERE datname='pmis' AND state='active';
  ```
  Only your own session should appear.

### Step 3 — Create schemas

- [ ] Run [`../migrations/00_create_schemas.sql`](../migrations/00_create_schemas.sql):
  ```bash
  psql -h <prod-host> -U postgres -d pmis -f migrations/00_create_schemas.sql
  ```
- [ ] Verify schemas exist:
  ```sql
  SELECT schema_name FROM information_schema.schemata
  WHERE schema_name IN ('users','project','notification','masters');
  ```

### Step 4 — Run service migrations

Order: notification → masters → users → project (per Q19).

- [ ] notification-svc:
  ```bash
  docker compose run --rm pmis-notification-management alembic upgrade head
  ```
- [ ] masters-svc:
  ```bash
  docker compose run --rm pmis-masters-management alembic upgrade head
  ```
- [ ] users-svc:
  ```bash
  SUPERADMIN_BOOTSTRAP_PASSWORD='<not used here — only on a fresh env>' \
  docker compose run --rm pmis-user-management alembic upgrade head
  ```
- [ ] project-svc:
  ```bash
  docker compose run --rm pmis-project-management alembic upgrade head
  ```
- [ ] Verify each service's alembic version table:
  ```sql
  SELECT * FROM users.alembic_version_users;
  SELECT * FROM project.alembic_version_project;
  SELECT * FROM notification.alembic_version_notification;
  SELECT * FROM masters.alembic_version_masters;
  ```

### Step 5 — Copy data

- [ ] Run [`../migrations/01_copy_data.sql`](../migrations/01_copy_data.sql):
  ```bash
  psql -h <prod-host> -U pmis_app -d pmis -f migrations/01_copy_data.sql
  ```
- [ ] Verify row counts match between `public.*` and `<schema>.<table>`:
  ```sql
  SELECT 'users' AS schema, 'users' AS table, COUNT(*) FROM users.users
  UNION ALL
  SELECT 'public', 'users', COUNT(*) FROM public.users;
  -- Repeat for every migrated table.
  ```
- [ ] Spot-check a few rows for fidelity (random user, project, vendor).

### Step 6 — Cleanup permissions

- [ ] Run [`../migrations/03_cleanup_permissions.sql`](../migrations/03_cleanup_permissions.sql):
  ```bash
  psql -h <prod-host> -U pmis_app -d pmis -f migrations/03_cleanup_permissions.sql
  ```

### Step 7 — Start new app

- [ ] `cd /path/to/PMIS-refactor`
- [ ] `docker compose up -d`
- [ ] Wait for all four service health probes to be green:
  ```bash
  curl http://localhost/health/user
  curl http://localhost/health/project
  curl http://localhost/health/notification
  curl http://localhost/health/masters
  ```

### Step 8 — Flip FE base URL and rebuild

- [ ] Update FE `.env`:
  ```
  VITE_API_BASE_URL=http://<new-host>:80
  ```
- [ ] Rebuild FE image / redeploy FE container.
- [ ] Confirm browser reaches new app: load `/` (frontend), check Network tab in devtools shows requests going to new paths.

### Step 9 — Smoke test (manual, ~5 min)

Run through these scenarios as a logged-in user:

- [ ] Login (admin) succeeds; access token issued
- [ ] List projects loads
- [ ] Open a project's tree; M/A/T/S hierarchy renders
- [ ] Create a new milestone
- [ ] Add a comment with an attachment (file upload)
- [ ] Dashboard summary loads
- [ ] Logout
- [ ] Login as a non-admin user (project_member): pickers (divisions, priorities, resource_types) load via `/masters/<resource>/picker`
- [ ] Login as a non-admin user (project_admin): role-assignment write succeeds

### Step 10 — Decision

- [ ] **Smoke test GREEN** → cutover declared complete. Begin 7-day burn-in.
- [ ] **Smoke test RED** → proceed to Rollback (below).

---

## Rollback (if step 9 fails)

### R-1 — Stop new app

- [ ] `cd /path/to/PMIS-refactor && docker compose down`

### R-2 — Drop new schemas

- [ ] Run [`../migrations/99_rollback.sql`](../migrations/99_rollback.sql):
  ```bash
  psql -h <prod-host> -U postgres -d pmis -f migrations/99_rollback.sql
  ```

### R-3 — Restart monolith

- [ ] `cd /path/to/PMIS-OpenProject && docker-compose up -d`
- [ ] Verify monolith health: `curl http://<old-host>:8000/health`

### R-4 — Revert FE

- [ ] Update FE `.env`:
  ```
  VITE_API_BASE_URL=http://<monolith-host>:8000
  ```
- [ ] Rebuild FE / redeploy.

### R-5 — Notify

- [ ] Notify on-call and stakeholders that rollback completed.
- [ ] File a postmortem ticket; capture logs from the failed smoke test.

Estimated rollback time: 5–10 min.

---

## Burn-in monitoring (T+0 to T+7 days)

- [ ] Daily check of error logs for any `public.<table>` references — none expected.
- [ ] Daily check of error logs for FK violation errors — none expected.
- [ ] Confirm dashboard load time is within normal range.
- [ ] Confirm OTP flow works end-to-end at least once.
- [ ] Confirm masters CRUD (admin) works for at least one catalog.

---

## Post burn-in (T+7 days, after clean burn-in)

### P-1 — Final snapshot

- [ ] DBA takes a fresh `pg_dump`:
  ```bash
  pg_dump -h <prod-host> -U pmis_app -d pmis -Fc -f pmis_post_burnin_$(date +%Y%m%d).dump
  ```

### P-2 — Drop legacy tables

- [ ] Run [`../migrations/02_drop_legacy.sql`](../migrations/02_drop_legacy.sql):
  ```bash
  psql -h <prod-host> -U postgres -d pmis -f migrations/02_drop_legacy.sql
  ```
- [ ] Verify `public.*` is empty (apart from any non-PMIS-related tables that may share the DB):
  ```sql
  SELECT table_name FROM information_schema.tables
  WHERE table_schema='public' AND table_name LIKE ANY(ARRAY['users','projects','vendors','%_packages','meeting%']);
  -- Should return zero rows for PMIS-related tables.
  ```

### P-3 — Cleanup announcement

- [ ] Announce that cutover and burn-in are complete. New app is the system of record.
