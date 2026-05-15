# PMIS Refactor — Audit (Checkpoint 2)

Synthesized from five per-repo audits under [audit/raw/](C:/Programming/PMIS-refactor/audit/raw/). Every concrete claim in those raw reports cites `path:line`; this synthesis quotes the citation where decision-relevant and otherwise points back to the raw file. Use prefixes `OBSERVED:` (read in source), `INFERRED:` (deduced), `[UNVERIFIED]` (not confirmable from current reads).

The audit covers four backend repos plus a narrow read of the FE API client:

| Repo | Path | Port | Role today |
|---|---|---|---|
| Monolith | `PMIS-OpenProject` | 8000 | De-facto gateway + fallback impl for every domain |
| User-svc | `PMIS-user-management` | 8001 | Partial extraction of user/auth |
| Notification-svc | `PMIS-notification-service` | 8002 (container 8000) | Email/SMS/OTP dispatch + notification_templates owner |
| Project-svc | `PMIS-project-management` | 8003 | Partial extraction of project domain |
| Frontend | `PMIS-Frontend-OpenProject` | 3000 | READ-ONLY for this refactor |

Decisions locked at Checkpoint 1 (see [REFACTOR_DECISIONS.md](C:/Programming/PMIS-refactor/REFACTOR_DECISIONS.md)):
- Per-service Postgres schemas (`user.`, `project.`, `notification.`, `masters.`), shared instance.
- Build the new app at `PMIS-refactor/` clean; cut over from monolith. No runtime dependency on monolith.
- Every meaningful endpoint must land in exactly one target service before the monolith goes away.
- `work_packages`, `meetings`, "old project impl" → enumerated and excluded (not ported).
- Shared `SECRET_KEY`, local HS256 decode in every service.
- Nginx routes by prefix to each service. FE base-URL change is one env var; path-prefix change is one file (`endpoint.js`).

---

## §1 Service inventory (per repo)

This section summarizes each repo's surface area. **Full route, model, and migration tables with `path:line` citations live in the raw reports** — [monolith.md](C:/Programming/PMIS-refactor/audit/raw/monolith.md), [user-svc.md](C:/Programming/PMIS-refactor/audit/raw/user-svc.md), [notification-svc.md](C:/Programming/PMIS-refactor/audit/raw/notification-svc.md), [project-svc.md](C:/Programming/PMIS-refactor/audit/raw/project-svc.md), [frontend.md](C:/Programming/PMIS-refactor/audit/raw/frontend.md).

### 1.1 Monolith (`PMIS-OpenProject`)

**OBSERVED counts:** ~218 routes, 41 SQLAlchemy models, 45 alembic migrations (single head `baddc1146b85`), 339 Python files under `app/`. Python 3.12, FastAPI 0.135.3, SQLAlchemy 2.0.49.

**Routes by family** (citations in raw report):

| Family | Routes | Disposition (preview — §3 fixes per-row) |
|---|---:|---|
| users (login, refresh, OTP, password-reset, CRUD, perms, roles) | 23 | move → user-svc (matches sibling) |
| projects (CRUD, save/publish/close, role-assignments forwards, attachments, discussion-feed, audit-logs) | 18 | move → project-svc (matches sibling) |
| milestones (project-scoped + standalone) | 6 | move → project-svc |
| activities (milestone-scoped + standalone) | 6 | move → project-svc |
| tasks (activity-scoped + standalone) | 6 | move → project-svc |
| subtasks (task-scoped + standalone + nested) | 7 | move → project-svc |
| tree (full M/A/T/S hierarchy) | 1 | move → project-svc |
| vendors (legacy, deprecated; mirrored under `/master/vendors`) | 8 | merge → masters (legacy paths deleted) |
| resource_types (legacy) | 2 | merge → masters (legacy deleted) |
| catalogs (legacy `/divisions`, `/project_status_transitions`, `/priorities`) | 3 | merge → masters (legacy deleted, except `/priorities` keep — see §3) |
| roles (legacy, deprecated) | 9 | merge → user-svc `/user/roles` (legacy deleted) |
| permissions (legacy, deprecated) | 5 | merge → user-svc `/user/permissions` (legacy deleted) |
| master_data (consolidated CRUD, 11 catalog families, 72 endpoints) | 72 | SPLIT — divisions/vendors/catalogs → masters-svc; roles/permissions → user-svc; notification_templates → notification-svc |
| comments (polymorphic, 4 target_kinds via factory) | 9 | move → project-svc |
| attachments (polymorphic, doc-35 unified onto comments JSON) | 9 | move → project-svc |
| dashboard (admin-only aggregations) | 6 | move → project-svc |
| project_members (superseded by role-assignments) | 4 | **delete-deprecated** (table already migrated to `user_role_assignments` — see §5) |
| **work_packages** | 6 | **legacy-exclude** (user-flagged) |
| **work_package_types** | 5 | **legacy-exclude** |
| **meetings** (incl. agenda_items, participants) | 13 | **legacy-exclude** (user-flagged) |
| app-level (`/health`, `/`, `/files/{key}`) | 3 | each service gets its own `/health` + `/ready` (decision 8d) |

**Middleware order** (`app/main.py:90-102`, outermost → innermost): `CORSMiddleware` → `NotificationServiceProxyMiddleware` → `UserServiceProxyMiddleware` → `AuthenticationMiddleware` → `LoggingMiddleware`. The two proxy middlewares are what make the monolith function as a gateway today; the new app replaces them with nginx.

**Auth/RBAC** (`app/core/security.py:46-107`, `app/core/middleware/auth.py:50-109`, `app/core/middleware/rbac.py:42-430`): JWT decode with shared `SECRET_KEY`, HS256; per-request hydration of `user_permissions`, `is_admin`, `scoped_permissions: Dict[(kind, id), Set[str]]`. Permission codes are flat strings like `"users:create"`, `"projects:publish"`. Scope-aware checks via `require_project_permission(code)` resolve project id from path or via ancestor SQL lookup (`rbac.py:117-251`).

**Cross-service outbound HTTP** (monolith calls):

| Caller (file:line) | Target | Purpose |
|---|---|---|
| `app/main.py:386` | `${NOTIFICATION_SERVICE_URL}/api/v1/health` | startup diagnostic |
| `app/shared/notifications.py:339, 354` | notification-svc `/api/v1/notifications/{email,sms}/send` | legacy dispatch path |
| `app/shared/notification_service_client.py:69` | notification-svc `/api/v3/master/notification_templates/...` | proxy when `NOTIFICATION_SERVICE_PROXY_ENABLED=true` |
| `app/shared/user_service_client.py` | user-svc `/api/v3/{users,master/roles,master/permissions,role-grants}/...` | proxy when `USER_SERVICE_PROXY_ENABLED=true` |
| `app/api/v3/projects/routes.py:1151, 1168` | user-svc `/api/v3/projects/{id}/role-assignments` | explicit forward for project-scoped grant writes |
| `app/api/v3/vendors/routes.py:791` | user-svc `/api/v3/vendors/{id}/users` | explicit forward |

INFERRED: no retries anywhere; every call is single-attempt with fail-closed 503.

**Env vars consumed** (raw report §2 has full list, 40+ vars). Notable for refactor:
- `DATABASE_URL` + `DATABASE_URL_MIGRATIONS` (separate roles for DML vs DDL)
- `MIGRATIONS_AUTORUN=True`, `MIGRATIONS_REQUIRED=True` — runs `alembic upgrade head` on boot
- `BOOTSTRAP_ADMIN_*` (disabled per doc 42b) / `BOOTSTRAP_SUPERADMIN_*` (still active)
- `UNIVERSAL_OTP_ENABLED` / `UNIVERSAL_OTP_CODE="000000"` — break-glass backdoor; `main.py:46-52` logs warning when enabled
- `ATTACHMENTS_*` (max 26 MB default, `year_month` subdir strategy, 90-day retention "future cron")
- `FILE_SERVER_*` (external file server + local fallback)
- `USER_SERVICE_*`, `NOTIFICATION_SERVICE_*` (URL + timeout + proxy-enabled flag for each)
- `REQUIRE_2FA=True`, `OTP_*` (TTL/length/attempts)
- `CORS_ORIGINS=["*"]` (current); will narrow per decision 8e

**`init_db()` complexity** (`app/infrastructure/db/session.py:209-619`): runs `alembic upgrade head` subprocess on Postgres; on SQLite it runs `create_all` + a 300+ line "self-heal" ALTER block. INFERRED: SQLite path is a dev-only artefact. The new app should not replicate this — clean alembic, no boot-time DDL heal.

### 1.2 User-svc (`PMIS-user-management`)

**OBSERVED counts:** 47 routes (`/api/v3` prefix), 15 SQLAlchemy models on `Base.metadata`, **2 alembic migrations** only (head `b9f4d27e1a83`), ~98 Python files under `app/`. Python 3.11, FastAPI 0.115.6, SQLAlchemy 2.0.36, alembic 1.18.1. Argon2 password hashing (`argon2-cffi`).

**Routes by family:**

| Family | Routes |
|---|---:|
| Users (login/OTP/refresh + CRUD + perms-by-user + roles-by-user legacy) | 24 |
| Master (delegates to legacy roles/permissions with `Deprecation` header stripped) | 15 |
| Role-assignments (scoped doc-41 + grantable-roles matrix) | 10 |
| Roles (legacy, deprecated) | 9 |
| Permissions (legacy, deprecated) | 5 |
| Top-level `/health`, `/` | 2 |

**Models:**
- **CORE-USER** (11): `users`, `roles`, `permissions`, `user_roles`, `role_permissions`, `user_permissions`, `user_role_assignments`, `revoked_tokens`, `password_reset_tokens`, `otp_codes`, `notification_log`.
- **CROSS-DOMAIN-READ-ONLY** (4): `divisions`, `projects`, `vendors`, `project_vendors`. Used for FK target validation, vendor/project label embedding in user responses, org-scope RBAC walks (`role_assignments/services.py:143-150`).
- **ORPHAN** (1): `milestone_vendors` — FKs stripped, no route or service references it. Per docstring (`models/milestone_vendor.py:1-9`): "user-mgmt never writes this table". Kept only by an import chain.

**Migration gap (CRITICAL):** Initial migration `7e3fa9c21b4d` creates the *legacy* schema (int PK `users.id`, `admin` boolean column, `roles.permissions` JSON). Current ORM expects UUID PK / post-Doc-26 shape. **There is no migration in this repo that performs the int→UUID flip or drops the legacy columns.** The user-svc relies on the monolith's alembic chain having already done that work in the shared DB. If user-svc is ever booted against a DB the monolith hasn't migrated, routes crash with column-not-found. This pattern must NOT carry into the new app — each service must own a complete migration chain for its tables.

**Auth/RBAC:** Same shape as monolith — `app/core/security.py:89-107` decodes locally with shared `SECRET_KEY`; `app/core/middleware/auth.py:50-110` hydrates scoped permissions; `app/core/middleware/rbac.py` exposes `require_permission / require_any_permission / require_authenticated / require_admin / require_project_permission / require_org_permission`. Permission constants in `app/core/permissions.py` are duplicated from monolith's — manual sync note in the file header.

**Outbound HTTP:** One call site (`app/shared/notifications.py:178-186`) — POSTs to `${NOTIFICATION_SERVICE_URL}/api/v1/notifications/dispatch` for OTP + password-reset. Gated by `NOTIFICATION_CLIENT=mock|http`. No retry; failure → `notification_log.status='failed'`.

**Duplicate `src/` tree at repo root:** Complete near-copy of `app/`, `alembic/`, `tests/` lives under `src/`. Dockerfile only copies top-level `app/` + `alembic/`. The duplicate has stale models (e.g. `src/app/infrastructure/db/models/project_member.py` for a table since unified into `user_role_assignments`). INFERRED: pre-extraction snapshot, never cleaned up. Source repo only — refactor doesn't touch it.

**`app/api/v3/users/schemas.py` + `schemas/` package:** Both exist. Import-shadowing risk (Python prefers the package). Refactor should pick one.

**Folder shape:** DDD-ish — `app/{api, core, domain, infrastructure, shared}` with per-resource subtree under `api/v3/<resource>/`. Diverges from notification-svc's flat shape; refactor flattens.

### 1.3 Notification-svc (`PMIS-notification-service`)

