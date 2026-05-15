# PMIS Refactor — Cutover SQL Scripts

These scripts are the **cross-service one-shot DB migration** from monolith (`public.*`) to per-service schemas (`users`, `project`, `notification`, `masters`). They are NOT per-service alembic migrations (those live inside each service's `alembic/versions/`).

Run order during the maintenance window — see [../docs/CUTOVER_RUNBOOK.md](../docs/CUTOVER_RUNBOOK.md) for the full step-by-step.

| File | When to run | What it does |
|---|---|---|
| `00_create_schemas.sql` | Step 1 of cutover, after pg_dump snapshot | `CREATE SCHEMA` for users/project/notification/masters + role grants |
| `01_copy_data.sql` | Step 3 of cutover, after each service's alembic creates empty tables in its schema | `INSERT … SELECT * FROM public.<table>` for every migrated table; updates autoincrement sequences |
| `03_cleanup_permissions.sql` | Step 4 of cutover, after data copy | DELETEs legacy `meetings:*`, `work_packages:*`, `work_package_types:*` permission codes; drops `public.project_members` (Q12) |
| `02_drop_legacy.sql` | **POST burn-in (7+ days clean)** | Drops every `public.<table>` (legacy + migrated). DO NOT RUN UNTIL BURN-IN COMPLETES. |
| `99_rollback.sql` | Only during cutover window if smoke test fails | Drops the new schemas; `public.*` is untouched throughout cutover, so monolith can restart against it |

## Prerequisites

- Postgres 16+ (per Q31).
- Two DB roles: `pmis_app` (DML), `pmis_ddl` (DDL). See `00_create_schemas.sql` for grants.
- A `pg_dump` snapshot taken **before** `00_create_schemas.sql` runs (Q32 — operator step in runbook).
- Each service's alembic chain validated against `docker-compose.staging.yml` first.

## NOT a re-runnable artifact

These scripts run **once** per environment. Re-running `01_copy_data.sql` against a non-empty target schema raises FK / PK violations.
