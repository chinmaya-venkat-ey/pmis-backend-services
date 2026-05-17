# pmis-masters-management — Migration Log

Second service ported in Phase 3 per Q19/Q29. Owns the `masters` Postgres schema (10 catalogs). Source: `C:\Programming\PMIS\PMIS-OpenProject\app\api\v3\master_data\routes.py` (the monolith's consolidated 2063-line CRUD surface) plus the per-table source models under `C:\Programming\PMIS\PMIS-OpenProject\app\infrastructure\db\models\`. Per Q3, `notification_templates` ownership moved here from notification-svc.

**Defining decision applied: Option C granular per-catalog RBAC.** Each catalog has its own `<catalog>:read` + `<catalog>:manage` permission codes (20 total). No catch-all `MASTER_DATA_VIEW` / `MASTER_DATA_MANAGE` gates anymore. See PLAN.md §9.6.

**User feedback applied during the port:**
- Only `vendors` retains the deleted_at + deleted_by audit columns; all other catalogs use `active=False` for delete/restore (uniform pattern).
- `is_builtin` is informational only — it does NOT block delete on any catalog. Built-in seeded rows are fully removable.
- `NotificationTemplate` restore conflict guard kept (option a): restore is rejected if another row is already active for the same `(template_kind, channel)`.

## Source

| Topic | Source (path:line) |
|---|---|
| master_data consolidated routes (72 endpoints) | `C:\Programming\PMIS\PMIS-OpenProject\app\api\v3\master_data\routes.py:193-2063` |
| Division model | `…\app\infrastructure\db\models\division.py:41` |
| Vendor model | `…\app\infrastructure\db\models\vendor.py:31` |
| Priority model | `…\app\infrastructure\db\models\priority.py:20` |
| ProjectStatusTransition model | `…\app\infrastructure\db\models\project_status_transition.py:43` |
| NotificationTemplate model | `C:\Programming\PMIS\PMIS-notification-service\app\db\models\notification_template.py:22` (was notification-svc; moved here per Q3) |
| Project status transition rules (in-code constants) | `…\app\api\v3\projects\services\transitions.py` (used to seed the catalog) |

## Endpoint port table

10 catalogs × 6 endpoints each + 1 extra on vendors = **61 endpoints** (vs 72 in the monolith — 11 endpoints folded into other catalogs or made auth-only-list). All paths use the verb-suffix scheme per PLAN.md §2.4.

### Catalog endpoints (pattern, repeated per catalog)

| METHOD | NEW PATH | HANDLER (new file:line) | SOURCE HANDLER (monolith path:line) | RBAC |
|---|---|---|---|---|
| GET | `/masters/<resource>/list` | `app/routes/<resource>_routes.py` (list endpoint) | `master_data/routes.py:193 / 312 / 422 / …` (per-catalog GET-list) | `<catalog>:read` |
| GET | `/masters/<resource>/{key}/details` | route file (details endpoint) | source (per-catalog GET-by-id) | `<catalog>:read` |
| POST | `/masters/<resource>/create` | route file (create endpoint) | source (POST /create) | `<catalog>:manage` |
| PATCH | `/masters/<resource>/{key}/update` | route file (update endpoint) | source (PATCH) | `<catalog>:manage` |
| DELETE | `/masters/<resource>/{key}/delete` | route file (delete endpoint) | source (DELETE) | `<catalog>:manage` |
| POST | `/masters/<resource>/{key}/restore` | route file (restore endpoint) | source (POST /restore) | `<catalog>:manage` |

Per-catalog specifics (resource URL, key path-param, source line of CRUD block):

| Resource URL | Key | Source CRUD block |
|---|---|---|
| `/masters/divisions/*` | `{code}` (str) | `master_data/routes.py:193-318` |
| `/masters/vendors/*` | `{vendor_id}` (UUID str) | `master_data/routes.py:565-662` |
| `/masters/resource-types/*` | `{rt_id}` (UUID str) | `master_data/routes.py:451-525` |
| `/masters/priorities/*` | `{code}` (str, UPPER) | `master_data/routes.py:1925-2049` |
| `/masters/project-categories/*` | `{code}` (str) | `master_data/routes.py:1443-1556` |
| `/masters/activity-types/*` | `{code}` (str) | `master_data/routes.py:1558-1669` |
| `/masters/activity-statuses/*` | `{code}` (str) | `master_data/routes.py:1786-1923` |
| `/masters/milestone-statuses/*` | `{code}` (str) | `master_data/routes.py:1671-1784` |
| `/masters/project-status-transitions/*` | `{row_id}` (int) | `master_data/routes.py:341-429` |
| `/masters/notification-templates/*` | `{template_id}` (int) | `C:\Programming\PMIS\PMIS-notification-service\app\routes\master_data_routes.py:81-261` |

### Extra vendor endpoint

| METHOD | NEW PATH | HANDLER (new file:line) | SOURCE | RBAC |
|---|---|---|---|---|
| GET | `/masters/vendors/{vendor_id}/projects/list` | `app/routes/vendor_routes.py` (`list_projects_for_vendor`) | `C:\Programming\PMIS\PMIS-OpenProject\app\api\v3\vendors\routes.py:740` | `vendors:read` |

Joins cross-schema: `masters.vendors` → `project.project_vendors` → `project.projects`.

### Endpoints intentionally NOT ported

| Old endpoint | Reason | Successor |
|---|---|---|
| `/api/v3/vendors/*` (legacy non-master, 7 routes) | Already deprecated; FE migrates to `/masters/vendors/*` | `/masters/vendors/*` |
| `/api/v3/resource_types/*` (legacy, 2 routes) | Same — already deprecated | `/masters/resource-types/*` |
| `/api/v3/divisions` (legacy catalogs router) | Unified into the masters surface | `/masters/divisions/list` |
| `/api/v3/project_status_transitions` (legacy) | Unified | `/masters/project-status-transitions/list` |
| `/api/v3/priorities` (legacy auth-only picker) | Unified under Option C granular `priorities:read` | `/masters/priorities/list` |

## Models ported (owned)

| Table | New model (file:line) | Source (path:line) | Schema changes vs source |
|---|---|---|---|
| `masters.divisions` | `app/models/division.py:35` | `…\PMIS-OpenProject\…\division.py:41` | SQLAlchemy 2.0 `Mapped[T]`; no behavioral change. |
| `masters.vendors` | `app/models/vendor.py:32` | `…\vendor.py:31` | `deleted_by` is now `String(36)` without a DB-level FK (cross-schema FK to users.users.id was unenforceable at migration time; constraint is logical/app-enforced). |
| `masters.resource_types` | `app/models/resource_type.py:24` | `…\resource_type.py:19` | **Dropped `deleted_at`** (per user feedback — use `active=False`). |
| `masters.priorities` | `app/models/priority.py:30` | `…\priority.py:20` | **Dropped `deleted_at`** (per user feedback). |
| `masters.project_categories` | `app/models/project_category.py:26` | `…\project_category.py:26` | Unchanged. |
| `masters.activity_types` | `app/models/activity_type.py:21` | `…\activity_type.py:26` | Unchanged. |
| `masters.activity_statuses` | `app/models/activity_status.py:21` | `…\activity_status.py:26` | Unchanged. |
| `masters.milestone_statuses` | `app/models/milestone_status.py:21` | `…\milestone_status.py:27` | Unchanged. |
| `masters.project_status_transitions` | `app/models/project_status_transition.py:30` | `…\project_status_transition.py:43` | Unchanged. |
| `masters.notification_templates` | `app/models/notification_template.py:30` | `C:\…\PMIS-notification-service\…\notification_template.py:22` | Moved schema from notification → masters per Q3; modernized to 2.0. |

## Cross-schema mirrors (read-only)

| Mirrored table | New mirror (file:line) | Canonical owner |
|---|---|---|
| `users.users` | `app/models/_cross_schema.py:34` | pmis-user-management (pending port) |
| `users.roles` | `_cross_schema.py:51` | pmis-user-management |
| `users.user_roles` | `_cross_schema.py:60` | pmis-user-management |
| `users.user_role_assignments` | `_cross_schema.py:70` | pmis-user-management (Doc-41 scoped) |
| `users.permissions` | `_cross_schema.py:82` | pmis-user-management |
| `users.role_permissions` | `_cross_schema.py:92` | pmis-user-management |
| `users.user_permissions` | `_cross_schema.py:101` | pmis-user-management |
| `users.revoked_tokens` | `_cross_schema.py:111` | pmis-user-management |
| `project.projects` | `_cross_schema.py:127` | pmis-project-management (for /vendors/{id}/projects/list) |
| `project.project_vendors` | `_cross_schema.py:139` | pmis-project-management |

Drift caught by Q24 CI test (lives in user-svc once that's ported).

## Alembic migrations

| Revision | File | Type | Description |
|---|---|---|---|
| `m1a000000001` | `alembic/versions/m1a000000001_create_masters_tables.py` | DDL | Creates the 10 catalog tables + indexes + the `uq_project_status_transitions_edge` unique constraint. No cross-schema FKs created. |
| `m1a000000002` | `alembic/versions/m1a000000002_seed_masters_builtins.py` | data (idempotent) | Seeds built-in rows: priorities (P1/P2/P3), milestone_statuses + activity_statuses (5 each), project_status_transitions (10 edges), notification_templates (5 templates). Uses `ON CONFLICT DO NOTHING` so the migration is safe to run after a cutover data-copy from `public.*`. |

Per-service alembic version table: `masters.alembic_version_masters`.

## Cross-service HTTP calls

NONE. masters-svc has no outbound HTTP to other PMIS services. Cross-domain reads (vendor → projects) go through the shared Postgres via the cross-schema mirror declarations.

## Layer-by-layer port summary

| Layer | Files | Notes |
|---|---|---|
| `core/` | `permissions.py` (20 codes), `errors.py`, `response.py`, `security.py` (JWT decode), `rbac.py` (5 dependency factories) | Permissions canonical lives here for now; will be promoted to user-svc once that's ported (PLAN.md §5.5). |
| `middleware/` | `request_context.py`, `error_handler.py`, `auth_middleware.py` | Auth middleware uses `RbacReadRepository` to hydrate `request.state.user_permissions` from cross-schema reads. |
| `utilities/` | `logger.py`, `timezones.py` | Duplicated from notification-svc. |
| `models/` | 10 catalog models + `_cross_schema.py` | All catalogs declared on `Base`; cross-schema mirrors on `MirrorBase` (excluded from alembic autogen). |
| `schemas/` | 10 catalog schema files + `vendor_project.py` (slim project response for /vendors/{id}/projects/list) | Pydantic v2 conventions throughout. |
| `repositories/` | 10 catalog repos + `rbac_read_repository.py` | Two distinct delete patterns: vendor uses `soft_delete()` + `restore()`; all others use `deactivate()` + `reactivate()`. |
| `services/` | 10 catalog services | Each enforces code uniqueness on create. NotificationTemplateService has the restore-conflict guard. VendorService accepts `caller_vendor_id` + `is_admin` for the row-level scoping placeholder. |
| `controllers/` | 10 catalog controllers | Thin HTTP adapters per Q8. VendorController has an extra `list_projects` method. |
| `routes/` | 10 catalog route files + `__init__.py` (composer) + `health_routes.py` | Each catalog mounts at `/masters/<resource>/*`; health at app root. Vendor routes pass `request.state.user_id` for soft-delete audit. |
| `dependencies.py` | 1 file with 10 controller factories | Standard FastAPI Depends pattern. |
| `main.py` | Wires AuthMiddleware + RequestContextMiddleware + (dev-only) CORSMiddleware + routers. | Replaces the scaffold stub. |

## Tests

| Layer | Count | Coverage |
|---|---|---|
| Unit | 8 across 2 files | Division service (create-conflict, get-not-found, builtin-not-blocking-delete, partial update); NotificationTemplate restore-conflict guard + create-conflict + builtin-not-blocking-delete |
| Integration | 11 across 2 files | `/health` × 4 (incl. 503 DB-down); RBAC gates × 7 (anonymous 401, reader 200/403, admin 200, vendors/divisions cross-permission verify) |
| Parity | 0 | Deferred — captured by `tools/capture_fixtures.py` against monolith pre-cutover. |

Run with: `cd services/pmis-masters-management && pytest -q`.

Pattern for the tests: a custom `_TestAuthMiddleware` (in conftest) replaces the real `AuthMiddleware` and lets per-test fixtures inject `user_id`/`user_permissions`/`is_admin` without minting JWTs.

## OpenAPI / Swagger quality (docs/OPENAPI_QUALITY.md)

- [x] Every endpoint has `summary` (≤60 chars) + `description`
- [x] Tags grouped per catalog (`divisions`, `vendors`, etc.)
- [x] Request schemas have field-level `description=` on every `Field(...)`
- [x] `response_model=` on every endpoint
- [x] 404/409/422 codes documented via `responses={...}` where applicable
- [x] No file-upload endpoints in this service (N/A)
- [x] No `deprecated=True` endpoints (full clean break for catalogs)
- [x] Auth requirement visible via `dependencies=[Depends(require_permission(...))]` (FastAPI propagates this to OpenAPI as a security requirement)

## Open issues / deviations

| Issue | Disposition |
|---|---|
| `caller_vendor_id` row-level scoping is a placeholder — passes `None` for now and `is_admin` from `request.state.is_admin`. | Refine during user-svc port. The vendor service has the hook; just needs the JWT claim populated. |
| Cross-schema `Project` + `ProjectVendor` mirrors point at schemas that don't yet exist at migration time (project-svc isn't ported). | Acceptable — the mirror declarations are Python-only; they only need the schemas to exist at runtime, which happens at cutover when project-svc's alembic runs. |
| Initial migration creates NO FK constraint between `masters.vendors.deleted_by` and `users.users.id`. | Intentional. Cross-schema cross-service FK at migration time fails when users-svc hasn't migrated yet. App enforces the logical FK via `request.state.user_id`. |
| `priorities:read` and other catalog codes don't yet have role-grant rows seeded — user-svc bootstrap migration will do that. | Required for masters-svc to be USEFUL post-cutover. Captured as a Phase-3 follow-up when user-svc is ported. |
| Parity tests deferred. | Will be captured against the monolith before cutover via `tools/capture_fixtures.py`. |

## Approval

- [ ] All ported routes match the endpoint plan in PLAN.md §2.4 + §9.6
- [ ] OpenAPI quality bar passes (manual inspection above)
- [ ] Unit tests pass (`pytest tests/unit -q`)
- [ ] Integration tests pass (`pytest tests/integration -q`)
- [ ] Alembic migration runs cleanly on a fresh staging Postgres (needs Docker; **Phase-3-test step still pending**)
- [ ] User approval to proceed to `pmis-user-management` ☐