**OBSERVED counts:** 14 routes, **0 alembic migrations** (uses monolith's alembic chain for shared tables; uses `Base.metadata.create_all` for SQLite dev), 41 Python files. Python 3.11, FastAPI 0.115.0, SQLAlchemy 2.0.36. SMTP (stdlib `smtplib` — no `aiosmtplib`), SendGrid HTTP, Twilio, MSG91.

**Routes by family:**

| Family | Prefix | Routes | Auth |
|---|---|---:|---|
| Legacy dispatch | `/api/v1/notifications/{email,sms,otp}` | 4 | none (network trust) |
| Templated dispatch (Doc-38) | `/api/v1/notifications/dispatch` | 1 | none (network trust) |
| Cron daily-digest | `/api/v1/notifications/cron/daily-digest` | 1 | `X-Cron-Secret` header |
| Notification-templates master CRUD (Doc-38) | `/api/v3/master/notification_templates` | 6 | JWT + `master_data:view` / `master_data:manage` |
| Health, root | `/api/v1/health`, `/` | 2 | none |

**Stateless? No.** Service owns `notification_templates` (R/W) and **read-only-mirrors 7 tables from user-svc/monolith** for the auth middleware and daily-digest: `role_permissions`, `user_roles`, `user_permissions`, `roles`, `revoked_tokens`, `users`, plus digest-only `projects`, `milestones`, `activities`, `user_role_assignments`, `project_vendors`. The RBAC reads use **raw `text()` SQL** in `app/db/repositories/rbac_read_repository.py:25-63` against the user-svc-owned schema. Schema drift in user-svc silently demotes every authed request to anonymous (the `except Exception` catch at `auth_middleware.py:93-97` swallows it).

**OTP store is in-memory** (`app/services/otp_service.py:36`). Comment at `:30-33` acknowledges Redis as the intended production target. Blocks horizontal scaling. Refactor must address.

**Auth/RBAC:** `app/core/auth.py:36-56` (JWT decode), `app/core/permissions.py:15-16` (just two codes: `MASTER_DATA_VIEW`, `MASTER_DATA_MANAGE`), `app/middleware/auth_middleware.py:50-132`. Public-path allow-list is hard-coded at `:32-40` (every `/api/v1/notifications/*`, `/api/v1/health`, `/docs`, `/redoc`, `/openapi.json`, `/`).

**Inbound callers (`OBSERVED`):**

| Caller (file:line) | Endpoint |
|---|---|
| monolith `app/shared/notifications.py:339, 354` | `/api/v1/notifications/{email,sms}/send` |
| monolith `app/shared/notification_service_client.py:126` | `/api/v3/master/notification_templates/*` |
| user-svc `app/shared/notifications.py:168` | `/api/v1/notifications/dispatch` |

**Port:** container 8000, host-mapped 8002 (`deploy.sh:89`, `docker-compose.yml:11`). The "8002" in the brief is the public port; the in-process port is 8000. Same convention should apply to every backend service in the refactor.

**Folder shape (REFERENCE for refactor):** 8 top-level dirs under `app/`: `config/`, `controllers/`, `core/`, `db/{models,repositories}`, `middleware/`, `routes/`, `schemas/`, `services/`, `utilities/`. **`controllers/` is half-adopted** — only used for legacy email/sms/otp; Doc-38 routes (`dispatch`, `cron`, `master_data_routes`) call services directly. **Decision needed before adopting as reference shape** (raised in §6 + §7).

**Dead deps:**
- `jinja2==3.1.4` declared but never imported (Doc-38 uses `str.format_map` instead — `template_service.py:96-105`)
- `MIGRATIONS_AUTORUN` / `MIGRATIONS_REQUIRED` settings declared but never referenced

**Logic leak:** `schemas/notification_template.py:18-60` hosts `validate_placeholder_set` + `ALLOWED_PLACEHOLDERS` map. Master-data route imports the helper. Should live in `services/template_service.py` or `core/`.

### 1.4 Project-svc (`PMIS-project-management`)

**OBSERVED counts:** 105 CURRENT routes + 11 LEGACY (deprecated wire surface), 32 SQLAlchemy models (24 owned, 8 read-only mirrors of user-svc tables), 13 alembic migrations (linear, single head `d4f9b2e8a317`), 221 Python files in `app/`, ~32,521 LOC. Python 3.11, FastAPI 0.115.6, SQLAlchemy 2.0.36, alembic 1.18.1.

**Routes by family (CURRENT):**

| Family | Routes | Notes |
|---|---:|---|
| projects | 16 | incl. `assignable-users`, `audit-logs`, `attachments`, `discussion-feed`, `tree` |
| milestones | 6 | project-scoped + standalone |
| activities | 6 | milestone-scoped + standalone |
| tasks | 6 | activity-scoped + standalone |
| subtasks | 7 | nested via `parent_subtask_id` |
| comments | 9 | 4 target_kinds × (POST + GET) + 1 DELETE |
| attachments | 9 | 4 target_kinds × (POST + GET) + 1 DELETE |
| master_data | 48 | divisions, project_status_transitions, resource_types (own), + delegated vendors, project_categories, activity_types, activity_statuses, milestone_statuses, priorities |
| dashboard | 6 | admin-only (`require_admin()` on router) |
| catalogs (legacy reads) | 3 | `/divisions`, `/project_status_transitions`, `/priorities` |
| vendors (legacy) | 7 | every endpoint deprecated to `/master/vendors/*` |
| resource_types (legacy) | 2 | deprecated |
| root, health, `/files/{key}` | 3 | `/files` conditional on env flag |

**Routes by family (LEGACY for refactor):** 11 — the 7 vendor + 2 resource_type + 2 catalogs (divisions, project_status_transitions) that have direct master-data successors. Catalog `/priorities` is FE picker — kept (see §3).

**Models:**
- **CURRENT (24, owned by project-svc):** `projects`, `project_audit_logs`, `project_vendors`, `project_status_transitions`, `project_categories`, `milestones`, `milestone_dependencies`, `milestone_vendors`, `milestone_statuses`, `activities`, `activity_dependencies`, `activity_resources`, `activity_types`, `activity_statuses`, `tasks`, `task_dependencies`, `task_resources`, `subtasks`, `subtask_dependencies`, `subtask_resources`, `comments`, `divisions`, `priorities`, `resource_types`, `vendors`.

> Note: `divisions`, `vendors`, `priorities`, `resource_types`, `project_categories`, `activity_types`, `activity_statuses`, `milestone_statuses`, `project_status_transitions` are catalog/reference tables. Per Decision 6, ownership of these moves to a separate **masters-svc** in the refactor. Project-svc retains FK-target read access (cross-schema FK).

- **READ-ONLY MIRRORS (8) of user-svc tables:** `users`, `revoked_tokens`, `roles`, `permissions`, `role_permissions`, `user_roles`, `user_permissions`, `user_role_assignments`. Used for auth middleware + scope checks. project-svc only reads; writes happen on user-svc.

**Migrations:** Single head `d4f9b2e8a317`, linear. Version table `alembic_version_project_svc` (separate from monolith's `alembic_version` and user-svc's `alembic_version_user_svc`). All operations target project-svc's own tables; initial migration uses `CREATE TABLE IF NOT EXISTS` so running against the shared DB is no-op for existing tables. INFERRED: no migrations modify user-svc-owned tables — `[UNVERIFIED]` (would need per-file inspection).

**Auth/RBAC:** Same shape as monolith. `app/core/security.py:89` (JWT decode), `app/core/middleware/auth.py:50-105` (hydrate state). **Auth middleware opens TWO fresh DB sessions per authenticated request** — one for revoked_token check, one for permission hydrate — both via `SessionLocal()` not the request-bound session. Performance cost on hot endpoints; flag for the new app.

**Cross-service HTTP: NONE.** project-svc does not call user-svc / notification-svc. All cross-service coordination is via the shared DB (raw SQL joins to `users`, `user_role_assignments`, etc).

**Duplicate `src/` tree at repo root:** Complete second copy of the service (~95 files under `src/app/`, plus `src/alembic/`, `src/tests/`, etc). Dockerfile only copies top-level `app/` + `alembic/`. The `src/` tree contains:
- An older `app/api/router.py` missing the `dashboard_router` registration
- A `src/app/infrastructure/db/models/project_member.py` for a table since unified into `user_role_assignments`
- 6 alembic migration duplicates
- 9 outdated tests

This is **the "old implementation of project modules"** the user flagged. Source-only; refactor doesn't touch it. The active service is `app/` only.

**Dead permission constants:** `MEETINGS_*` and `WORK_PACKAGES_*` constants exist in active `app/core/permissions.py` and `app/core/rbac.py` (not just `src/`). They're seeded into the permissions catalog on boot and emitted as HAL links by `app/core/response.py` link builders. Need explicit removal — they're not dead-file removable.

**Folder shape:** Hybrid — `app/{api/v3/<resource>/{controller,routes,schemas,permissions,services/}, core, domain, infrastructure/db, shared}`. Deep-nested verb-per-file pattern (`projects/services/{audit,close,create,delete,get,list,publish,save,transitions,update,upsert}.py`). Flattening proposed in §6.

### 1.5 Frontend API client (`PMIS-Frontend-OpenProject`)

**Read-only. Not modified.** Scope: API layer only.

- **HTTP client:** native `fetch` (no axios, no rtk-query). React 19.2.4, Vite 8, react-router-dom 7.
- **Central endpoint map:** `src/api/endpoint.js` — **64 distinct endpoints** declared in one object literal (`endpoint.js:11-130`).
- **Base URL:** Single env var `VITE_API_BASE_URL`, read in one place (`src/api/client.js:3`), defaults to `http://10.1.131.199:8000/`. One-base-URL claim **confirmed TRUE**.
- **Path prefix `/api/v3` is literal-repeated 64 times inside `endpoint.js`** — not extracted into a constant. The prefix change is a **one-file (~64 lines) edit**, not a one-line edit. Alternative: keep `/api/v3` and have nginx rewrite per service (zero FE change). See §4.
- **`REFRESH_PATH`** is duplicated at `client.js:10` (`/api/v3/users/refresh`) — same path as `ENDPOINTS.auth.refresh`. Should be deduplicated.
- **Token storage:** dual sessionStorage + localStorage + legacy mirror keys (`pmis_token` / `auth_token`).
- **Refresh logic:** single-flight 401 → POST `/refresh` → retry original request (`client.js:154-279`).
- **5 endpoints declared in map with no observed caller** in the inspected files (`endpoint.js:84, 98, 108, 118, 63`):
  - `milestones.attachments`, `activities.attachments`, `tasks.attachments`, `subtasks.attachments` (the polymorphic attachment paths — likely wired from Components, `[UNVERIFIED]`)
  - `roles.list` (`/api/v3/master/roles`)

The FE call list is the canonical "actually in use" signal for §3 reconciliation: **endpoints NOT in the FE list are candidates for `delete-deprecated`** (subject to grep confirmation against `components/` for the 5 unobserved ones).

---

## §2 Cross-service duplication matrix

Only paths implemented in 2+ repos are listed. "monolith" column means the route exists in `PMIS-OpenProject`. Cells show implementation status; trailing notes flag whether implementations agree.

| Path family | monolith | user-svc | notification-svc | project-svc | Agree? |
|---|---|---|---|---|---|
| `POST /api/v3/users/login` | ✓ `users/routes.py:88` | ✓ `users/routes.py:94` | — | — | **Drift** — user-svc has Doc-46 admin-tier exclusion in list, Doc-44 caller-vs-target gate, Doc-41 scoped roles. Monolith is canonical fallback but lags. Sibling is target. |
| `POST /api/v3/users/refresh` | ✓ `:68` | ✓ `:74` | — | — | Same shape; proxied when flag on |
| `POST /api/v3/users/introspect` | ✓ `:48` | ✓ `:54` | — | — | |
| `POST /api/v3/users/login/{send,verify}-otp` | ✓ `:111,:128` | ✓ `:117,:134` | — | — | |
| `POST /api/v3/users/{forgot,reset}-password` | ✓ `:144,:159` | ✓ `:150,:165` | — | — | |
| `POST /api/v3/users/logout` | ✓ `:177` | ✓ `:183` | — | — | |
| `GET /api/v3/users/me`, `GET /api/v3/users/me/permissions` | ✓ `:191, :428` | ✓ `:197, :568` | — | — | |
| `POST /api/v3/users/create` | ✓ `:210` | ✓ `:216` | — | — | user-svc adds Doc-44 caller-vs-target gate, orgRole + project_assignments handling. |
| `GET /api/v3/users` (list) | ✓ `:229` | ✓ `:268` | — | — | user-svc has Doc-46 vendor auto-filter + admin-tier NOT-EXISTS exclusion. Monolith lacks these. **Choose user-svc impl.** |
| `GET /api/v3/users/{id}`, `PATCH`, `DELETE`, `POST /restore` | ✓ | ✓ | — | — | |
| `PATCH /api/v3/users/{id}/password` | ✓ `:317` | ✓ `:424` | — | — | |
| `GET /api/v3/users/{id}/permissions`, `POST/DELETE /…/{code}` | ✓ | ✓ | — | — | |
| `GET /api/v3/users/{id}/roles`, `POST /…/{role_id}`, `DELETE` | ✓ `:531,:554,:585` | ✓ `:710,:752,:824` | — | — | **Both DEPRECATED** in both services (stamped via `_stamp`). Successor is `/role-assignments`. |
| `/api/v3/master/roles/*` (consolidated CRUD, 9 endpoints) | ✓ `master_data/routes.py:684-811` | ✓ `master_data/routes.py:83-207` | — | — | Both proxy/delegate to legacy `/api/v3/roles/*` handlers internally. Owner → **user-svc** (RBAC domain). |
| `/api/v3/master/permissions/*` (6 endpoints) | ✓ `master_data/routes.py:831-949` | ✓ `master_data/routes.py:227-332` | — | — | Owner → **user-svc**. |
| `/api/v3/master/notification_templates/*` (6 endpoints) | ✓ `master_data/routes.py:996-1208` | — | ✓ `master_data_routes.py:83-261` | — | Owner → **notification-svc** (already authoritative). Monolith implementation is fallback-only. |
| `/api/v3/master/divisions/*` (5 endpoints) | ✓ `master_data/routes.py:193-318` | — | — | ✓ `master_data/routes.py:160-289` | Owner → **masters-svc** per Decision 6. Two implementations agree on shape. |
| `/api/v3/master/project_status_transitions/*` (5) | ✓ `:341-429` | — | — | ✓ `:312-400` | Owner → **masters-svc**. |
| `/api/v3/master/resource_types/*` (5) | ✓ `:451-525` | — | — | ✓ `:422-496` | Owner → **masters-svc**. |
| `/api/v3/master/vendors/*` (7) | ✓ `:565-662` | — | — | ✓ `:536-633` | Both delegate to legacy `/api/v3/vendors/*`. Owner → **masters-svc**. |
| `/api/v3/master/project_categories/*` (6) | ✓ `:1443-1556` | — | — | ✓ `:846-944` | Owner → **masters-svc**. |
| `/api/v3/master/activity_types/*` (6) | ✓ `:1558-1654` | — | — | ✓ `:961-1057` | Owner → **masters-svc**. |
| `/api/v3/master/milestone_statuses/*` (6) | ✓ `:1671-1769` | — | — | ✓ `:1074-1172` | Owner → **masters-svc**. |
| `/api/v3/master/activity_statuses/*` (6) | ✓ `:1786-1884` | — | — | ✓ `:1189-1287` | Owner → **masters-svc**. |
| `/api/v3/master/priorities/*` (6) | ✓ `:1925-2049` | — | — | ✓ `:1328-1452` | Owner → **masters-svc**. |
| `/api/v3/vendors/*` (7, LEGACY) | ✓ `vendors/routes.py:242-740` | — | — | ✓ `vendors/routes.py:242-715` | **Both DEPRECATED.** Delete in refactor; FE never calls (uses `/master/vendors/*`). |
| `/api/v3/resource_types/*` (2, LEGACY) | ✓ `resource_types/routes.py:54,74` | — | — | ✓ `resource_types/routes.py:54,74` | DEPRECATED. Delete. |
| `/api/v3/divisions` (LEGACY) | ✓ `catalogs/routes.py:56` | — | — | ✓ `catalogs/routes.py:56` | DEPRECATED. Delete in refactor. FE DOES call it (`ProjectDetailsPage.jsx:253`) — **FE migration needed**. |
| `/api/v3/project_status_transitions` (LEGACY) | ✓ `:124` | — | — | ✓ `:124` | DEPRECATED. Delete. |
| `/api/v3/priorities` (kept) | ✓ `:171` | — | — | ✓ `:171` | NOT deprecated. FE picker uses this. Decide: keep separate or unify with `/master/priorities`? (§7 Q.) |
| `/api/v3/roles/*` (9, LEGACY) | ✓ `roles/routes.py:46-336` | ✓ `roles/routes.py:49-336` | — | — | DEPRECATED. Delete (successor: `/master/roles/*`). |
| `/api/v3/permissions/*` (5, LEGACY) | ✓ `permissions/routes.py:60-181` | ✓ `permissions/routes.py:60-181` | — | — | DEPRECATED. Delete. |
| `POST /api/v3/users/{id}/role-assignments`, `GET`, `DELETE` | — | ✓ `role_assignments/routes.py:68-149` | — | — | **CANONICAL** — successor to `POST /users/{id}/roles/{role_id}`. |
| `GET/POST/DELETE /api/v3/projects/{uuid}/role-assignments` | ✓ `projects/routes.py:343, 1146, 1163` (writes proxy to user-svc) | ✓ `role_assignments/routes.py:199, 253, 282` | — | — | Monolith list is native; monolith writes forward via `proxy_or_503`. Owner → **user-svc** (RBAC domain). |
| `GET /api/v3/projects/{uuid}/assignable-users` | ✓ `projects/routes.py:404` | — | — | ✓ `projects/routes.py:341` | Implementations diverge: project-svc joins on user-svc tables via shared schema. Owner → **project-svc** (project-scoped read). |
| `GET /api/v3/users/{id}/projects`, `GET /api/v3/vendors/{id}/projects`, `GET /api/v3/vendors/{id}/users` | ✓ (vendors→users forwards to user-svc) | ✓ `role_assignments/routes.py:333-525` | — | ✓ `vendors/routes.py:715` (project-svc has `vendors/{id}/projects`) | Owner per resource intent: `users/{id}/projects` → user-svc; `vendors/{id}/projects` → masters-svc or project-svc; `vendors/{id}/users` → user-svc. See §3. |
| `GET /api/v3/role-grants/{role_name}` | — | ✓ `role_assignments/routes.py:591` | — | — | Single owner. user-svc. |
| Project domain CRUD: `/api/v3/projects/*`, `/api/v3/milestones/*`, `/api/v3/activities/*`, `/api/v3/tasks/*`, `/api/v3/subtasks/*`, `/api/v3/comments/*`, `/api/v3/attachments/*`, `/api/v3/dashboard/*`, `/api/v3/projects/{uuid}/tree` | ✓ (all) | — | — | ✓ (all, mostly same shape) | Owner → **project-svc**. Both implementations exist; project-svc is the target. |
| `POST /api/v1/notifications/{email,sms,otp}/{send,verify}` | — | — | ✓ `email_routes.py:21`, `sms_routes.py:21`, `otp_routes.py:26,39` | — | Single owner. notification-svc. |
| `POST /api/v1/notifications/dispatch` | — | — | ✓ `dispatch_routes.py:38` | — | Single owner. notification-svc. |
| `POST /api/v1/notifications/cron/daily-digest` | — | — | ✓ `cron_routes.py:85` | — | Single owner. notification-svc. |
| `GET /api/v3/projects/{uuid}/audit-logs`, `attachments`, `discussion-feed` | ✓ `projects/routes.py:547, 788, 961` | — | — | ✓ `projects/routes.py:480, 721, 891` | Both impl. Owner → project-svc. |
| `POST /api/v3/projects/{uuid}/memberships/create` etc. (4 routes) | ✓ `project_members/routes.py:46-104` | — | — | — | **LEGACY — superseded by `/role-assignments`**. Already removed in user-svc/project-svc. Disposition: `delete-deprecated`. |
| `/api/v3/work_packages/*`, `/api/v3/work_package_types/*` (LEGACY) | ✓ `work_packages/routes.py`, `work_package_types/routes.py` | — | — | — | **LEGACY-EXCLUDE** (user-flagged). |
| `/api/v3/{projects/{uuid}/meetings,meetings}/*` (LEGACY) | ✓ `meetings/routes.py:46-295` | — | — | — | **LEGACY-EXCLUDE**. FK chain: `meeting_agenda_items.work_package_id` → must drop with work_packages. |

**Summary of the "monolith as gateway and fallback" pattern:** every user/auth endpoint exists in BOTH monolith and user-svc; every masters endpoint exists in BOTH monolith and project-svc (and notification-svc for templates). The flags `USER_SERVICE_PROXY_ENABLED` / `NOTIFICATION_SERVICE_PROXY_ENABLED` decide which implementation answers a given request. The refactor removes this duality — each path has exactly one implementation in exactly one service.

---

## §3 Endpoint reconciliation table

Every endpoint with disposition. Columns:
- **CURRENT PATH** — as seen by the FE today
- **DISP** — `keep` | `move` | `merge-into` | `delete-deprecated` | `legacy-exclude` | `rename`
- **NEW PATH** — target under `/<service>/...` (per Decision 2; see §4 for full migration table)
- **OWNER** — target service (`user` / `project` / `notification` / `masters`)
- **FE?** — does the FE's `endpoint.js` currently use this path? (Y / N / `[UNVERIFIED]`)
- **REASON** — one-line justification

> Convention: NEW PATH uses the standardized scheme `/<service>/<resource>/<action>` and drops `/api/v3`. Per Decision 5, response shape changes are kept minimal but envelopes/errors may be normalized per service.

### 3.1 User domain → user-svc

| METHOD | CURRENT PATH | DISP | NEW PATH | OWNER | FE? | REASON |
|---|---|---|---|---|---|---|
| POST | /api/v3/users/login | move | /user/users/login | user | Y | canonical login |
| POST | /api/v3/users/logout | move | /user/users/logout | user | Y | |
| POST | /api/v3/users/refresh | move | /user/users/refresh | user | Y | |
| POST | /api/v3/users/introspect | move | /user/users/introspect | user | Y | |
| GET | /api/v3/users/me | move | /user/users/me | user | Y | |
| POST | /api/v3/users/login/send-otp | move | /user/users/login/send-otp | user | Y | |
| POST | /api/v3/users/login/verify-otp | move | /user/users/login/verify-otp | user | Y | |
| POST | /api/v3/users/forgot-password | move | /user/users/forgot-password | user | Y | |
| POST | /api/v3/users/reset-password | move | /user/users/reset-password | user | Y | |
| POST | /api/v3/users/create | move | /user/users/create | user | Y | use user-svc impl (Doc-44 gate) |
| GET | /api/v3/users | move | /user/users | user | Y | use user-svc impl (Doc-46 vendor auto-filter + admin-tier exclusion) |
| GET | /api/v3/users/check-login | move | /user/users/check-login | user | [UNVERIFIED] | user-svc only |
| GET | /api/v3/users/{id} | move | /user/users/{id} | user | Y | |
| PATCH | /api/v3/users/{id} | move | /user/users/{id} | user | Y | |
| PATCH | /api/v3/users/{id}/password | move | /user/users/{id}/password | user | Y | |
| DELETE | /api/v3/users/{id} | move | /user/users/{id} | user | Y | |
| POST | /api/v3/users/{id}/restore | move | /user/users/{id}/restore | user | [UNVERIFIED] | |
| GET | /api/v3/users/me/permissions | move | /user/users/me/permissions | user | [UNVERIFIED] | |
| GET | /api/v3/users/{id}/permissions | move | /user/users/{id}/permissions | user | [UNVERIFIED] | |
| POST | /api/v3/users/{id}/permissions/{code} | move | /user/users/{id}/permissions/{code} | user | [UNVERIFIED] | |
| DELETE | /api/v3/users/{id}/permissions/{code} | move | /user/users/{id}/permissions/{code} | user | [UNVERIFIED] | |
| GET | /api/v3/users/{id}/roles | **delete-deprecated** | — | — | N | legacy global-role list; successor: `/user/users/{id}/role-assignments` |
| POST | /api/v3/users/{id}/roles/{role_id} | **delete-deprecated** | — | — | N | **legacy assign-role**; successor below |
| DELETE | /api/v3/users/{id}/roles/{role_id} | **delete-deprecated** | — | — | N | legacy revoke-role |
| GET | /api/v3/users/{id}/role-assignments | move | /user/users/{id}/role-assignments | user | [UNVERIFIED] | canonical Doc-41 scoped RBAC |
| POST | /api/v3/users/{id}/role-assignments | move | /user/users/{id}/role-assignments | user | [UNVERIFIED] | canonical scoped assign |
| DELETE | /api/v3/users/{id}/role-assignments/{aid} | move | /user/users/{id}/role-assignments/{aid} | user | [UNVERIFIED] | |
| GET | /api/v3/users/{id}/projects | move | /user/users/{id}/projects | user | [UNVERIFIED] | user-centric view |
| GET | /api/v3/role-grants/{role_name} | move | /user/role-grants/{role_name} | user | [UNVERIFIED] | grantable-roles matrix |
| GET | /api/v3/master/roles | merge-into `/user/roles/*` | /user/roles | user | Y? (`endpoint.js:63` declared, no observed caller) | RBAC domain owns roles |
| GET | /api/v3/master/roles/{id} | merge-into | /user/roles/{id} | user | [UNVERIFIED] | |
| POST | /api/v3/master/roles/create | merge-into | /user/roles/create | user | [UNVERIFIED] | |
| PATCH | /api/v3/master/roles/{id} | merge-into | /user/roles/{id} | user | [UNVERIFIED] | |
| DELETE | /api/v3/master/roles/{id} | merge-into | /user/roles/{id} | user | [UNVERIFIED] | |
| GET | /api/v3/master/roles/{id}/permissions | merge-into | /user/roles/{id}/permissions | user | [UNVERIFIED] | |
| PUT | /api/v3/master/roles/{id}/permissions | merge-into | /user/roles/{id}/permissions | user | [UNVERIFIED] | |
| POST | /api/v3/master/roles/{id}/permissions/{code} | merge-into | /user/roles/{id}/permissions/{code} | user | [UNVERIFIED] | |
| DELETE | /api/v3/master/roles/{id}/permissions/{code} | merge-into | /user/roles/{id}/permissions/{code} | user | [UNVERIFIED] | |
| GET | /api/v3/master/permissions | merge-into `/user/permissions/*` | /user/permissions | user | [UNVERIFIED] | |
| GET | /api/v3/master/permissions/by-module | merge-into | /user/permissions/by-module | user | [UNVERIFIED] | |
| GET | /api/v3/master/permissions/{code} | merge-into | /user/permissions/{code} | user | [UNVERIFIED] | |
| POST | /api/v3/master/permissions/create | merge-into | /user/permissions/create | user | [UNVERIFIED] | |
| PATCH | /api/v3/master/permissions/{code} | merge-into | /user/permissions/{code} | user | [UNVERIFIED] | |
| DELETE | /api/v3/master/permissions/{code} | merge-into | /user/permissions/{code} | user | [UNVERIFIED] | |
| /api/v3/roles/* (9 routes) | **delete-deprecated** | — | — | N | legacy unscoped (already deprecated, FE doesn't use) |
| /api/v3/permissions/* (5 routes) | **delete-deprecated** | — | — | N | legacy (already deprecated, FE doesn't use) |
| GET | /api/v3/vendors/{id}/users | move (rename) | /user/vendors/{id}/users | user | [UNVERIFIED] | user-list-by-vendor — user domain query |

### 3.2 Project domain → project-svc

| METHOD | CURRENT PATH | DISP | NEW PATH | OWNER | FE? | REASON |
|---|---|---|---|---|---|---|
| POST | /api/v3/projects/create | move | /project/projects/create | project | Y | |
| PUT | /api/v3/projects/{uuid} | move | /project/projects/{uuid} | project | [UNVERIFIED] | idempotent upsert |
| GET | /api/v3/projects | move | /project/projects | project | Y | |
| GET | /api/v3/projects/all | move | /project/projects/all | project | [UNVERIFIED] | admin view incl. deleted |
| GET | /api/v3/projects/{uuid} | move | /project/projects/{uuid} | project | Y | |
| PATCH | /api/v3/projects/{uuid} | move | /project/projects/{uuid} | project | Y | |
| DELETE | /api/v3/projects/{uuid} | move | /project/projects/{uuid} | project | Y | |
| POST | /api/v3/projects/{uuid}/save | move | /project/projects/{uuid}/save | project | Y | wizard step 1 |
| POST | /api/v3/projects/{uuid}/publish | move | /project/projects/{uuid}/publish | project | Y | |
| POST | /api/v3/projects/{uuid}/close | move | /project/projects/{uuid}/close | project | Y | |
| GET | /api/v3/projects/{uuid}/tree | move | /project/projects/{uuid}/tree | project | Y | |
| GET | /api/v3/projects/{uuid}/assignable-users | move | /project/projects/{uuid}/assignable-users | project | [UNVERIFIED] | project-scoped picker (joins user-svc tables cross-schema) |
| GET | /api/v3/projects/{uuid}/role-assignments | **move to user** | /user/projects/{uuid}/role-assignments | user | [UNVERIFIED] | RBAC domain (currently lives in monolith projects/) |
| POST | /api/v3/projects/{uuid}/role-assignments | **move to user** | /user/projects/{uuid}/role-assignments | user | [UNVERIFIED] | RBAC domain |
| DELETE | /api/v3/projects/{uuid}/role-assignments/{aid} | **move to user** | /user/projects/{uuid}/role-assignments/{aid} | user | [UNVERIFIED] | RBAC domain |
| GET | /api/v3/projects/{uuid}/audit-logs | move | /project/projects/{uuid}/audit-logs | project | [UNVERIFIED] | Doc-47, project-owned table |
| GET | /api/v3/projects/{uuid}/attachments | move | /project/projects/{uuid}/attachments | project | [UNVERIFIED] | reads comments table |
| POST | /api/v3/projects/{uuid}/attachments | move | /project/projects/{uuid}/attachments | project | [UNVERIFIED] | multipart |
| GET | /api/v3/projects/{uuid}/discussion-feed | move | /project/projects/{uuid}/discussion-feed | project | [UNVERIFIED] | comments across M/A/T/S |
| POST | /api/v3/projects/{uuid}/milestones/create | move | /project/projects/{uuid}/milestones/create | project | Y | |
| GET | /api/v3/projects/{uuid}/milestones | move | /project/projects/{uuid}/milestones | project | Y | |
| GET | /api/v3/milestones/{id} | move | /project/milestones/{id} | project | [UNVERIFIED] | |
| PATCH | /api/v3/milestones/{id} | move | /project/milestones/{id} | project | Y | |
| DELETE | /api/v3/milestones/{id} | move | /project/milestones/{id} | project | Y | |
| POST | /api/v3/milestones/{id}/restore | move | /project/milestones/{id}/restore | project | [UNVERIFIED] | |
| POST | /api/v3/milestones/{id}/activities/create | move | /project/milestones/{id}/activities/create | project | Y | |
| GET | /api/v3/milestones/{id}/activities | move | /project/milestones/{id}/activities | project | Y | |
| GET | /api/v3/activities/{id} | move | /project/activities/{id} | project | Y | |
| PATCH | /api/v3/activities/{id} | move | /project/activities/{id} | project | Y | |
| DELETE | /api/v3/activities/{id} | move | /project/activities/{id} | project | Y | |
| POST | /api/v3/activities/{id}/restore | move | /project/activities/{id}/restore | project | [UNVERIFIED] | |
| POST | /api/v3/activities/{id}/tasks/create | move | /project/activities/{id}/tasks/create | project | Y | |
| GET | /api/v3/activities/{id}/tasks | move | /project/activities/{id}/tasks | project | Y | |
| GET | /api/v3/tasks/{id} | move | /project/tasks/{id} | project | Y | |
| PATCH | /api/v3/tasks/{id} | move | /project/tasks/{id} | project | Y | |
| DELETE | /api/v3/tasks/{id} | move | /project/tasks/{id} | project | Y | |
| POST | /api/v3/tasks/{id}/restore | move | /project/tasks/{id}/restore | project | [UNVERIFIED] | |
| POST | /api/v3/tasks/{id}/subtasks/create | move | /project/tasks/{id}/subtasks/create | project | Y | |
| GET | /api/v3/tasks/{id}/subtasks | move | /project/tasks/{id}/subtasks | project | Y | |
| POST | /api/v3/subtasks/{parent_id}/subtasks/create | move | /project/subtasks/{parent_id}/subtasks/create | project | Y | nested subtask |
| GET | /api/v3/subtasks/{id} | move | /project/subtasks/{id} | project | Y | |
| GET | /api/v3/subtasks/{id}/subtasks | move | /project/subtasks/{id}/subtasks | project | Y | |
| PATCH | /api/v3/subtasks/{id} | move | /project/subtasks/{id} | project | Y | |
| DELETE | /api/v3/subtasks/{id} | move | /project/subtasks/{id} | project | Y | |
| POST | /api/v3/subtasks/{id}/restore | move | /project/subtasks/{id}/restore | project | [UNVERIFIED] | |
| POST | /api/v3/{milestones\|activities\|tasks\|subtasks}/{id}/comments | move | /project/{kind}/{id}/comments | project | Y (4 paths) | factory-registered, 4 target_kinds |
| GET | /api/v3/{milestones\|activities\|tasks\|subtasks}/{id}/comments | move | /project/{kind}/{id}/comments | project | Y (4 paths) | |
| DELETE | /api/v3/comments/{id} | move | /project/comments/{id} | project | [UNVERIFIED] | author/admin gate |
| POST | /api/v3/{milestones\|activities\|tasks\|subtasks}/{id}/attachments | move | /project/{kind}/{id}/attachments | project | Y? declared, no observed caller for 4 paths | doc-35 unified onto comments JSON |
| GET | /api/v3/{milestones\|activities\|tasks\|subtasks}/{id}/attachments | move | /project/{kind}/{id}/attachments | project | Y? declared | |
| DELETE | /api/v3/attachments/{id} | move | /project/attachments/{id} | project | [UNVERIFIED] | doc-35 alias |
| GET | /api/v3/dashboard/summary | move | /project/dashboard/summary | project | Y | admin-only |
| GET | /api/v3/dashboard/projects | move | /project/dashboard/projects | project | Y | |
| GET | /api/v3/dashboard/projects/{uuid} | move | /project/dashboard/projects/{uuid} | project | Y | |
| GET | /api/v3/dashboard/projects/{uuid}/items | move | /project/dashboard/projects/{uuid}/items | project | Y | |
| GET | /api/v3/dashboard/organisations | move | /project/dashboard/organisations | project | Y | |
| GET | /api/v3/dashboard/organisations/{vendor_id} | move | /project/dashboard/organisations/{vendor_id} | project | Y | |
| /api/v3/projects/{uuid}/memberships/* (4 routes) | **delete-deprecated** | — | — | N | superseded by role-assignments; table already migrated (Decision 1 — every meaningful API has a home, this one is functionally rehomed) |
| /api/v3/work_packages/* (6 routes) | **legacy-exclude** | — | — | N | user-flagged |
| /api/v3/work_package_types/* (5 routes) | **legacy-exclude** | — | — | N | user-flagged |
| /api/v3/{projects/{uuid}/meetings,meetings}/* (13 routes) | **legacy-exclude** | — | — | N | user-flagged; FK chain with work_packages |

### 3.3 Masters domain → masters-svc (new)

> Per Decision 6, masters-svc owns: divisions, vendors, resource_types, project_categories, activity_types, activity_statuses, milestone_statuses, project_status_transitions, priorities. Roles/permissions live in user-svc (RBAC), notification_templates in notification-svc.

| METHOD | CURRENT PATH | DISP | NEW PATH | OWNER | FE? | REASON |
|---|---|---|---|---|---|---|
| GET | /api/v3/master/divisions | move | /masters/divisions | masters | Y | |
| POST | /api/v3/master/divisions/create | move | /masters/divisions/create | masters | Y | |
| PATCH | /api/v3/master/divisions/{code} | move | /masters/divisions/{code} | masters | Y | |
| DELETE | /api/v3/master/divisions/{code} | move | /masters/divisions/{code} | masters | Y | |
| POST | /api/v3/master/divisions/{code}/restore | move | /masters/divisions/{code}/restore | masters | Y | |
| GET | /api/v3/divisions (legacy) | **delete-deprecated** | — | — | **Y** (`ProjectDetailsPage.jsx:253` calls this directly) | FE migration needed before delete |
| GET | /api/v3/master/project_status_transitions | move | /masters/project_status_transitions | masters | [UNVERIFIED] | |
| POST | /api/v3/master/project_status_transitions/create | move | /masters/project_status_transitions/create | masters | [UNVERIFIED] | |
| PATCH | /api/v3/master/project_status_transitions/{row_id} | move | /masters/project_status_transitions/{row_id} | masters | [UNVERIFIED] | |
| DELETE | /api/v3/master/project_status_transitions/{row_id} | move | /masters/project_status_transitions/{row_id} | masters | [UNVERIFIED] | |
| POST | /api/v3/master/project_status_transitions/{row_id}/restore | move | /masters/project_status_transitions/{row_id}/restore | masters | [UNVERIFIED] | |
| GET | /api/v3/project_status_transitions (legacy) | **delete-deprecated** | — | — | N | |
| GET | /api/v3/master/resource_types | move | /masters/resource_types | masters | [UNVERIFIED] | |
| POST | /api/v3/master/resource_types/create | move | /masters/resource_types/create | masters | [UNVERIFIED] | |
| PATCH | /api/v3/master/resource_types/{rt_id} | move | /masters/resource_types/{rt_id} | masters | [UNVERIFIED] | |
| DELETE | /api/v3/master/resource_types/{rt_id} | move | /masters/resource_types/{rt_id} | masters | [UNVERIFIED] | |
| POST | /api/v3/master/resource_types/{rt_id}/restore | move | /masters/resource_types/{rt_id}/restore | masters | [UNVERIFIED] | |
| GET | /api/v3/resource_types (legacy) | **delete-deprecated** | — | — | **Y** (`milestoneConfigApi.js:385`) | FE migration needed |
| POST | /api/v3/resource_types/create (legacy) | **delete-deprecated** | — | — | N | |
| GET | /api/v3/master/vendors | move | /masters/vendors | masters | Y | |
| GET | /api/v3/master/vendors/{vendor_id} | move | /masters/vendors/{vendor_id} | masters | Y | |
| POST | /api/v3/master/vendors/create | move | /masters/vendors/create | masters | Y | |
| PATCH | /api/v3/master/vendors/{vendor_id} | move | /masters/vendors/{vendor_id} | masters | Y | tier-scoped (admin/OA/PA) — preserve gate |
| DELETE | /api/v3/master/vendors/{vendor_id} | move | /masters/vendors/{vendor_id} | masters | Y | |
| POST | /api/v3/master/vendors/{vendor_id}/restore | move | /masters/vendors/{vendor_id}/restore | masters | [UNVERIFIED] | |
| GET | /api/v3/master/vendors/{vendor_id}/projects | move | /masters/vendors/{vendor_id}/projects | masters | [UNVERIFIED] | catalog→project listing |
| /api/v3/vendors/* (7 legacy routes) | **delete-deprecated** | — | — | N | FE never calls (uses `/master/vendors/*`); already deprecated |
| GET | /api/v3/master/project_categories | move | /masters/project_categories | masters | [UNVERIFIED] | |
| GET | /api/v3/master/project_categories/{code} | move | /masters/project_categories/{code} | masters | [UNVERIFIED] | |
| POST | /api/v3/master/project_categories/create | move | /masters/project_categories/create | masters | [UNVERIFIED] | |
| PATCH | /api/v3/master/project_categories/{code} | move | /masters/project_categories/{code} | masters | [UNVERIFIED] | |
| DELETE | /api/v3/master/project_categories/{code} | move | /masters/project_categories/{code} | masters | [UNVERIFIED] | |
| POST | /api/v3/master/project_categories/{code}/restore | move | /masters/project_categories/{code}/restore | masters | [UNVERIFIED] | |
| GET | /api/v3/master/activity_types | move | /masters/activity_types | masters | [UNVERIFIED] | |
| GET | /api/v3/master/activity_types/{code} | move | /masters/activity_types/{code} | masters | [UNVERIFIED] | |
| POST | /api/v3/master/activity_types/create | move | /masters/activity_types/create | masters | [UNVERIFIED] | |
| PATCH | /api/v3/master/activity_types/{code} | move | /masters/activity_types/{code} | masters | [UNVERIFIED] | |
| DELETE | /api/v3/master/activity_types/{code} | move | /masters/activity_types/{code} | masters | [UNVERIFIED] | |
| POST | /api/v3/master/activity_types/{code}/restore | move | /masters/activity_types/{code}/restore | masters | [UNVERIFIED] | |
| GET | /api/v3/master/milestone_statuses | move | /masters/milestone_statuses | masters | [UNVERIFIED] | |
| GET | /api/v3/master/milestone_statuses/{code} | move | /masters/milestone_statuses/{code} | masters | [UNVERIFIED] | |
| POST | /api/v3/master/milestone_statuses/create | move | /masters/milestone_statuses/create | masters | [UNVERIFIED] | |
| PATCH | /api/v3/master/milestone_statuses/{code} | move | /masters/milestone_statuses/{code} | masters | [UNVERIFIED] | |
| DELETE | /api/v3/master/milestone_statuses/{code} | move | /masters/milestone_statuses/{code} | masters | [UNVERIFIED] | |
| POST | /api/v3/master/milestone_statuses/{code}/restore | move | /masters/milestone_statuses/{code}/restore | masters | [UNVERIFIED] | |
| GET | /api/v3/master/activity_statuses | move | /masters/activity_statuses | masters | [UNVERIFIED] | |
| GET | /api/v3/master/activity_statuses/{code} | move | /masters/activity_statuses/{code} | masters | [UNVERIFIED] | |
| POST | /api/v3/master/activity_statuses/create | move | /masters/activity_statuses/create | masters | [UNVERIFIED] | |
| PATCH | /api/v3/master/activity_statuses/{code} | move | /masters/activity_statuses/{code} | masters | [UNVERIFIED] | |
| DELETE | /api/v3/master/activity_statuses/{code} | move | /masters/activity_statuses/{code} | masters | [UNVERIFIED] | |
| POST | /api/v3/master/activity_statuses/{code}/restore | move | /masters/activity_statuses/{code}/restore | masters | [UNVERIFIED] | |
| GET | /api/v3/master/priorities | move | /masters/priorities | masters | [UNVERIFIED] | |
| GET | /api/v3/master/priorities/{code} | move | /masters/priorities/{code} | masters | [UNVERIFIED] | |
| POST | /api/v3/master/priorities/create | move | /masters/priorities/create | masters | [UNVERIFIED] | |
| PATCH | /api/v3/master/priorities/{code} | move | /masters/priorities/{code} | masters | [UNVERIFIED] | |
| DELETE | /api/v3/master/priorities/{code} | move | /masters/priorities/{code} | masters | [UNVERIFIED] | |
| POST | /api/v3/master/priorities/{code}/restore | move | /masters/priorities/{code}/restore | masters | [UNVERIFIED] | |
| GET | /api/v3/priorities (kept, not deprecated) | **decision needed** | `/masters/priorities` (unify) OR `/masters/priorities/picker` (separate auth) | masters | **Y** (`milestoneConfigApi.js:411`) | Currently auth-only (lighter gate). `/master/priorities` requires MASTER_DATA_VIEW. See §7 Q. |

### 3.4 Notification domain → notification-svc

| METHOD | CURRENT PATH | DISP | NEW PATH | OWNER | FE? | REASON |
|---|---|---|---|---|---|---|
| POST | /api/v1/notifications/email/send | move (rename) | /notification/email/send | notification | N (server-to-server) | drop `/api/v1` prefix to align with new scheme |
| POST | /api/v1/notifications/sms/send | move (rename) | /notification/sms/send | notification | N | |
| POST | /api/v1/notifications/otp/send | move (rename) | /notification/otp/send | notification | N | |
| POST | /api/v1/notifications/otp/verify | move (rename) | /notification/otp/verify | notification | N | needs Redis-backed store (see §7) |
| POST | /api/v1/notifications/dispatch | move (rename) | /notification/dispatch | notification | N (called by user-svc) | Doc-38 single-call dispatch |
| POST | /api/v1/notifications/cron/daily-digest | move (rename) | /notification/cron/daily-digest | notification | N (DevOps cron) | `X-Cron-Secret` header preserved |
| GET | /api/v1/health | rename | /notification/health | notification | N | per Decision 8d |
| GET | /api/v3/master/notification_templates | move | /notification/templates | notification | [UNVERIFIED] (FE may use; not in observed map) | drop `/master/` since notification-svc is the owner; flatter path |
| GET | /api/v3/master/notification_templates/{id} | move | /notification/templates/{id} | notification | [UNVERIFIED] | |
| POST | /api/v3/master/notification_templates/create | move | /notification/templates/create | notification | [UNVERIFIED] | |
| PATCH | /api/v3/master/notification_templates/{id} | move | /notification/templates/{id} | notification | [UNVERIFIED] | |
| DELETE | /api/v3/master/notification_templates/{id} | move | /notification/templates/{id} | notification | [UNVERIFIED] | |
| POST | /api/v3/master/notification_templates/{id}/restore | move | /notification/templates/{id}/restore | notification | [UNVERIFIED] | |

> Note: dropping `/master/` for notification_templates breaks consistency with the rest of `/masters/*` for catalogs. See §7 Q for the unified-vs-per-service-prefix decision.

### 3.5 The "assign-roles / assignable-users / users" triplet (user-called-out)

The user originally flagged `assign-roles` vs the RBAC-filtered `users` list as a duplicate-intent pair. The audit found it's actually a **triplet** of overlapping endpoints with different intents and different filters:

| # | CURRENT PATH | INTENT | DATA SHAPE | RBAC | OWNER |
|---|---|---|---|---|---|
| 1 | `GET /api/v3/users` (RBAC-filtered list) | Admin-style user directory | `Collection<User>` HAL — id, login, email, fullName, status, vendor_id, vendor_name, division, division_other, phone_number, two_factor_enabled, deleted_at, user_code, projects[] | `USERS_READ_ALL` + non-admin caller auto-filtered to caller's vendor_id + admin-tier excluded via NOT-EXISTS subqueries | **user-svc** |
| 2 | `GET /api/v3/projects/{uuid}/assignable-users` (project-scoped picker) | "Who can I assign to this project?" | Subset filtered by project's owning vendor membership | `PROJECT_MEMBERS_READ` | **project-svc** (project-scoped read on user-svc tables via shared schema) |
| 3a | `POST /api/v3/users/{user_id}/roles/{role_id}` (LEGACY assign-role) | Grant role globally | Returns role list with Deprecation header | `RBAC_ASSIGN` | **DELETE — deprecated** |
| 3b | `POST /api/v3/users/{user_id}/role-assignments` (canonical scoped) | Grant role with optional org/project scope | Returns single assignment or batch `{items, total}` | `RBAC_ASSIGN` | **user-svc** (canonical Doc-41) |
| 3c | `POST /api/v3/projects/{uuid}/role-assignments` | Grant role within a project scope (project-scoped variant of 3b) | Same as 3b | `RBAC_ASSIGN` (currently forwarded by monolith to user-svc) | **user-svc** (move from monolith projects/) |

**Resolution:**
- `(1)` and `(2)` are NOT duplicates — they have different RBAC gates, different filters, different consumers. Both kept. The naming is consistent with intent.
- `(3a)` is genuinely deprecated — delete in refactor. `(3b)` and `(3c)` are kept as canonical, both owned by user-svc.
- The user's mental model "assign-roles vs users" maps to `(3a/3b)` vs `(1)`. After this refactor, the only `assign-role` endpoint is `(3b)` and its project-scoped twin `(3c)`. The `(1)` user list remains a distinct read endpoint.

**[UNVERIFIED]:** Whether the FE actually USES `(1)` and `(2)` is partly unconfirmed — `users.list` is in `endpoint.js` (`users.list = '/api/v3/users'`) and `vendors.js` calls `/api/v3/vendors`, but the specific `assignable-users` endpoint isn't in the inspected files. Likely wired from a Component. Worth a `components/` grep before deletion of any of them.

---

## §4 URL-prefix migration table

Comprehensive OLD → NEW. Same data as §3 but indexed by the FE's perspective.

| OLD PATH (FE sees today) | NEW PATH (FE sees after refactor) | OWNING SERVICE | FE CONSUMER? | BREAKING? |
|---|---|---|---|---|
| `/api/v3/users/login` | `/user/users/login` | user-svc | Y (`auth.js:46`) | Y — path change |
| `/api/v3/users/logout` | `/user/users/logout` | user-svc | Y (`auth.js:107`) | Y |
| `/api/v3/users/refresh` | `/user/users/refresh` | user-svc | Y (`client.js:163`, `endpoint.js:17`) | Y + dedupe `client.js:10` literal |
| `/api/v3/users/introspect` | `/user/users/introspect` | user-svc | Y (`auth.js:102`) | Y |
| `/api/v3/users/me` | `/user/users/me` | user-svc | Y (`auth.js:98`) | Y |
| `/api/v3/users/login/send-otp` | `/user/users/login/send-otp` | user-svc | Y (`auth.js:66`) | Y |
| `/api/v3/users/login/verify-otp` | `/user/users/login/verify-otp` | user-svc | Y (`auth.js:74`) | Y |
| `/api/v3/users/forgot-password` | `/user/users/forgot-password` | user-svc | Y (`auth.js:83`) | Y |
| `/api/v3/users/reset-password` | `/user/users/reset-password` | user-svc | Y (`auth.js:91`) | Y |
| `/api/v3/users` (list) | `/user/users` | user-svc | Y (`users.js:61`) | Y |
| `/api/v3/users/{id}` (GET/PATCH/DELETE) | `/user/users/{id}` | user-svc | Y | Y |
| `/api/v3/users/create` | `/user/users/create` | user-svc | Y (`users.js:71`) | Y |
| `/api/v3/users/{id}/password` | `/user/users/{id}/password` | user-svc | Y (`users.js:110`) | Y |
| `/api/v3/vendors` | `/masters/vendors` | masters-svc | Y (`vendors.js:109` — uses **legacy** vendors route, not master) | Y + **FE switch from legacy to master prefix** |
| `/api/v3/vendors/{id}` | `/masters/vendors/{id}` | masters-svc | Y (`vendors.js:114`) | Y |
| `/api/v3/vendors/create` | `/masters/vendors/create` | masters-svc | Y (`vendors.js:127`) | Y |
| `/api/v3/vendors/{id}` (PATCH) | `/masters/vendors/{id}` | masters-svc | Y (`vendors.js:180`) | Y |
| `/api/v3/vendors/{id}` (DELETE) | `/masters/vendors/{id}` | masters-svc | Y (`vendors.js:185`) | Y |
| `/api/v3/divisions` (legacy GET) | `/masters/divisions` | masters-svc | **Y** (`ProjectDetailsPage.jsx:253` — used as UI dropdown) | **Y — direct breaking change; FE must update** |
| `/api/v3/master/divisions` (+ CRUD/restore) | `/masters/divisions` (...) | masters-svc | Y (`divisions.js:35-61`) | Y |
| `/api/v3/master/roles` | `/user/roles` | user-svc | Declared in `endpoint.js:63`, no observed caller | Y (if used) |
| `/api/v3/resource_types` (legacy GET) | `/masters/resource_types` | masters-svc | **Y** (`milestoneConfigApi.js:385`) | **Y — FE must switch from legacy to master prefix** |
| `/api/v3/priorities` (kept) | **Decision needed**: `/masters/priorities` (unify) or `/masters/priorities/picker` | masters-svc | Y (`milestoneConfigApi.js:411`) | Y |
| `/api/v3/projects` | `/project/projects` | project-svc | Y (`projects.js:17`) | Y |
| `/api/v3/projects/{uuid}` | `/project/projects/{uuid}` | project-svc | Y | Y |
| `/api/v3/projects/{uuid}/tree` | `/project/projects/{uuid}/tree` | project-svc | Y (`projects.js:29`) | Y |
| `/api/v3/projects/create` | `/project/projects/create` | project-svc | Y (`AddProjectPage.jsx:310`) | Y |
| `/api/v3/projects/{uuid}/save` | `/project/projects/{uuid}/save` | project-svc | Y (`projects.js:44`) | Y |
| `/api/v3/projects/{uuid}/publish` | `/project/projects/{uuid}/publish` | project-svc | Y | Y |
| `/api/v3/projects/{uuid}/close` | `/project/projects/{uuid}/close` | project-svc | Y | Y |
| `/api/v3/projects/{uuid}/milestones` | `/project/projects/{uuid}/milestones` | project-svc | Y | Y |
| `/api/v3/projects/{uuid}/milestones/create` | `/project/projects/{uuid}/milestones/create` | project-svc | Y | Y |
| `/api/v3/milestones/{id}` (GET/PATCH/DELETE) | `/project/milestones/{id}` | project-svc | Y | Y |
| `/api/v3/milestones/{id}/activities` | `/project/milestones/{id}/activities` | project-svc | Y | Y |
| `/api/v3/milestones/{id}/activities/create` | `/project/milestones/{id}/activities/create` | project-svc | Y | Y |
| `/api/v3/milestones/{id}/comments` | `/project/milestones/{id}/comments` | project-svc | Y | Y |
| `/api/v3/milestones/{id}/attachments` | `/project/milestones/{id}/attachments` | project-svc | Declared in `endpoint.js:84`, no observed caller | Y (if used) |
| `/api/v3/activities/{id}` (GET/PATCH/DELETE) | `/project/activities/{id}` | project-svc | Y | Y |
| `/api/v3/activities/{id}/tasks` | `/project/activities/{id}/tasks` | project-svc | Y | Y |
| `/api/v3/activities/{id}/tasks/create` | `/project/activities/{id}/tasks/create` | project-svc | Y | Y |
| `/api/v3/activities/{id}/comments` | `/project/activities/{id}/comments` | project-svc | Y | Y |
| `/api/v3/activities/{id}/attachments` | `/project/activities/{id}/attachments` | project-svc | Declared, no caller | Y (if used) |
| `/api/v3/tasks/{id}` (GET/PATCH/DELETE) | `/project/tasks/{id}` | project-svc | Y | Y |
| `/api/v3/tasks/{id}/subtasks` | `/project/tasks/{id}/subtasks` | project-svc | Y | Y |
| `/api/v3/tasks/{id}/subtasks/create` | `/project/tasks/{id}/subtasks/create` | project-svc | Y | Y |
| `/api/v3/tasks/{id}/comments` | `/project/tasks/{id}/comments` | project-svc | Y | Y |
| `/api/v3/tasks/{id}/attachments` | `/project/tasks/{id}/attachments` | project-svc | Declared, no caller | Y (if used) |
| `/api/v3/subtasks/{id}` (GET/PATCH/DELETE) | `/project/subtasks/{id}` | project-svc | Y | Y |
| `/api/v3/subtasks/{id}/subtasks` | `/project/subtasks/{id}/subtasks` | project-svc | Y | Y |
| `/api/v3/subtasks/{id}/subtasks/create` | `/project/subtasks/{id}/subtasks/create` | project-svc | Y | Y |
| `/api/v3/subtasks/{id}/comments` | `/project/subtasks/{id}/comments` | project-svc | Y | Y |
| `/api/v3/subtasks/{id}/attachments` | `/project/subtasks/{id}/attachments` | project-svc | Declared, no caller | Y (if used) |
| `/api/v3/dashboard/summary` | `/project/dashboard/summary` | project-svc | Y | Y |
| `/api/v3/dashboard/projects` | `/project/dashboard/projects` | project-svc | Y | Y |
| `/api/v3/dashboard/projects/{uuid}` | `/project/dashboard/projects/{uuid}` | project-svc | Y | Y |
| `/api/v3/dashboard/projects/{uuid}/items` | `/project/dashboard/projects/{uuid}/items` | project-svc | Y | Y |
| `/api/v3/dashboard/organisations` | `/project/dashboard/organisations` | project-svc | Y | Y |
| `/api/v3/dashboard/organisations/{vendorId}` | `/project/dashboard/organisations/{vendorId}` | project-svc | Y | Y |
| _every_ `/api/v1/notifications/*` | `/notification/*` (drop `/api/v1` and the `notifications/` middle segment) | notification-svc | N (server-to-server only) | Y for monolith + user-svc → these go away |

**Endpoints declared in FE map but with no observed caller (5):** subject to a `components/` grep before deletion. If still unused, the corresponding BE routes are candidates for `delete-deprecated`:
- `endpoint.js:84` `milestones.attachments`
- `endpoint.js:98` `activities.attachments`
- `endpoint.js:108` `tasks.attachments`
- `endpoint.js:118` `subtasks.attachments`
- `endpoint.js:63` `roles.list`

**FE migration approach (per Decision 5a + decision 1):** Two alternatives, listed in `frontend.md` §6:
1. Edit `endpoint.js` only — ~64 lines, find-replace-style. The dedupe of `REFRESH_PATH` at `client.js:10` is a follow-up one-liner.
2. Gateway-based rewrite at nginx — zero FE code changes; nginx rewrites `/api/v3/users/*` → user-svc, etc.

PLAN.md will recommend (1) since the refactor's whole point is the new scheme; (2) is for risk-averse cutover.

---

## §5 Schema audit

Per-table disposition. Columns:
- **TABLE** — name
- **NEW OWNER** — service in the refactor's schema layout (`user.`, `project.`, `notification.`, `masters.`, or `legacy-exclude` for drop)
- **STATUS** — `keep` | `keep-cross-schema-read` | `drop` | `merge` | `rename` | `needs-migration`
- **CITATION** — model file:line (in monolith unless otherwise noted)
- **FLAGGED COLUMNS / NOTES**

### 5.1 User-svc-owned (target schema `user.`)

| TABLE | NEW OWNER | STATUS | CITATION | NOTES |
|---|---|---|---|---|
| users | user. | keep | `models/user.py:23` | UUID PK (Doc-26); deleted_at/deleted_by soft-delete; multiple drift columns (vendor_id, division, phone_number, org_role, refresh_token_jti). Schema is in monolith's alembic; not in user-svc's alembic. **Migration plan must own this table.** |
| roles | user. | keep | `role.py:21` | Integer PK auto; name unique; `permissions` JSON column DROPPED in Doc-21B but the initial user-svc migration still recreates it (drift). Confirm prod state. |
| permissions | user. | keep | `permission.py:25` | String(128) PK `code` (e.g. `"users:create"`). |
| role_permissions | user. | keep | `role_permission.py:14` | Composite PK. |
| user_roles | user. | keep | `user_role.py:14` | Composite PK. **Legacy global-scope; superseded by `user_role_assignments` for new writes but still queried** (project-svc admin-tier scan, monolith `projects/routes.py:490-507`). |
| user_permissions | user. | keep | `user_permission.py:18` | Composite PK. Direct grants. |
| user_role_assignments | user. | keep | `user_role_assignment.py:36` | Doc-41 scoped RBAC. **FKs reach `vendors.id` (org scope) and `projects.id` (project scope)** — cross-schema FK from `user.` to `masters.` and `project.`. Allowed within shared Postgres. Has `CHECK ck_ura_single_scope` + UNIQUE (user_id, role_id, organization_id, project_id). |
| revoked_tokens | user. | keep | `revoked_token.py:26` | jti-PK blacklist. **Read by all 3 backend services** (cross-schema read). |
| password_reset_tokens | user. | keep | `password_reset_token.py:32` | token_hash unique; single-use. |
| otp_codes | user. | keep | `otp_code.py:37` | ephemeral_token_hash; attempt_count; 2FA login flow. **Distinct from notification-svc's in-memory OTP store** (which dispatches the OTP code; user-svc records the issuance/verification). |
| notification_log | user. | keep | `notification_log.py:22` | User-svc's audit log of issued notifications. JSON `payload` column. **Notification templates moved out to notification-svc (Doc-38), but this log stays in user.** |

> Schema-ownership clean-up note: user-svc's repo declares 4 cross-domain models (`divisions`, `projects`, `vendors`, `project_vendors`) plus 1 orphan (`milestone_vendors`). In the refactor, those become **cross-schema FK targets**: user-svc imports the model classes to read from `masters.divisions / masters.vendors / project.projects / project.project_vendors` but does NOT own those tables. The `milestone_vendors` orphan is dropped (no usage). The 4 deliberate ones are kept as read-only declarations.

### 5.2 Project-svc-owned (target schema `project.`)

| TABLE | NEW OWNER | STATUS | CITATION (project-svc unless noted) | NOTES |
|---|---|---|---|---|
| projects | project. | keep | `models/project.py:23` | UUID PK; deleted_at/by soft-delete. Schema drift: monolith model adds `category_other_reason`, `actual_start_date`, etc. — project-svc's model lacks some. **Diff before porting.** |
| project_audit_logs | project. | keep | `project_audit_log.py:33` (project-svc) / `:14` (monolith) | Doc-47. Owned by project-svc per separate migration `b1d3e7a9c204`. |
| project_vendors | project. | keep | `project_vendor.py:18` (project-svc) / `:17` (monolith) | Composite PK M:N. project-svc adds `deleted_at` soft-delete; monolith model doesn't. **Drift — confirm prod has both columns.** |
| milestones | project. | keep | `milestone.py:24` (project-svc) / `:16` (monolith) | UUID PK; deleted_at/by; cascades on project delete via service code (not DB). |
| milestone_dependencies | project. | keep | `milestone_dependency.py:25` (project-svc) / `:24` (monolith) | Partial unique on (source,target) WHERE deleted_at IS NULL. |
| milestone_vendors | project. | keep | `milestone_vendor.py:15` (project-svc) / `:14` (monolith) | Composite PK. NOTE: user-svc's `milestone_vendors` ORPHAN is dropped; project-svc owns canonical. |
| activities | project. | keep | `activity.py:16` | doc-38 `type` nullable; Doc-39 `concerned_divisions` JSON. `vendor_id` FK to `masters.vendors` (cross-schema). |
| activity_dependencies | project. | keep | `activity_dependency.py:40` | |
| activity_resources | project. | keep | `activity_resource.py:16` | FK to `masters.resource_types` (cross-schema). |
| tasks | project. | keep | `task.py:18` (project-svc) / `:16` (monolith) | UUID PK. `assigned_to` FK to `user.users`. |
| task_dependencies | project. | keep | `task_dependency.py:26` (project-svc) / `:25` (monolith) | |
| task_resources | project. | keep | `task_resource.py:17` (project-svc) / `:16` (monolith) | |
| subtasks | project. | keep | `subtask.py:36` (project-svc) / `:30` (monolith) | Self-FK `parent_subtask_id` (Doc-24); `task_id` is ROOT task even for nested. |
| subtask_dependencies | project. | keep | `subtask_dependency.py:21` (project-svc) / `:20` (monolith) | |
| subtask_resources | project. | keep | `subtask_resource.py:17` (project-svc) / `:16` (monolith) | |
| comments | project. | keep | `comment.py:40` (both) | Doc-35 unified attachments onto JSON column; polymorphic `(target_kind, target_id)` — NO DB-level FK to target. |

> Cross-schema reads from project. → user. for auth (revoked_tokens, role_permissions/user_roles/user_permissions, user_role_assignments) — kept as read-only ORM declarations in project-svc, no writes. To masters. for vendors/resource_types/divisions/priorities — read-only FK targets.

### 5.3 Notification-svc-owned (target schema `notification.`)

| TABLE | NEW OWNER | STATUS | CITATION | NOTES |
|---|---|---|---|---|
| notification_templates | notification. | keep | `notification_template.py:23` (notification-svc) / `notification_template.py:49` (monolith) | Doc-38 moved ownership from user-svc. Single source of truth post-cutover. **Monolith still has the model + routes (proxied) — drop those.** |

> notification-svc reads from `user.` (RBAC tables, revoked_tokens, users) and `project.` (projects, milestones, activities, user_role_assignments, project_vendors) for the daily-digest cron. Raw SQL via `rbac_read_repository.py:32-43`. Refactor option: replace raw `text()` SQL with ORM declarations of read-only views OR keep raw SQL with a cross-schema integration test that fails CI on drift. See §7.

### 5.4 Masters-svc-owned (target schema `masters.`)

| TABLE | NEW OWNER | STATUS | CITATION (project-svc unless noted) | NOTES |
|---|---|---|---|---|
| divisions | masters. | keep | `division.py:42` (project-svc) / `:41` (monolith) | code unique; doc-36 made email/phone NOT NULL. |
| vendors | masters. | keep | `vendor.py:32` (project-svc) / `:31` (monolith) | UUID PK; vendor_code unique; name unique; soft-delete. **Reached by FKs from `user.users.vendor_id`, `user.user_role_assignments.organization_id`, `project.project_vendors.vendor_id`, `project.milestone_vendors.vendor_id`, `project.activities.vendor_id`.** Heavy cross-schema FK target. |
| project_categories | masters. | keep | `project_category.py:27` (project-svc) / `:26` (monolith) | Doc-37 catalog. |
| project_status_transitions | masters. | keep | `project_status_transition.py:44` (project-svc) / `:43` (monolith) | from_status NULL allowed (initial). |
| activity_types | masters. | keep | `activity_type.py:27` (project-svc) / `:26` (monolith) | Doc-37. |
| activity_statuses | masters. | keep | `activity_status.py:27` (project-svc) / `:26` (monolith) | Doc-37. |
| milestone_statuses | masters. | keep | `milestone_status.py:28` (project-svc) / `:27` (monolith) | Doc-37. |
| priorities | masters. | keep | `priority.py:21` (project-svc) / `:20` (monolith) | Doc-41. UUID PK; UPPER code normalized. **deleted_at** soft-delete (only catalog with soft-delete). |
| resource_types | masters. | keep | `resource_type.py:20` (project-svc) / `:19` (monolith) | UUID PK; deleted_at. |

### 5.5 Legacy — drop

| TABLE | OLD OWNER | DISP | CITATION | NOTES |
|---|---|---|---|---|
| work_packages | (monolith) | **legacy-exclude** | `work_package.py:15` | User-flagged. No soft-delete. Self-FK `parent_id`. **FK reached by `meeting_agenda_items.work_package_id`** — must drop after meeting_agenda_items. |
| work_package_types | (monolith) | **legacy-exclude** | `work_package_type.py:14` | Legacy companion. |
| meetings | (monolith) | **legacy-exclude** | `meeting.py:14` | User-flagged. No soft-delete. |
| meeting_agenda_items | (monolith) | **legacy-exclude** | `meeting_agenda_item.py:14` | FK chain to work_packages. |
| meeting_participants | (monolith) | **legacy-exclude** | `meeting_participant.py:14` | |
| project_members | (already migrated) | **drop-table** (if still in DB) | — | Per monolith alembic `baddc1146b85_unify_project_membership_into_user_*`, the table was unified into `user_role_assignments`. **Verify it's actually been dropped from prod** before refactor migrations run. project-svc's `__init__.py:41-42` says "retired". No model file exists in active code. |

**FK chain — drop order for legacy:**
1. `meeting_participants` (no incoming FKs)
2. `meeting_agenda_items` (FK to meetings + work_packages)
3. `meetings` (FK to projects, users)
4. `work_packages` (FK to projects, work_package_types, users — and `meeting_agenda_items.work_package_id` points here, so drop AFTER step 2)
5. `work_package_types` (no incoming FKs)
6. Any stray rows in `permissions` table with codes `work_packages:*`, `work_package_types:*`, `meetings:*` — clean up via data migration

### 5.6 Schema-level findings

- **Soft-delete inconsistency:** Most domain tables use `deleted_at + deleted_by`. Catalogs use `active boolean` instead (divisions, project_status_transitions, project_categories, activity_types, activity_statuses, milestone_statuses, resource_types). `priorities` is the lone catalog with `deleted_at`. **For the refactor, pick one convention per layer:** keep `deleted_at + deleted_by` for domain tables, keep `active` for static catalogs (matches today). Document explicitly.
- **Missing indexes:** none flagged by audit (raw reports note explicit indexes on most foreign keys and lookup columns). [UNVERIFIED] — needs `\d+` on prod tables to confirm vs ORM declarations.
- **FK integrity gaps:**
  - `comments` has no DB-level FK to its target (polymorphic by `(target_kind, target_id)`). Doc-35 trade-off; acceptable.
  - `user_role_assignments` has `CHECK ck_ura_single_scope` to enforce exactly-one of (organization_id, project_id) — preserve.
  - `milestone_vendors` in user-svc has FKs STRIPPED — that's the orphan. project-svc's `milestone_vendors` HAS the FKs. Use project-svc's definition; drop user-svc's.
- **Orphan migrations:** none found across the 45 monolith + 13 project-svc + 2 user-svc + 0 notification-svc migration chains. Two merge revisions in monolith (`eea66b52f947`, `4373b8cb0204`) cleanly close history branches.
- **`init_db()` boot-time DDL:** monolith and user-svc both run `alembic upgrade head` as a subprocess on boot + SQLite auto-heal block. The new app must remove this (Decision 4 — clean alembic, no boot-time heal). Staging-DB migration verification gated on Decision 4's "staging DB is in scope" answer.

---

## §6 Folder structure proposal (per service)

Reference shape from notification-svc, adapted per service to its actual needs. **Decision needed (see §7 Q.):** keep `controllers/` layer or drop it. Below assumes `controllers/` is kept where it adds value (request/response normalization beyond what schemas handle), dropped where routes can call services directly.

### 6.1 user-svc (target tree)

```
PMIS-refactor/services/user/
├── Dockerfile
├── alembic.ini
├── alembic/
│   ├── env.py                     # version_table='alembic_version_user'
│   └── versions/                  # COMPLETE chain owning user. schema (incl. int→UUID flip)
├── app/
│   ├── main.py                    # FastAPI app, middleware order, /health + /ready
│   ├── config.py                  # Pydantic Settings — all env vars
│   ├── db.py                      # engine, SessionLocal, Base, get_db
│   ├── models/                    # SQLAlchemy models (one file per table)
│   │   ├── user.py                # users
│   │   ├── role.py                # roles + role_permissions
│   │   ├── permission.py          # permissions + user_permissions
│   │   ├── user_role.py           # user_roles (legacy global)
│   │   ├── user_role_assignment.py # Doc-41 scoped + CHECK ck_ura_single_scope
│   │   ├── revoked_token.py
│   │   ├── password_reset_token.py
│   │   ├── otp_code.py
│   │   ├── notification_log.py
│   │   └── _cross_schema.py       # read-only declarations: divisions, vendors, projects, project_vendors (FK targets)
│   ├── repositories/              # ORM query helpers; one file per resource
│   │   ├── user_repository.py
│   │   ├── role_repository.py
│   │   ├── permission_repository.py
│   │   ├── role_assignment_repository.py
│   │   ├── rbac_repository.py     # effective_permissions_for_user, by_scope, user_has_admin_role
│   │   ├── revoked_token_repository.py
│   │   ├── password_reset_repository.py
│   │   └── otp_repository.py
│   ├── services/                  # business logic per resource (flat, one file per resource)
│   │   ├── auth_service.py        # login, logout, refresh, introspect, 2FA orchestration
│   │   ├── password_reset_service.py
│   │   ├── two_factor_service.py
│   │   ├── user_service.py        # CRUD + caller-vs-target gate (Doc-44) + vendor auto-filter (Doc-46)
│   │   ├── role_service.py        # /user/roles CRUD
│   │   ├── permission_service.py  # /user/permissions CRUD
│   │   ├── role_assignment_service.py # /user/users/{id}/role-assignments, /user/projects/{uuid}/role-assignments
│   │   └── notification_client.py # HTTP wrapper to notification-svc/dispatch
│   ├── routes/                    # FastAPI APIRouters (one file per resource)
│   │   ├── auth_routes.py         # login/logout/refresh/introspect/me/me/permissions
│   │   ├── otp_routes.py          # send-otp/verify-otp
│   │   ├── password_reset_routes.py # forgot-password, reset-password
│   │   ├── user_routes.py         # CRUD + permissions sub-paths
│   │   ├── role_routes.py
│   │   ├── permission_routes.py
│   │   ├── role_assignment_routes.py
│   │   └── health_routes.py       # /health, /ready
│   ├── schemas/                   # Pydantic v2 request/response (one file per resource)
│   │   ├── auth.py
│   │   ├── user.py
│   │   ├── role.py
│   │   ├── permission.py
│   │   ├── role_assignment.py
│   │   ├── pagination.py
│   │   └── envelope.py            # Collection<T>, ErrorEnvelope
│   ├── middleware/
│   │   ├── auth_middleware.py     # JWT decode, revoked_token check, state hydration
│   │   ├── logging_middleware.py
│   │   └── request_context.py
│   ├── core/                      # cross-cutting helpers (NOT routes/services/repos)
│   │   ├── security.py            # JWT encode/decode, argon2 password hash, jti, refresh-grace
│   │   ├── permissions.py         # permission code constants
│   │   ├── rbac.py                # require_permission, require_authenticated, require_admin, require_project_permission, require_org_permission
│   │   ├── errors.py              # DomainError hierarchy
│   │   └── response.py            # HAL formatters
│   └── utilities/
│       ├── logger.py
│       └── datetime.py
├── tests/                         # pytest; integration tests hit real Postgres
└── requirements.txt
```

**Deviations from notification-svc reference:**
- **No `controllers/` layer.** user-svc's current monolith has thin controllers but the audit shows much of the actual orchestration happens in `services/`. Flatten: routes call services directly.
- **`models/` is flat** — one file per table. No `infrastructure/db/models/`. The DDD `domain/` split in current user-svc is dropped (audit shows it's thin entities mostly used internally by repositories; SQLAlchemy models are already domain objects in 2.0 style).
- **`repositories/` is flat** — one file per resource. The current `_repository.py` files in user-svc map 1:1 to this.

**Migrations:** **NEW complete chain.** Initial migration creates every `user.` table from scratch (UUID PK for users, no legacy `admin` column, no `roles.permissions` JSON). The drift problem in current user-svc disappears because user-svc no longer relies on monolith's alembic chain.

### 6.2 project-svc (target tree)

```
PMIS-refactor/services/project/
├── Dockerfile, alembic.ini, alembic/{env.py, versions/} (version_table='alembic_version_project')
├── app/
│   ├── main.py
│   ├── config.py
│   ├── db.py
│   ├── models/                    # ONE file per table (flat)
│   │   ├── project.py
│   │   ├── project_audit_log.py
│   │   ├── project_vendor.py
│   │   ├── milestone.py
│   │   ├── milestone_dependency.py
│   │   ├── milestone_vendor.py
│   │   ├── activity.py
│   │   ├── activity_dependency.py
│   │   ├── activity_resource.py
│   │   ├── task.py
│   │   ├── task_dependency.py
│   │   ├── task_resource.py
│   │   ├── subtask.py
│   │   ├── subtask_dependency.py
│   │   ├── subtask_resource.py
│   │   ├── comment.py
│   │   └── _cross_schema.py       # read-only: users, revoked_tokens, roles, permissions, role_permissions, user_roles, user_permissions, user_role_assignments + vendors, divisions, resource_types, priorities
│   ├── repositories/
│   │   ├── project_repository.py
│   │   ├── audit_log_repository.py
│   │   ├── milestone_repository.py
│   │   ├── activity_repository.py
│   │   ├── task_repository.py
│   │   ├── subtask_repository.py
│   │   ├── comment_repository.py
│   │   ├── dependency_repository.py # used by audit-logs M/A/T/S dep snapshot
│   │   ├── dashboard_repository.py
│   │   └── tree_repository.py
│   ├── services/                  # FLAT: one file per resource, NOT one per verb
│   │   ├── project_service.py     # create / read / list / update / delete / publish / close / save / transitions / upsert
│   │   ├── milestone_service.py
│   │   ├── activity_service.py
│   │   ├── task_service.py
│   │   ├── subtask_service.py
│   │   ├── comment_service.py
│   │   ├── attachment_service.py  # file upload, MIME sniff, storage write
│   │   ├── tree_service.py
│   │   ├── dashboard_service.py
│   │   ├── assignable_users_service.py # cross-schema query into user.
│   │   └── audit_log_service.py
│   ├── routes/
│   │   ├── project_routes.py      # /project/projects/*
│   │   ├── milestone_routes.py
│   │   ├── activity_routes.py
│   │   ├── task_routes.py
│   │   ├── subtask_routes.py
│   │   ├── comment_routes.py      # factory for 4 target_kinds
│   │   ├── attachment_routes.py   # factory for 4 target_kinds
│   │   ├── tree_routes.py
│   │   ├── dashboard_routes.py
│   │   └── health_routes.py
│   ├── schemas/                   # one file per resource
│   ├── middleware/                # same as user-svc (auth, logging, request_context)
│   ├── core/                      # security.py (verify only, no encode), permissions.py (project codes), rbac.py, errors.py, response.py
│   ├── storage/
│   │   ├── file_storage.py        # local filesystem write/read
│   │   └── external_file_client.py # HTTP to FILE_SERVER_BASE_URL (current stub kept as stub)
│   └── utilities/
├── tests/
└── requirements.txt
```

**Deviations from notification-svc reference:**
- **No per-verb files in `services/`.** The current `app/api/v3/<resource>/services/{get,list,delete,restore}.py` pattern is collapsed to one `<resource>_service.py` per resource. Empirically: many of those verb files are <50 LOC; the deep nest costs navigability without paying off in cohesion.
- **No `controllers/`.** Same reasoning as user-svc.
- **`storage/` is a top-level dir** — file-handling is non-trivial here (multipart upload, MIME sniff, attachment retention) and deserves its own location.

**Migrations:** **NEW complete chain** for `project.` schema. Single initial migration creates every project. table from scratch. Subsequent migrations only for project-svc-owned tables.

### 6.3 notification-svc (target tree)

Already very close to target. Adjustments:

```
PMIS-refactor/services/notification/
├── Dockerfile
├── alembic.ini, alembic/{env.py, versions/} (NEW — was missing) (version_table='alembic_version_notification')
├── app/
│   ├── main.py
│   ├── config.py                  # was config/settings.py — flatten
│   ├── db.py                      # was db/session.py — flatten
│   ├── models/
│   │   ├── notification_template.py
│   │   └── _cross_schema.py       # read-only mirrors: user., project.
│   ├── repositories/
│   │   ├── notification_template_repository.py
│   │   └── rbac_read_repository.py # raw text() SQL OR replace with cross-schema ORM (§7 decision)
│   ├── services/
│   │   ├── email_service.py       # SMTP + SendGrid strategy
│   │   ├── sms_service.py         # Twilio + MSG91 + mock strategy
│   │   ├── otp_service.py         # NEEDS Redis-backed store (§7); currently in-memory
│   │   ├── template_service.py    # render_email, render_sms, placeholder validator (relocate from schemas/)
│   │   ├── dispatch_service.py    # Doc-38 single-call dispatch
│   │   └── digest_service.py      # daily cron
│   ├── routes/
│   │   ├── email_routes.py        # → /notification/email/send
│   │   ├── sms_routes.py          # → /notification/sms/send
│   │   ├── otp_routes.py          # → /notification/otp/{send,verify}
│   │   ├── dispatch_routes.py     # → /notification/dispatch
│   │   ├── cron_routes.py         # → /notification/cron/daily-digest, X-Cron-Secret
│   │   ├── template_routes.py     # → /notification/templates/* (replaces /api/v3/master/notification_templates/*)
│   │   └── health_routes.py
│   ├── schemas/
│   │   ├── email.py, sms.py, otp.py, dispatch.py, digest.py
│   │   └── notification_template.py # pure schema; placeholder validator MOVED to template_service.py
│   ├── middleware/
│   │   ├── auth_middleware.py
│   │   ├── error_handler.py
│   │   └── request_context.py
│   ├── core/
│   │   ├── auth.py                # JWT decode
│   │   ├── permissions.py         # MASTER_DATA_VIEW, MASTER_DATA_MANAGE constants
│   │   └── errors.py
│   └── utilities/
│       ├── logger.py
│       └── timezones.py
└── tests/
```

**Deviations from current notification-svc:**
- **Drop `controllers/` layer.** Current code: legacy email/sms/otp have controllers (3 single-method, ~5-line files); Doc-38 routes (dispatch, cron, master_data) skip the layer. Audit confirms no quality loss without controllers. Decision in §7.
- **Move `validate_placeholder_set` from `schemas/notification_template.py` to `services/template_service.py`.** Schemas should be pure.
- **Add `alembic/` chain** owning the `notification_templates` table. Removes the dependency on monolith's alembic.
- **`config/settings.py` → `config.py`**, `db/session.py` → `db.py` — flatten one level.
- **Drop `jinja2`, `MIGRATIONS_AUTORUN`/`MIGRATIONS_REQUIRED`** — dead deps/settings.
- **`OTPService` Redis-backed** — §7 decision.

### 6.4 masters-svc (NEW service)

This service doesn't exist today; routes live in monolith's `master_data/routes.py` and partially in project-svc. New scaffold:

```
PMIS-refactor/services/masters/
├── Dockerfile, alembic.ini, alembic/{env.py, versions/} (version_table='alembic_version_masters')
├── app/
│   ├── main.py
│   ├── config.py
│   ├── db.py
│   ├── models/
│   │   ├── division.py
│   │   ├── vendor.py
│   │   ├── project_category.py
│   │   ├── project_status_transition.py
│   │   ├── activity_type.py
│   │   ├── activity_status.py
│   │   ├── milestone_status.py
│   │   ├── priority.py
│   │   ├── resource_type.py
│   │   └── _cross_schema.py       # read-only: projects, users for vendor projects/users sub-listings; user_role_assignments for vendors→users mapping
│   ├── repositories/              # one file per catalog
│   ├── services/                  # one file per catalog
│   ├── routes/                    # one file per catalog + health
│   ├── schemas/                   # one file per catalog
│   ├── middleware/                # auth, logging, request_context (copies of user-svc shape)
│   ├── core/                      # security.py (verify only), permissions.py (MASTER_DATA_VIEW/MANAGE), rbac.py, errors.py, response.py
│   └── utilities/
├── tests/
└── requirements.txt
```

**Note on vendors:** vendors live in `masters.` per Decision 6 BUT have FKs reached from `user.users.vendor_id`, `user.user_role_assignments.organization_id`, `project.project_vendors.vendor_id`, `project.milestone_vendors.vendor_id`, `project.activities.vendor_id`. Cross-schema FK constraints in Postgres are allowed and we preserve them.

**Vendor sub-listings** (`GET /masters/vendors/{id}/projects`, `GET /masters/vendors/{id}/users` — though the latter is moved to user-svc per §3.1) need cross-schema reads. Handle via `_cross_schema.py` model declarations.

### 6.5 Shared (non-shared) code — duplicated per service

Per Decision 7, each service carries its own copy of:
- JWT decode logic (`core/security.py`)
- RBAC dependency factories (`core/rbac.py`)
- Permission constants (`core/permissions.py`)
- HAL response formatters (`core/response.py`)
- Pagination helpers (`schemas/pagination.py`)
- Soft-delete query helpers

**Anti-shared-package decision:** no `pmis-common` package. Cost: changes to JWT logic ripple across 4 repos. Benefit: services are independently deployable; no version-pinning hell. Mitigation: a per-file `# canonical: user-service/core/security.py` comment header on each duplicate so future developers know which is the source of truth.

---

## §7 Open questions for Checkpoint 2

Numbered for your responses. Each one is something I will NOT decide unilaterally before PLAN.md.

### 7.1 Ownership / boundary

**Q1.** **Vendors as `masters.` or `user.` org-tier?**
- The accepted ownership map in `REFACTOR_DECISIONS.md` puts vendors in masters. But `user.user_role_assignments.organization_id` FK-references vendors as the "org tier" of scoped RBAC. **Org/vendor identity is shared across the user (RBAC) and masters (catalog) domains.** Two options:
  - (a) **vendors in masters.** (current proposal): user.user_role_assignments has cross-schema FK to masters.vendors. Works in shared Postgres.
  - (b) **vendors in user.** as `user.organizations`: simpler from RBAC perspective; masters.vendors becomes a thin view or moves to user too. Loses the "catalog" framing.
- **My recommendation: (a)** — preserve today's "vendor as organization" semantics. The cross-schema FK is cheap.

**Q2.** **`/api/v3/priorities` (FE picker, kept) vs. `/masters/priorities` (catalog CRUD) — unify or keep separate?**
- Today the picker (`milestoneConfigApi.js:411`) requires only authentication; the CRUD requires `MASTER_DATA_VIEW`. Different auth, same data.
- **Options:**
  - (a) **Unify** — `/masters/priorities` serves both reads (lighten auth to `auth-only` for GETs). FE picker just calls this.
  - (b) **Keep two** — `/masters/priorities/picker` (auth-only) + `/masters/priorities` (master_data:view). Tiny duplication, clearer intent.
- **My recommendation: (a)** — fewer paths, simpler model. Read-only listing endpoints don't need a `master_data:view` permission gate for an auth'd user.

**Q3.** **`/api/v3/master/notification_templates/*` — keep under `/notification/` or `/masters/`?**
- Templates are reference data (catalog feel) BUT notification-svc is the owner. Two prefix options:
  - (a) `/notification/templates/*` (owner-aligned) — breaks the "all catalogs under /masters/" pattern.
  - (b) `/masters/notification_templates/*` (catalog-aligned) — but masters-svc doesn't own the table.
- **My recommendation: (a)** — service-prefix follows ownership, not data category.

### 7.2 Endpoint reconciliation

**Q4.** **The 5 declared-but-uncalled FE endpoints** (`endpoint.js:84, 98, 108, 118, 63` — attachments × 4 + roles.list). Before deleting their BE counterparts:
- Should I do a wider `components/` grep to confirm they're actually dead?
- Or accept the audit's `[UNVERIFIED]` flag and keep them as `move-into` (low risk) until a follow-up cleanup pass?
- **My recommendation:** grep `components/` for these 5 strings in Phase 3 implementation; default to `move` (safe), reclassify to `delete-deprecated` after grep.

**Q5.** **Legacy `/api/v3/divisions` and `/api/v3/resource_types` (catalogs router)** — the FE DOES call these (not their `/master/` successors). Should I:
- (a) Migrate the FE to `/masters/divisions` and `/masters/resource_types` (per §3 disposition: `delete-deprecated` for legacy paths)?
- (b) Keep the legacy paths as aliases in masters-svc temporarily?
- **My recommendation: (a)** — clean break. FE migration is one line each in `endpoint.js`. Per Decision 1 the new app has no monolith dependency, so aliases would only pay off if cutover required FE delays.

**Q6.** **monolith's `POST /api/v3/projects/{uuid}/role-assignments`** today is a forwarding handler that proxies to user-svc. In the new app this lands at `/user/projects/{uuid}/role-assignments` — but the FE expects it as "project-scoped" since the wider feature is project-scoped RBAC. Is `/user/projects/{uuid}/role-assignments` confusing UX? Alternative: `/user/role-assignments?project_uuid=...` (resource-shape). Or stay with the path style.
- **My recommendation:** keep the path-shape (`/user/projects/{uuid}/role-assignments`). It's clearer and matches the existing FE pattern.

**Q7.** **`/api/v3/projects/{uuid}/audit-logs`** lives in project-svc. The audit log includes user actor info pulled cross-schema from `user.users`. Is that the correct boundary, or should there be a global `/user/audit-logs` endpoint? (Current `project_audit_logs` is project-scoped only.)
- **My recommendation:** keep project-scoped only. Auth/login activity audit (different concept) doesn't exist today and is out of scope.

### 7.3 Folder shape / reference

**Q8.** **`controllers/` layer — keep or drop?**
- notification-svc has it half-adopted (legacy routes only; new Doc-38 routes go route→service).
- **My recommendation: DROP** in all four services. The audit shows no quality loss when omitted. Three near-empty files per service for no clear gain.

**Q9.** **`services/` shape — flat one-per-resource or nested one-per-verb?**
- Current project-svc has `app/api/v3/<resource>/services/{get,list,delete,restore,...}.py` (often <50 LOC each).
- **My recommendation:** flat `services/<resource>_service.py` per the §6 proposal. Matches user feedback "do not break into very complicated structure with sub-modules". The current verb-per-file pattern is the deep-nesting they want to eliminate.

**Q10.** **`domain/` separate from `models/`?**
- Current user-svc and project-svc have separate `domain/` (Python dataclasses) and `infrastructure/db/models/` (SQLAlchemy). SQLAlchemy 2.0 declarative models are already type-rich; the duplication is usually thin.
- **My recommendation: DROP `domain/`**, fold any domain-specific computed properties onto the SQLAlchemy model classes or keep them in a `_compute.py` per resource. Less indirection.

### 7.4 Schema / DB strategy

**Q11.** **Cross-schema reads for RBAC** — three options for project-svc and notification-svc reading user-svc's RBAC tables:
- (a) **Raw `text()` SQL** (current notification-svc pattern at `rbac_read_repository.py:32-43`). Brittle; schema drift breaks silently.
- (b) **Read-only ORM declarations** of `user.role_permissions`, `user.user_roles`, etc. — declared in the local `models/_cross_schema.py`. SQLAlchemy joins compile clean against the local engine because Postgres treats schemas as namespaces.
- (c) **HTTP introspection** — every authed request hits `/user/users/{id}/permissions`. Adds latency.
- **My recommendation: (b)** — ORM declarations. Schema changes in user-svc are caught by the foreign service's imports breaking, not silent 401s. Cost: each non-user service ships a read-only copy of the RBAC model classes.

**Q12.** **`project_members` table residue** — the table was unified into `user_role_assignments` per monolith alembic `baddc1146b85`. Is the table actually dropped from prod, or still sitting empty? The audit can't confirm without DB inspection.
- **My recommendation:** include a "drop project_members if exists" step in the cutover migration, idempotent.

**Q13.** **OTP store: in-memory vs Redis** — notification-svc's `OTPService` stores codes in a process-local dict. Blocks horizontal scaling. Options:
- (a) **Move OTP storage to user-svc's `otp_codes` table.** notification-svc dispatches the code but doesn't track it. Cleaner separation; matches Doc-38's "user-svc owns auth state". The verify endpoint moves to user-svc.
- (b) **Add Redis to docker-compose**, notification-svc keeps verify endpoint with Redis-backed store.
- (c) **Keep in-memory + scale notification-svc to 1 replica.** Easiest but disables HA.
- **My recommendation: (a)** — eliminate the duplicate state. notification-svc is the dispatch boundary; user-svc owns the OTP record. The current notification-svc `/otp/{send,verify}` endpoints are legacy pre-Doc-38 paths anyway.

**Q14.** **`UNIVERSAL_OTP_ENABLED` backdoor** — kept or dropped?
- Currently in monolith config + user-svc config. Defaults to False. Useful for E2E tests and emergency unlock; risky in prod.
- **My recommendation:** **keep** but make `UNIVERSAL_OTP_ENABLED` startup-error if `ENV=production`. Code-enforced safety rail.

**Q15.** **`UserModel.refresh_token_jti` + `previous_refresh_token_jti` grace window** — kept as-is? It's a stateful column on users to support the 120s grace after token rotation. Could be replaced by a `refresh_token_sessions` table, but works fine today.
- **My recommendation:** keep as-is. Don't refactor what isn't broken.

**Q16.** **`init_db()` boot-time DDL** — current monolith runs alembic + a 300-line SQLite ALTER auto-heal block on every boot. The new app drops boot-time DDL?
- **My recommendation: DROP.** Per Decision 4, alembic migrations run separately (via `docker-compose run --rm <service> alembic upgrade head` against staging then prod). No boot-time schema modification.

### 7.5 Auth

**Q17.** **The `pre-Doc-26 integer-id JWT` guard** at `monolith/app/core/middleware/auth.py:78-88` rejects access tokens whose `user_id` claim is an integer (i.e. tokens issued before Doc-26 flipped users.id to UUID). For cutover:
- (a) **Keep the guard.** Forces all users to re-login post-cutover.
- (b) **Drop it.** Tokens older than `ACCESS_TOKEN_EXPIRE_MINUTES=120` are already expired, so the guard is largely vestigial.
- **My recommendation: (b)** — drop. 2-hour token lifetime + 7-day refresh means cutover happens during a normal token lifetime and the guard adds no real protection.

**Q18.** **Logout / revoked_tokens — read by 3 services**. The `revoked_tokens` table is checked by every authed request in user-svc, project-svc, notification-svc, masters-svc. That's a hot path. Options:
- (a) **Status quo** — DB query per request. Today's pattern.
- (b) **In-memory cache per service** with TTL = token grace window (~2 min). Each service polls every N seconds.
- (c) **Redis-backed shared blacklist.**
- **My recommendation: (a)** — keep DB query. At 4 services × hundreds of requests/sec it's still well under the DB's capacity. Add (b) only if profiling shows it as a bottleneck.

### 7.6 Migration / cutover

**Q19.** **Migration ordering.** Per Decision 4, staging DB will validate migrations before prod. Order:
- notification-svc first (single owned table, simplest)
- masters-svc next (catalogs only, no inbound FKs from other services on day 1 if we keep the cross-schema FK approach)
- user-svc (deepest auth dependencies; everyone reads from it)
- project-svc last (biggest schema; reads from user-svc + masters-svc)
- **My recommendation: agreed** — same order.

**Q20.** **Data migration from monolith → per-service schemas.** Currently every table is in `public` schema. Moving to per-service schemas means either:
- (a) **Rename in place** — `ALTER TABLE public.users SET SCHEMA user;` — fast, no data copy, **but breaks any cross-schema references that haven't been updated**.
- (b) **Copy + cutover** — create tables in new schema, copy rows, swap on a maintenance window.
- **My recommendation: (a)** + a coordinated config-rollout. PLAN.md will detail the exact sequence.

**Q21.** **Bootstrap data (admin user, master catalogs).** Today the monolith's `init_db()` seeds bootstrap superadmin, default divisions, default permissions catalog. In the new app, where?
- **My recommendation:** each service ships its own bootstrap script as a separate alembic data-migration. Run once per env via `alembic upgrade <bootstrap_rev>`. No more boot-time seeding.

### 7.7 Other

**Q22.** **`MAX_UPLOAD_MB` default** — set to 50 in Decision 8c, pending audit verification of real attachment sizes. Monolith config has `ATTACHMENTS_MAX_BYTES=26214400` (= 25 MB). Stick with 25 to match today, or bump to 50?
- **My recommendation: keep 25 MB.** Match current production behavior. Document the env var so devops can raise it later if needed.

**Q23.** **Sentry / observability** — monolith ships `sentry-sdk==2.57.0` but no `sentry_sdk.init` call is found in the source. INFERRED: not currently wired. New app:
- (a) Add `sentry_sdk.init` to each service with a per-service DSN env var.
- (b) Skip Sentry; rely on stdout logs.
- **My recommendation: (b) for now.** Add (a) as a Phase 4 enhancement once core refactor is stable.

**Q24.** **Notification service's read-only RBAC mirroring** — notification-svc currently raw-SQLs `user.role_permissions JOIN user_roles` to hydrate permissions. If we go with Q11(b), the column-drift risk goes away. But if a column rename in user-svc breaks notification-svc imports, we discover it at import time (boot crash) instead of silent 401s. Either way: do we want a **cross-repo schema test** that imports all services' models against the same DB and asserts consistency? Recommended in §10 of notification-svc raw report.
- **My recommendation:** yes — add a `tests/test_cross_schema_drift.py` in the user-svc repo that imports the read-only models from project-svc and notification-svc and asserts they line up. Catches drift in CI.

**Q25.** **Dead permission constants `MEETINGS_*` and `WORK_PACKAGES_*`** in active `app/core/permissions.py` and `app/core/rbac.py` of project-svc, plus monolith's `app/core/permissions.py`. They're seeded into the `permissions` table on boot and emitted by HAL link builders.
- The refactor should drop these constants AND delete any rows in `permissions` table whose `code` starts with `meetings:`, `work_packages:`, `work_package_types:`.
- **My recommendation:** include in the legacy-cleanup data migration. PLAN.md §3.

---

## Status

- **`work_packages`, `meetings`, `work_package_types`, `meeting_agenda_items`, `meeting_participants`** — fully enumerated, marked `legacy-exclude`, FK chain documented in §5.5. Not ported.
- **`project_members`** — table already migrated to `user_role_assignments` per monolith alembic head. No route or model in active code (only in user-svc's stale `src/` and project-svc's stale `src/`). Cleanup step in §5.5.
- **Old project implementation** — confirmed as the `PMIS-project-management/src/` duplicate tree (~95 files). Source-only, refactor doesn't touch it.
- **Every CURRENT meaningful endpoint** has a row in §3 with a `move` / `merge` / `delete-deprecated` disposition. **Nothing falls through the cracks** per Decision 1.
- **The "assign-roles vs users" call-out** is resolved in §3.5 as a triplet, not a pair. Legacy assign-role is deleted; canonical scoped role-assignment is kept; the RBAC-filtered user list is a distinct read with different intent — kept.

Awaiting your responses to **Q1–Q25** before drafting PLAN.md.
