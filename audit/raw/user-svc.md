# PMIS-user-management Audit

Source repo: `C:\Programming\PMIS\PMIS-user-management\`
Audited 2026-05-14. All citations use `path:line` relative to that root (or absolute where noted).

OBSERVED unless explicitly marked INFERRED / [UNVERIFIED].

---

## 1. Tech & dependencies

OBSERVED — `requirements.txt`:

- `fastapi==0.115.6` (requirements.txt:1)
- `uvicorn[standard]==0.32.1` (requirements.txt:2)
- `sqlalchemy==2.0.36` (requirements.txt:3)
- `psycopg2-binary==2.9.10` (requirements.txt:4)
- `alembic==1.18.1` (requirements.txt:5)
- `pydantic==2.10.3` / `pydantic-settings==2.7.0` (requirements.txt:6-7)
- `email-validator==2.2.0` (requirements.txt:8)
- `python-multipart==0.0.20` (requirements.txt:9)
- `python-jose[cryptography]==3.3.0` (requirements.txt:10)
- `argon2-cffi==23.1.0` (requirements.txt:11)
- Test/HTTP: `pytest==8.3.4`, `httpx==0.28.1` (requirements.txt:12-13). `httpx` is also a runtime dep — used by the notification HTTP client (`app/shared/notifications.py:35`).
- INFERRED: Python 3.11 (Dockerfile:6 `FROM python:3.11-slim`).
- Notably absent: passlib/bcrypt (argon2-cffi replaces it), no redis / no celery, no shared internal package.

---

## 2. Entry point & startup

- App factory / module: `app/main.py:57` (`app = FastAPI(...)`).
- Lifespan: `app/main.py:33-54` — calls `init_db()` (`app/main.py:37`), warns on `UNIVERSAL_OTP_ENABLED` (`app/main.py:45-51`), logs `port 8001` (`app/main.py:52`).
- Routers mounted: only one — `api_v3_router` at `app/main.py:124` from `app/api/__init__.py:2`. That central router (`app/api/router.py:29`) prefixes everything with `/api/v3` and includes 7 sub-routers:
  - `users_router` (`app/api/router.py:32`)
  - `master_data_router` (line 33)
  - `user_role_assignments_router` / `project_role_assignments_router` / `vendor_projects_router` / `role_grants_router` (lines 38-41)
  - `roles_router` and `permissions_router` (lines 47-48; marked DEPRECATED, mounted last).
- Health / root: `GET /health` (`app/main.py:166`), `GET /` (`app/main.py:182`).

### Middleware order
`app/main.py:81-90`. Starlette wraps LIFO so outermost-to-innermost on a request:
1. CORSMiddleware (outermost; `allow_origins=["*"]`) — `app/main.py:84-90`.
2. AuthenticationMiddleware — `app/main.py:82` → `app/core/middleware/auth.py:50`.
3. LoggingMiddleware (innermost) — `app/main.py:81`.

Plus two exception handlers: `DomainError` → mapped status (`app/main.py:95-105`), generic `Exception` → 500 with `details` only when `DEBUG` (`app/main.py:108-119`).

### Env vars / settings (all in `app/core/config.py`)
- `APP_NAME`, `APP_VERSION`, `SERVICE_NAME`, `DEBUG` (lines 29-32)
- `SECRET_KEY` (line 35) — explicitly shared with monolith.
- `ALGORITHM=HS256` (line 39)
- `ACCESS_TOKEN_EXPIRE_MINUTES=120` (line 47 — comment notes it was bumped 15→60→120 as a hotfix for FE refresh bug, "must match monolith")
- `REFRESH_TOKEN_EXPIRE_DAYS=7` (line 48), `REFRESH_TOKEN_GRACE_SECONDS=120` (line 49)
- `DATABASE_URL` (line 52), `DATABASE_URL_MIGRATIONS` (line 57)
- `MIGRATIONS_AUTORUN=True` (line 71), `MIGRATIONS_REQUIRED=True` (line 79)
- `CORS_ORIGINS=["http://localhost:3000"]` (line 90) — but middleware actually uses `["*"]` (`app/main.py:86`)
- `BOOTSTRAP_ADMIN_*` (lines 96-98), `BOOTSTRAP_SUPERADMIN_*` (lines 106-108)
- `DEFAULT_PAGE_SIZE=20`, `MAX_PAGE_SIZE=100` (lines 111-112)
- `REQUIRE_2FA=True` (line 115)
- `OTP_TTL_SECONDS=300`, `OTP_RESEND_COOLDOWN_SECONDS=60`, `OTP_MAX_ATTEMPTS=5`, `OTP_CODE_LENGTH=6`, `OTP_HASH_PEPPER` (lines 124-128)
- `PASSWORD_RESET_TTL_SECONDS=3600` (line 136)
- `FRONTEND_BASE_URL` (line 139)
- `NOTIFICATION_CLIENT="mock"`, `NOTIFICATION_SERVICE_URL=""` (lines 150-156)
- `UNIVERSAL_OTP_ENABLED=False`, `UNIVERSAL_OTP_CODE="000000"` (lines 169-178) — break-glass for OTP.

Direct `os.getenv` use is limited to alembic infra: `app/infrastructure/db/session.py:24` (`import os`) only passes env through to the alembic subprocess (`session.py:74` `env=env`). Settings are otherwise the single source of truth.

### DB connection
- `engine = create_engine(settings.DATABASE_URL, echo=settings.DEBUG)` — `app/infrastructure/db/session.py:32`.
- `SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)` — `session.py:34`.
- `Base(DeclarativeBase)` — `session.py:37-39`.
- `get_db()` FastAPI dep — `session.py:42-48`.
- **No schema qualifier** OBSERVED on any model `__tablename__` (e.g. `app/infrastructure/db/models/user.py:26` `__tablename__ = "users"`). INFERRED: default `public` schema in Postgres.

### Port
- Dockerfile `EXPOSE 8001` (Dockerfile:36); CMD binds `--port 8001` (Dockerfile:40).
- docker-compose maps `8001:8001` (docker-compose.yml:24).
- `app/main.py:52` logs `port 8001`. **Port 8001 confirmed.**

---

## 3. Route inventory (FULL)

All paths carry the `/api/v3` prefix from `app/api/router.py:29` unless they are the bare `/health` or `/`. Auth column abbreviations:
- `anon` = no dep (or dep is none; auth middleware runs but no `require_*`)
- `auth` = `require_authenticated()`
- `perm:CODE` = `require_permission(CODE)` or `require_any_permission(...)`

Tables abbreviated: `u`=users, `r`=roles, `p`=permissions, `ur`=user_roles, `rp`=role_permissions, `up`=user_permissions, `ura`=user_role_assignments, `rt`=revoked_tokens, `prt`=password_reset_tokens, `otp`=otp_codes, `nl`=notification_log, `v`=vendors, `pr`=projects, `pv`=project_vendors, `d`=divisions.

### Users router (`app/api/v3/users/routes.py`)

| METHOD | PATH | HANDLER (file:line) | AUTH | RBAC | REQUEST SCHEMA | RESPONSE | DB TABLES | EXTERNAL HTTP | NOTES |
|---|---|---|---|---|---|---|---|---|---|
| POST | /api/v3/users/introspect | `users/routes.py:54` | anon | — | `IntrospectRequest` | `Introspect` (RFC7662 metadata; access/refresh sub-objects) | u, rt | — | Public (whitelisted in OpenAPI public_paths, main.py:148) |
| POST | /api/v3/users/refresh | `users/routes.py:74` | anon | — | `RefreshRequest` | `Refresh` (new access+refresh+expiry meta) | u, rt | — | Public; rotates refresh_token_jti atomically with grace window |
| POST | /api/v3/users/login | `users/routes.py:94` | anon | — | `LoginRequest` | `Login` (access/refresh + user) OR `LoginOtpRequired` | u, otp, nl | — | 2FA branch returns `{requires_otp, ephemeral_token, channels_available}` (controller.py:684-700) |
| POST | /api/v3/users/login/send-otp | `users/routes.py:117` | anon | — | `OtpSendRequest` | `OtpSent` | u, otp, nl | →notification-service (HttpNotificationClient, see §7) | — |
| POST | /api/v3/users/login/verify-otp | `users/routes.py:134` | anon | — | `OtpVerifyRequest` | `Login` (full token pair) | u, otp | — | Honours UNIVERSAL_OTP break-glass when enabled |
| POST | /api/v3/users/forgot-password | `users/routes.py:150` | anon | — | `ForgotPasswordRequest` | generic 200 | u, prt, nl | →notification-service | Always-200 anti-enumeration |
| POST | /api/v3/users/reset-password | `users/routes.py:165` | anon | — | `ResetPasswordRequest` | generic 200 | u, prt | — | — |
| POST | /api/v3/users/logout | `users/routes.py:183` | auth | — | — (header bearer) | success message | u, rt | — | Inserts jti into rt + clears refresh jti |
| GET | /api/v3/users/me | `users/routes.py:197` | auth | — | — | User HAL | u, v, ura, pr | — | — |
| POST | /api/v3/users/create | `users/routes.py:216` | — | perm:USERS_CREATE | `UserCreateRequest` | User HAL | u, ur, ura, v, pr, pv | — | Doc 44 — orgRole + project_assignments; caller-vs-target gate fires |
| GET | /api/v3/users/check-login | `users/routes.py:244` | auth | — | query `login` | `{login, available}` | u | — | Includes soft-deleted (line 254) |
| **GET** | **/api/v3/users** (list) | **`users/routes.py:268`** | — | **perm:USERS_READ_ALL** | query `offset, pageSize, status, include_deleted` | `Collection<User>` (paged HAL — `format_collection_response`) | u, v, pr, ur, ura | — | **Special focus.** Non-admin callers auto-filtered by their `vendor_id` AND excludes admin-tier users via NOT-EXISTS subqueries (controller.py:299-333 + user_repository.py:415-437). Response items carry id, login, email, fullName, firstName, lastName, isAdmin, isSuperAdmin, status, vendor_id, vendor_name, division, division_other, phone_number, two_factor_enabled, deleted_at, deleted_by, user_code, projects[] (user_repository.py:101-122 + controller.py:336-348). [UNVERIFIED] exact wire shape — would need to read `format_user_response`/`format_collection_response` in `app/core/response.py` (file not opened). |
| GET | /api/v3/users/{user_id} | `users/routes.py:307` | — | perm:USERS_READ | path int|`US-...` code | User HAL | u, v, pr, ura | — | Read-side super_admin shield (controller.py:158-183) |
| PATCH | /api/v3/users/{user_id} | `users/routes.py:338` | — | perm:USERS_UPDATE or USERS_DEACTIVATE | `UserUpdateRequest` | User HAL | u, ur, ura, pr, v | — | deactivate-only callers restricted to status field (routes.py:388-407) |
| PATCH | /api/v3/users/{user_id}/password | `users/routes.py:424` | — | perm:USERS_UPDATE | `UserPasswordUpdateRequest` | success | u | — | Destructive — `can_caller_modify_user(op="destructive")` (routes.py:445) |
| DELETE | /api/v3/users/{user_id} | `users/routes.py:467` | — | perm:USERS_DELETE_ALL | — | success | u | — | Destructive gate; last-super_admin lockout |
| POST | /api/v3/users/{user_id}/restore | `users/routes.py:509` | — | perm:USERS_DELETE_ALL | — | User HAL | u | — | Idempotent on already-active |
| GET | /api/v3/users/me/permissions | `users/routes.py:568` | auth | — | — | `EffectivePermissions` | u, ur, up, rp, ura | — | — |
| GET | /api/v3/users/{user_id}/permissions | `users/routes.py:593` | — | perm:PERMISSIONS_READ | — | `EffectivePermissions` | u, ur, up, rp, ura | — | — |
| POST | /api/v3/users/{user_id}/permissions/{code} | `users/routes.py:625` | — | perm:RBAC_ASSIGN | — | direct-perms snapshot | u, up | — | Reserved-perm guard on `users:grant_superadmin` (routes.py:634) |
| DELETE | /api/v3/users/{user_id}/permissions/{code} | `users/routes.py:673` | — | perm:RBAC_ASSIGN | — | 204 | u, up | — | — |
| GET | /api/v3/users/{user_id}/roles | `users/routes.py:710` | — | perm:PERMISSIONS_READ | — | `Collection<Role>` (DEPRECATED) | u, ur, r | — | Stamps `Deprecation` header; successor → /role-assignments |
| **POST** | **/api/v3/users/{user_id}/roles/{role_id}** | **`users/routes.py:752`** | — | **perm:RBAC_ASSIGN** | — | role list (DEPRECATED) | u, ur, r, ura | — | **The legacy "assign role" path.** Doc 42b caller-vs-target gate via `can_caller_grant` (routes.py:780-794) |
| DELETE | /api/v3/users/{user_id}/roles/{role_id} | `users/routes.py:824` | — | perm:RBAC_ASSIGN | — | 204 (DEPRECATED) | u, ur, r | — | — |

### Master-data router (`app/api/v3/master_data/routes.py`)

All gated by `perm:MASTER_DATA_VIEW` or `perm:MASTER_DATA_MANAGE`. Every handler delegates to a legacy `roles` or `permissions` handler and strips the `Deprecation` header (`master_data/routes.py:66-71`):

| METHOD | PATH | HANDLER (file:line) | GATE |
|---|---|---|---|
| GET | /api/v3/master/roles | `master_data/routes.py:83` | VIEW |
| GET | /api/v3/master/roles/{role_id} | `master_data/routes.py:102` | VIEW |
| POST | /api/v3/master/roles/create | `master_data/routes.py:116` | MANAGE |
| PATCH | /api/v3/master/roles/{role_id} | `master_data/routes.py:131` | MANAGE |
| DELETE | /api/v3/master/roles/{role_id} | `master_data/routes.py:147` | MANAGE |
| GET | /api/v3/master/roles/{role_id}/permissions | `master_data/routes.py:160` | VIEW |
| PUT | /api/v3/master/roles/{role_id}/permissions | `master_data/routes.py:173` | MANAGE |
| POST | /api/v3/master/roles/{role_id}/permissions/{code} | `master_data/routes.py:191` | MANAGE |
| DELETE | /api/v3/master/roles/{role_id}/permissions/{code} | `master_data/routes.py:207` | MANAGE |
| GET | /api/v3/master/permissions | `master_data/routes.py:227` | VIEW |
| GET | /api/v3/master/permissions/by-module | `master_data/routes.py:245` | VIEW |
| GET | /api/v3/master/permissions/{code} | `master_data/routes.py:287` | VIEW |
| POST | /api/v3/master/permissions/create | `master_data/routes.py:301` | MANAGE |
| PATCH | /api/v3/master/permissions/{code} | `master_data/routes.py:316` | MANAGE |
| DELETE | /api/v3/master/permissions/{code} | `master_data/routes.py:332` | MANAGE |

### Role-assignments router (`app/api/v3/role_assignments/routes.py`)

| METHOD | PATH | HANDLER (file:line) | AUTH | RBAC | REQUEST | RESPONSE | TABLES |
|---|---|---|---|---|---|---|---|
| GET | /api/v3/users/{user_id}/role-assignments | `role_assignments/routes.py:68` | auth+self-or-USERS_READ_ALL | — | — | `{items, total}` of assignments | ura, r, u, pr, v |
| **POST** | **/api/v3/users/{user_id}/role-assignments** | **`role_assignments/routes.py:116`** | — | **perm:RBAC_ASSIGN** | `RoleAssignmentCreateRequest` | created assignment OR `{items, total}` for batch | ura, r, u, pr, pv, v |
| DELETE | /api/v3/users/{user_id}/role-assignments/{assignment_id} | `role_assignments/routes.py:149` | — | perm:RBAC_ASSIGN | — | 204 | ura, r, u |
| GET | /api/v3/projects/{project_uuid}/role-assignments | `role_assignments/routes.py:199` | — | perm:PROJECT_MEMBERS_READ | — | per-role buckets | ura, r, u, pr |
| POST | /api/v3/projects/{project_uuid}/role-assignments | `role_assignments/routes.py:253` | — | perm:RBAC_ASSIGN | `RoleAssignmentCreateRequest` (userId required) | created assignment | ura, r, u, pr, pv |
| DELETE | /api/v3/projects/{project_uuid}/role-assignments/{assignment_id} | `role_assignments/routes.py:282` | — | perm:RBAC_ASSIGN | — | 204 | ura, r, u |
| GET | /api/v3/vendors/{vendor_id}/projects | `role_assignments/routes.py:333` | auth+(PROJECTS_READ_ALL OR org-scoped to vendor) | — | query `expand` | `{vendorId, vendorName, projects[]}` (optional roleAssignments) | v, pr, pv, ura, r, u |
| GET | /api/v3/vendors/{vendor_id}/users | `role_assignments/routes.py:432` | auth+(USERS_READ_ALL OR org-scoped) | — | offset/pageSize/status/include_deleted | `Collection<User>` | v, u, ur, ura, r |
| GET | /api/v3/users/{user_id}/projects | `role_assignments/routes.py:525` | auth+self-or-USERS_READ_ALL | — | — | `{userId, userLogin, projects[]}` | ura, r, pr, u |
| GET | /api/v3/role-grants/{role_name} | `role_assignments/routes.py:591` | auth | — | — | `{roleName, grantableRoles[]}` | — (static matrix) |

### Roles router (DEPRECATED, `app/api/v3/roles/routes.py`)

All paths stamp `Deprecation: true` + `Link: rel="successor-version"` (helper `_stamp`, `roles/routes.py:33-40`).

| METHOD | PATH | HANDLER (file:line) | GATE |
|---|---|---|---|
| POST | /api/v3/roles/create | `roles/routes.py:49` | perm:ROLES_CREATE |
| GET | /api/v3/roles | `roles/routes.py:65` | perm:ROLES_READ |
| GET | /api/v3/roles/{role_id} | `roles/routes.py:83` | perm:ROLES_READ |
| PATCH | /api/v3/roles/{role_id} | `roles/routes.py:99` | perm:ROLES_UPDATE |
| DELETE | /api/v3/roles/{role_id} | `roles/routes.py:116` | perm:ROLES_DELETE |
| GET | /api/v3/roles/{role_id}/permissions | `roles/routes.py:160` | perm:ROLES_READ |
| PUT | /api/v3/roles/{role_id}/permissions | `roles/routes.py:198` | perm:ROLES_UPDATE |
| POST | /api/v3/roles/{role_id}/permissions/{code} | `roles/routes.py:272` | perm:ROLES_UPDATE |
| DELETE | /api/v3/roles/{role_id}/permissions/{code} | `roles/routes.py:336` | perm:ROLES_UPDATE |

### Permissions router (DEPRECATED, `app/api/v3/permissions/routes.py`)

| METHOD | PATH | HANDLER (file:line) | GATE |
|---|---|---|---|
| GET | /api/v3/permissions | `permissions/routes.py:60` | perm:PERMISSIONS_READ |
| GET | /api/v3/permissions/{code} | `permissions/routes.py:93` | perm:PERMISSIONS_READ |
| POST | /api/v3/permissions | `permissions/routes.py:118` | perm:PERMISSIONS_MANAGE |
| PATCH | /api/v3/permissions/{code} | `permissions/routes.py:151` | perm:PERMISSIONS_MANAGE |
| DELETE | /api/v3/permissions/{code} | `permissions/routes.py:181` | perm:PERMISSIONS_MANAGE |

### Top-level (not under /api/v3)
| METHOD | PATH | HANDLER | NOTES |
|---|---|---|---|
| GET | /health | `app/main.py:166` | Returns service status + first 12 hex of sha256(SECRET_KEY) so ops can confirm shared-key parity |
| GET | / | `app/main.py:182` | HAL root |

### Route count (excluding /health, /)
OBSERVED: **47** API routes under `/api/v3`.
- Users: 24 (incl. roles legacy + permissions sub-routes)
- Master: 15
- Role-assignments: 10 across 4 sub-routers
- Roles legacy: 9
- Permissions legacy: 5

(Note: `master_data` handlers delegate into the same legacy handlers, so they share controller logic; they count as distinct FastAPI routes for client-facing purposes.)

### Special-focus — assign-roles and users-list responses

**assign-roles — TWO endpoints, both live:**

1. **Legacy global path:** `POST /api/v3/users/{user_id}/roles/{role_id}` — `app/api/v3/users/routes.py:752` (`assign_user_role`). Writes to `user_roles`. Returns:
   ```
   { userId, roles: [{ _type:"Role", _links:{self:{href:...}}, id, name, description, builtin }] }
   + headers: Deprecation: true, Link: </api/v3/users/{id}/role-assignments>; rel="successor-version"
   ```
   The caller-vs-target gate is `can_caller_grant(target_role_name=role.name, target_organization_id=None, target_project_id=None)` (routes.py:780-787).

2. **Canonical scoped path:** `POST /api/v3/users/{user_id}/role-assignments` — `app/api/v3/role_assignments/routes.py:116` (`create_user_role_assignment`). Writes to `user_role_assignments` (the doc-41 table). Accepts `{ roleId, organizationId? | projectId? | projectIds? }`. Returns either:
   ```
   single: serialize_assignment(...) → { id, userId, userLogin, userEmail, roleId, roleName, organizationId, projectId, scope, createdAt, createdBy }
   batch:  { items: [...assignments...], total: N }
   ```
   `serialize_assignment` at `app/api/v3/role_assignments/services.py:225-256`.

**users-list — `GET /api/v3/users`:** Handler at `app/api/v3/users/routes.py:268` (`list_users`). Gate is `require_permission(USERS_READ_ALL)`. Controller adds two non-admin-only filters:
- vendor_id auto-filter to caller's own vendor (`controller.py:306-319`).
- `exclude_admin_tier=True` (`controller.py:333`) — NOT-EXISTS subqueries against both `user_roles` and `user_role_assignments` for any row joining `admin`/`super_admin` role (`user_repository.py:415-437`).

Per-row shape comes from `User.to_dict()` then `format_user_response()` (function in `app/core/response.py`, not opened). Domain `User` attrs (`user_repository.py:101-122`): `id, login, email, first_name, last_name, admin, is_super_admin, status, created_at, updated_at, vendor_id, vendor_name, division, division_other, phone_number, two_factor_enabled, deleted_at, deleted_by, user_code, projects`. The list response wraps these in `format_collection_response` (HAL Collection `{ _type:"Collection", _embedded:{elements:[...]}, total, count, pageSize, offset, _links }` — same shape used by permissions list at `permissions/routes.py:71-78`).

[UNVERIFIED] exact JSON envelope for the list (would need `app/core/response.py` + `format_user_response` to confirm whether keys are camelCase or snake_case in the final wire shape). Schema uses camelCase aliases (`schemas.py:64, 105, 118`).

### Monolith parallels

INFERRED (parallel paths exist in monolith): `C:\Programming\PMIS\PMIS-OpenProject\app\api\v3\users\routes.py` exists (Glob hit). [UNVERIFIED] route-by-route diff between monolith and this service — needs side-by-side read.

---

## 4. Models (SQLAlchemy)

Declared on `Base.metadata` via the package `__init__.py` (`app/infrastructure/db/models/__init__.py:16-37`).

| TABLE | MODEL (file:line) | COLUMNS | FKs | INDEXES | SOFT-DELETE? | CLASS | NOTES |
|---|---|---|---|---|---|---|---|
| users | UserModel (`models/user.py:23`) | id(UUID, PK), user_code, login(UQ), email(UQ), hashed_password, first_name, last_name, status, created_at, updated_at, refresh_token_jti, refresh_token_expires_at, previous_refresh_token_jti, previous_refresh_token_jti_valid_until, vendor_id, division, division_other, phone_number, org_role, two_factor_enabled, deleted_at, deleted_by | vendor_id→vendors.id (use_alter=True, models/user.py:79-83); deleted_by→users.id (self, line 128) | login, email, status, created_at, deleted_at, vendor_id (lines 132-137) | YES (deleted_at, deleted_by) | **CORE-USER** | Doc 26 flipped PK to UUID. `admin` column dropped — admin status derived via user_roles. `org_role` column (line 113) is a doc-45 cache of the FE label. |
| roles | RoleModel (`models/role.py:21`) | id(int, PK), name(UQ), description, builtin, created_at, updated_at | — | name, builtin (lines 35-36) | NO | CORE-USER | JSON permissions column dropped per doc 21B. |
| permissions | PermissionModel (`models/permission.py:25`) | code(PK), name, description, is_builtin, created_at, updated_at | — | — | NO | CORE-USER | `code` like `"users:create"` is the PK. |
| user_roles | UserRoleModel (`models/user_role.py:14`) | user_id+role_id (composite PK), created_at, created_by | user_id→users.id, role_id→roles.id, created_by→users.id | user_id, role_id | NO | CORE-USER | Legacy global-only role assignments. |
| role_permissions | RolePermissionModel (`models/role_permission.py:14`) | role_id+permission_code (composite PK), created_at | role_id→roles.id, permission_code→permissions.code | role_id, permission_code | NO | CORE-USER | — |
| user_permissions | UserPermissionModel (`models/user_permission.py:18`) | user_id+permission_code (composite PK), created_at, created_by | user_id→users.id, permission_code→permissions.code, created_by→users.id | user_id, permission_code | NO | CORE-USER | Direct grants (additive). |
| user_role_assignments | UserRoleAssignmentModel (`models/user_role_assignment.py:44`) | id(int, PK), user_id, role_id, organization_id, project_id, created_at, created_by | user_id→users.id, role_id→roles.id, organization_id→vendors.id, project_id→projects.id, created_by→users.id | user, project, org, role; CHECK ck_ura_single_scope; UNIQUE (user_id, role_id, organization_id, project_id) | NO | CORE-USER | Doc 41 scoped RBAC table. **FKs reach projects + vendors — physical cross-domain link.** |
| revoked_tokens | RevokedTokenModel (`models/revoked_token.py:26`) | jti(PK), user_id, revoked_at, expires_at | user_id→users.id | user_id, expires_at | NO | CORE-USER | JWT blacklist (hard-logout / cross-service revocation). |
| password_reset_tokens | PasswordResetTokenModel (`models/password_reset_token.py:32`) | id(int, PK), user_id, channel, token_hash(UQ), generated_at, expires_at, consumed_at | user_id→users.id | (user_id, consumed_at) | NO | CORE-USER | Doc 33 forgot-password flow. |
| otp_codes | OtpCodeModel (`models/otp_code.py:37`) | id(int, PK), user_id, channel, code_hash, ephemeral_token_hash, generated_at, expires_at, consumed_at, attempt_count, last_sent_at | user_id→users.id | ephemeral_token_hash, (user_id, consumed_at) | NO | CORE-USER | 2FA login flow. |
| notification_log | NotificationLogModel (`models/notification_log.py:22`) | id(int, PK), user_id, channel, recipient, template_kind, payload(JSON), status, error, created_at | user_id→users.id | channel, template_kind, status, created_at, (user_id, template_kind) | NO | CORE-USER | User-svc's own audit log; templates moved to notification-svc per doc 38. |
| divisions | DivisionModel (`models/division.py:27`) | id(int, PK), code(UQ), label, is_builtin, requires_other, active, created_at, updated_at | — | (code, active) | NO | **CROSS-DOMAIN-READ-ONLY** | Docstring: "Read-only mirror of the monolith's divisions table" (`models/division.py:1-13`). Doc 49. user-svc only reads to validate `users.division`. |
| projects | ProjectModel (`models/project.py:27`) | id(UUID PK), project_code(UQ), name, description, active, public, status, owner, parent_id(self FK), deleted_at, deleted_by, created_at, updated_at | parent_id→projects.id | status, deleted_at | YES (column present; not written here) | **CROSS-DOMAIN-READ-ONLY** | Module docstring (`models/project.py:1-14`): "Slim mapping, READ-ONLY". Used to (a) validate project_ids on user-create and (b) join project rows into user responses. |
| vendors | VendorModel (`models/vendor.py:31`) | id(UUID PK), vendor_code(UQ), name(UQ), description, active, email, contact_person, phone_number, created_at, updated_at, deleted_at, deleted_by | deleted_by→users.id | active+name, created_at, deleted_at, email | YES | **CROSS-DOMAIN-READ-ONLY** | Used heavily by user-svc — vendor_id FK on users, on user_role_assignments (org_id), org-scoped RBAC depends on it. user-svc only reads; writes are owned by monolith. |
| project_vendors | ProjectVendorModel (`models/project_vendor.py:17`) | project_id+vendor_id (composite PK), created_at | project_id→projects.id, vendor_id→vendors.id | project_id, vendor_id | NO | **CROSS-DOMAIN-READ-ONLY** | Used by `_project_owning_vendors` in caller-vs-target gate (`role_assignments/services.py:143-150`) and by `/vendors/{id}/projects` (`role_assignments/routes.py:367-373`). |
| milestone_vendors | MilestoneVendorModel (`models/milestone_vendor.py:20`) | milestone_id+vendor_id, created_at | **NONE** (FKs stripped) | milestone, vendor | NO | **CROSS-DOMAIN — ORPHAN** | Module docstring (`models/milestone_vendor.py:1-9`): "user-mgmt never writes this table; the monolith does. Stripping the FKs lets SQLite test create_all succeed without milestones / vendors tables." OBSERVED: zero usages in routes / services — only referenced by `models/__init__.py` and `repositories/vendor_repository.py` (per grep). |

### Cross-domain model usage analysis (Grep `ProjectModel|VendorModel|DivisionModel|ProjectVendorModel|MilestoneVendorModel`)

OBSERVED usage map:

- **DivisionModel** — only `app/shared/division_catalog.py` (the validation helper) and the model itself. READ-ONLY mirror, used to validate `users.division`. Justified by `models/division.py:1-13`.
- **VendorModel** — used in `role_assignments/routes.py`, `role_assignments/services.py`, `vendor_repository.py`, `user_repository.py`, plus indirectly via `users.vendor_id` FK. Reads only. Justified — vendor scope is the org tier in scoped RBAC.
- **ProjectModel** — used in `role_assignments/routes.py`, `users/services/create.py`, `users/services/update.py`, `users/services/replace_project_membership.py`, `user_repository.py`, `role_assignments/services.py`. Reads only — validating project_ids on user-create, joining to surface user's project list, group-by views.
- **ProjectVendorModel** — used in `role_assignments/routes.py` and `role_assignments/services.py`. Reads only — needed to walk project→vendor for org-scoped RBAC gate (`role_assignments/services.py:143-150`).
- **MilestoneVendorModel** — **only referenced by `models/__init__.py` and `repositories/vendor_repository.py`**. INFERRED orphan — kept only because vendor_repository imports it. [UNVERIFIED] whether vendor_repository actually queries it or just imports it; the docstring suggests it's a SQLite-test-DB scaffolding artifact only.

**INFERRED conclusion (cross-domain models):** Four of the five non-user models (`divisions`, `projects`, `vendors`, `project_vendors`) are deliberate read-only mirrors required because user-svc and the monolith share one Postgres schema (MICROSERVICE_EXTRACTION.md:48-50, 124-128). User-svc reads them for: (a) FK-target existence validation, (b) embedding vendor/project labels in user responses, (c) RBAC org-scope walks. The fifth, `milestone_vendors`, appears to be wider-than-intended extraction baggage — kept only so a side-import chain in `vendor_repository.py` doesn't break. **No `project_members` model** despite repository commentary suggesting one was previously imported — explicitly noted retired into `user_role_assignments` (`models/__init__.py:18-19`).

---

## 5. Alembic migrations

`alembic/` has two revisions plus `env.py`:

| FILENAME | REVISION | DOWN_REVISION | SUMMARY | TYPE |
|---|---|---|---|---|
| `alembic/versions/7e3fa9c21b4d_initial_user_service_schema.py` | `7e3fa9c21b4d` | `None` | Idempotently creates `users` (legacy integer-PK shape with `admin` boolean), `roles` (with JSON `permissions` column), `revoked_tokens`. Skips per-table if already present. | DDL |
| `alembic/versions/b9f4d27e1a83_user_drift_port_columns.py` | `b9f4d27e1a83` | `7e3fa9c21b4d` | Adds columns to `users` that monolith already had (vendor_id, division, division_other, deleted_at, deleted_by, previous_refresh_token_jti, previous_refresh_token_jti_valid_until) + indexes + FKs. Every step gated on inspector "is it absent?" → idempotent. | DDL |

- **Current head:** `b9f4d27e1a83` (single head).
- **Multi-head / orphans:** OBSERVED none. Linear two-revision chain.
- `downgrade()` is a no-op in BOTH (intentional — tables shared with monolith). `7e3fa9c21b4d:109-117`, `b9f4d27e1a83:155-157`.

### alembic env.py coordination with monolith
- `alembic/env.py:36` — `VERSION_TABLE = "alembic_version_user_svc"`. Passed at both `context.configure(..., version_table=VERSION_TABLE)` call sites (lines 48 and 68). This is the key shared-DB separator — the monolith uses the default `alembic_version`, user-svc uses `alembic_version_user_svc`. No collision.
- `env.py:26` reads `settings.DATABASE_URL` and overrides `alembic.ini`'s placeholder.
- `compare_type=True, compare_server_default=True` (lines 46-47, 67) → autogenerate sees column-type drift.

### Drift relative to current ORM
The initial migration declares `users.id` as **Integer auto-increment** (`7e3fa9c21b4d:42`) but the current ORM (`models/user.py:34-39`) declares it as `String(36)` UUID with a `uuid4` default. Doc 26 flipped this; INFERRED that on a fresh DB the initial migration creates the int-PK table and the column-type change happens (a) in the shared Postgres because the monolith owns it (`MICROSERVICE_EXTRACTION.md:96-107`), or (b) only ever runs against a DB the monolith has already migrated. **There is no migration in this repo that performs the int→UUID flip.** Same gap for `roles.permissions` JSON column (created in `7e3fa9c21b4d:69` but no migration drops it — current ORM has no `permissions` column on `RoleModel`). [UNVERIFIED] this is intentional reliance on monolith migrations covering the drift, but it's documented at `models/role.py:1-10`.

### Init_db also runs alembic
`session.py:51-92` runs `alembic upgrade head` as a subprocess on every boot when `MIGRATIONS_AUTORUN=True`. Gated by `MIGRATIONS_REQUIRED` for crash-on-fail vs log-and-continue.

---

## 6. Auth & RBAC implementation

### JWT
- Library: `python-jose[cryptography]==3.3.0` (requirements.txt:10) — `from jose import jwt` at `app/core/security.py:9`.
- Algorithm: `HS256` (`config.py:39`).
- Secret env: `SECRET_KEY` (`config.py:35`). Hash of secret surfaced via `/health` to confirm parity with monolith (`main.py:173`).
- Decode: `decode_access_token` at `app/core/security.py:89-107` — pure local decode, no introspection round-trip. The `/api/v3/users/introspect` endpoint is internal-only (`users/routes.py:54`), public, and does NOT call out — it's a self-introspection over local secret.
- Encode + jti: `create_access_token` at `app/core/security.py:46-86` — always stamps a `jti = uuid4().hex` (line 77) so any access token can be revoked.

**Cross-service model:** Local HS256 decode using shared SECRET_KEY. No HTTP introspection of monolith. Confirmed by MICROSERVICE_EXTRACTION.md:52-66.

### Permission check — canonical impl
`require_permission(permission)` at `app/core/middleware/rbac.py:42-60` — dependency factory. Reads `request.state.user_permissions` (a flat `Set[str]`). Plus:
- `require_any_permission(*permissions)` — `rbac.py:63-82`
- `require_authenticated()` — `rbac.py:85-92`
- `require_admin()` — `rbac.py:95-104`
- `require_project_permission(perm)` — `rbac.py:157-188` (doc 41 scope-aware)
- `require_org_permission(perm)` — `rbac.py:191-220` (doc 41 scope-aware)

The auth middleware (`app/core/middleware/auth.py:50-110`) hydrates `request.state.user_permissions` (flat set), `request.state.scoped_permissions` (`Dict[(kind, id), Set[str]]`), and `request.state.is_admin` per request via `RbacRepository.effective_permissions_for_user`, `.user_has_admin_role`, `.effective_permissions_by_scope` (auth.py:124-146).

### Revoked-token check
- Table: `revoked_tokens` — `models/revoked_token.py:26`.
- Check fires in auth middleware before user lookup: `_is_revoked(jti)` at `auth.py:112-122`. Goes through `RevokedTokenRepository.is_revoked` (file not opened).
- When revoked: middleware returns early WITHOUT populating user_id, so every downstream `require_*` returns 401 — graceful (`auth.py:73-76`).

### Compare to monolith (high level)
OBSERVED — both services share the same SECRET_KEY, sign + verify HS256 locally, and both read the `revoked_tokens` table for logout effect propagation (MICROSERVICE_EXTRACTION.md:60-66). Monolith has the same folder shape (`PMIS-OpenProject/app/api/v3/users/routes.py` exists). [UNVERIFIED] route-by-route diff against monolith — would require side-by-side reads. INFERRED: this service has at least these features the monolith may not (doc 41 scoped roles, doc 44 caller-vs-target gates, doc 46 round-10 admin-tier exclusion in user list); see drift discussion in §10.

### Login / logout / password-reset / OTP / register flows

Endpoint → service chain:

- **Login** (POST `/users/login` → `users/routes.py:94`):
  - Controller `UserController.login` (`controller.py:651`) → service `authenticate_user` (`services/authenticate.py`, not opened).
  - If 2FA needed: `is_2fa_required_for` (`services/two_factor.py`) → `begin_otp_challenge` returns `{ephemeral_token, channels_available}`. A sentinel `OtpCodeModel` row is also written so /send-otp can look up the user later (controller.py:760-771).
  - Otherwise mints access+refresh tokens; response decoded via `_exp_metadata` for expiry display (controller.py:704-727).
- **Send OTP** (POST `/users/login/send-otp` → `users/routes.py:117`):
  - Controller looks up sentinel OtpCodeModel by `hash_secret(ephemeral_token)` (`controller.py:763-771`).
  - Calls `send_or_resend_otp` (`services/two_factor.py`) → `get_notification_client(db).send(...)` → `MockNotificationClient` or `HttpNotificationClient` (`shared/notifications.py:237-256`).
- **Verify OTP** (POST `/users/login/verify-otp` → `users/routes.py:134`):
  - Service `verify_otp` (`services/two_factor.py`) — increments attempt_count, honours UNIVERSAL_OTP break-glass, mints real access+refresh on success.
- **Forgot password** (POST `/users/forgot-password` → `users/routes.py:150`):
  - Service `request_password_reset` (`services/password_reset.py`). Always 200 (anti-enumeration, `password_reset_token.py:15-19`).
- **Reset password** (POST `/users/reset-password` → `users/routes.py:165`):
  - Service `perform_password_reset` (`services/password_reset.py`). Single-use HMAC-hashed token / OTP.
- **Logout** (POST `/users/logout` → `users/routes.py:183`):
  - Controller `logout` (`controller.py:204-235`). Service `logout_user` inserts the current `jti` into `revoked_tokens` AND clears `users.refresh_token_jti` via `rotate_refresh_token(new_jti=None, grace_seconds=0)` (`user_repository.py:622-668`).
- **Refresh** (POST `/users/refresh` → `users/routes.py:74`):
  - Service `refresh_tokens` (`services/refresh.py`). Uses grace-window logic — `previous_refresh_token_jti` accepted for `REFRESH_TOKEN_GRACE_SECONDS=120` after rotation (`user_repository.py:658-664`, `models/user.py:60-66`).
- **Register**: OBSERVED **no self-service registration** endpoint. The only user creation path is `POST /api/v3/users/create` which requires `USERS_CREATE` permission (admin-only).

---

## 7. Cross-service HTTP calls

Grep `httpx|requests\.|aiohttp` found exactly one file: `app/shared/notifications.py`.

| FROM (file:line) | TO (URL pattern) | METHOD | PURPOSE | TIMEOUT / RETRY |
|---|---|---|---|---|
| `app/shared/notifications.py:178-186` (`HttpNotificationClient.send`) | `{NOTIFICATION_SERVICE_URL}/api/v1/notifications/dispatch` | POST | Dispatch OTP / password-reset notifications | connect=5s, read=15s, write=15s, pool=15s (`notifications.py:60-61, 178-184`). **No retry.** Failure marks the `notification_log` row `status='failed'` with the error message (lines 188-202). |

The HTTP-call dependency tree:
- Invoked from `services/two_factor.py` (OTP send flow) and `services/password_reset.py` (forgot-password flow) via `get_notification_client(db).send(...)`.
- Gated by `NOTIFICATION_CLIENT` (`config.py:150`). Default `"mock"` writes to `notification_log` only — no real HTTP. `"http"` (or "auto-detect" when `NOTIFICATION_SERVICE_URL` is set) routes via `HttpNotificationClient`.
- Audit row is written first as `status="queued"`, then patched to `sent`/`failed` (`notifications.py:132-234`).

**Does user-svc POST to notification-svc for password reset?** OBSERVED YES — both `password_reset_link` (email) and `password_reset_otp` (sms) template kinds flow through `HttpNotificationClient.send` (`notifications.py:51-54` defines the template-kind constants; `services/password_reset.py` uses them, not opened but consistent with the two_factor pattern).

No other outbound calls. No call to monolith — communication is via shared Postgres + shared SECRET_KEY only, per the design (MICROSERVICE_EXTRACTION.md:44-66).

---

## 8. Folder shape & nesting

### Tree of `app/` to depth 4

```
app/
├── __init__.py
├── main.py
├── api/
│   ├── __init__.py
│   ├── router.py
│   └── v3/
│       ├── __init__.py
│       ├── master_data/        (routes, schemas)
│       ├── permissions/        (routes, schemas)
│       ├── roles/              (controller, routes, schemas, permissions, services/)
│       ├── role_assignments/   (routes, schemas, services.py)
│       └── users/              (controller, routes, permissions, schemas.py, schemas/, services/)
├── core/
│   ├── base_controller.py
│   ├── config.py
│   ├── dependencies.py
│   ├── errors.py
│   ├── permissions.py
│   ├── rbac.py
│   ├── response.py
│   ├── security.py
│   └── middleware/
│       ├── auth.py
│       ├── logging.py
│       └── rbac.py
├── domain/
│   ├── resource_types/  (resource_type.py)
│   ├── roles/           (role.py)
│   ├── users/           (user.py, division.py)
│   └── vendors/         (vendor.py)
├── infrastructure/
│   └── db/
│       ├── session.py
│       ├── utc_datetime.py
│       ├── models/      (15 model files)
│       └── repositories/  (5 repositories)
└── shared/
    ├── code_generators.py
    ├── datetime.py
    ├── division_catalog.py
    ├── notifications.py
    ├── otp.py
    ├── pagination.py
    ├── service_result.py
    ├── utils.py
    └── ...
```

### File count + LOC under `app/`
- Python file count under `app/` (excluding `__pycache__`): **OBSERVED 98 .py files** (from Glob earlier — counting non-pycache results under `app/**/*.py`).
- Total LOC: [UNVERIFIED] — sampled files: `main.py` 198 lines, `routes.py` (users) 877, `controller.py` (users) 938, `role_assignments/routes.py` 748, `role_assignments/services.py` 460, `user_repository.py` 743, `config.py` 184. **INFERRED rough estimate: 12,000–18,000 LOC across `app/`.** Use repo tooling if a precise number is needed.

### DDD layout (domain / infrastructure / api / core / shared)
- `domain/`: thin — pure-Python entities only (`User`, `Role`, `Vendor`, `ResourceType`, `Division`). Plain `@dataclass`-style classes (e.g. `domain/users/user.py`).
- `infrastructure/db/`: models (SQLAlchemy) + repositories. Repositories return domain objects (e.g. `UserRepository._to_domain`, `user_repository.py:95-122`).
- `api/v3/<resource>/`: routes + controller + schemas + per-action service modules (`api/v3/users/services/{create.py, get.py, list.py, ...}`). The `users/` slice has its own `services/` package; `roles/` has `services/`; `role_assignments/` has a flat `services.py`. Slight inconsistency within the DDD tier.
- `core/`: cross-cutting infra — config, security, middleware (auth + rbac + logging), permissions registry, error types.
- `shared/`: utility helpers (datetime, OTP hashing, pagination, notifications HTTP client, code generators).

### Depth per top-level
- `app/api`: deepest path is `app/api/v3/users/services/two_factor.py` (5 levels under `app/`).
- `app/core`: max 2 levels (`core/middleware/auth.py`).
- `app/domain`: max 2 levels.
- `app/infrastructure`: max 3 levels (`infrastructure/db/models/user.py`).
- `app/shared`: 1 level.

### Divergence from target (notification-svc flat shape)
INFERRED (target shape described as `controllers/routes/schemas/services/middleware/db`):
- This repo's `api/v3/<resource>/{controller, routes, schemas, services/}` layout has the same primitives but they are nested *per-resource*, not flat across the app.
- `infrastructure/db/{models, repositories}` is the SQLAlchemy layer with a separate `domain/` for pure Python entities — notification-svc has only `db` (no separate domain).
- `core/` here is split between `core/*.py` and `core/middleware/*.py` — notification-svc has top-level `middleware/`.
- Net divergence: 2 extra layers (`api/v3/`, separate `domain/`) and per-resource grouping. Flattening would consolidate everything to ~6 flat dirs at the top.

---

## 9. Suspected legacy / dead / orphan code

### `*_old` / `*_legacy` / `*_v1` files
OBSERVED — no files matching those suffixes in `app/`. (The legacy/deprecated routes are stamped via the `_stamp(Deprecation: true)` helper rather than separate files.)

### Duplicate `src/` tree at repo root
**Major OBSERVED weirdness.** `C:\Programming\PMIS\PMIS-user-management\src\` contains a parallel near-copy of the whole project: `src/app/main.py`, `src/app/api/v3/users/routes.py`, `src/app/infrastructure/db/models/*.py` (incl. a **`project_member.py` that does NOT exist in the canonical `app/` tree**), and `src/alembic/`.
- INFERRED: this is an orphan / pre-extraction snapshot that was committed alongside but not used. The Dockerfile (`Dockerfile:28`) only COPYs `app/` and `alembic/`, never `src/`. `tests/__init__.py` lives outside `src/` and imports `app` (not `src.app`).
- The duplicate even has a now-retired `project_member.py` model (Glob `PMIS\PMIS-user-management\src\app\infrastructure\db\models\project_member.py`) consistent with the comment in `app/infrastructure/db/models/__init__.py:18-19` that project_members was unified into user_role_assignments — `src/` predates that change.
- This is the prime suspect for "broader-than-intended extraction baggage" the brief flagged.

### `app/api/v3/users/schemas/` vs `schemas.py`
There is both a `schemas.py` (`app/api/v3/users/schemas.py`, 120+ lines) AND a `schemas/` package (`app/api/v3/users/schemas/introspect.py`). Python's import rules favor the package over the module when both exist; INFERRED this works because `schemas/` only contains `introspect.py` and the package's `__init__.py` is empty (Glob didn't show one, [UNVERIFIED]). May produce subtle import shadowing — worth flattening.

### Cross-domain models — unreferenced by routes
- `MilestoneVendorModel` — referenced only in `models/__init__.py` and `repositories/vendor_repository.py`. INFERRED orphan, kept for an unused import side effect. Docstring on the model file itself (`models/milestone_vendor.py:1-9`) admits "user-mgmt never writes this table".
- `domain/vendors/vendor.py`, `domain/resource_types/resource_type.py` — these domain dataclasses exist. `resource_type.py` is imported by `users/schemas.py:32` (DIVISION_CHOICES). The vendors domain class — [UNVERIFIED] whether it's currently used by any route in this repo.

### Subtrees that may be unused
- `app/core/rbac.py` exists separately from `app/core/middleware/rbac.py`. The middleware/rbac.py file is the canonical decorator set. INFERRED `core/rbac.py` is a legacy enum module — `core/dependencies.py:1-8` docstring explicitly says "`get_current_user_role` was removed — the in-memory `Role` enum no longer drives RBAC". [UNVERIFIED] but very suggestive — `core/rbac.py` may be a dead enum file.
- `app/api/v3/roles/services/` — separate per-action service files for the deprecated `/roles` routes. Live (called by `/master/roles/*` delegators) but small surface.

---

## 10. Notable findings / risks

### A. Shape divergence (DDD → flat)
- Current shape: nested per-resource under `api/v3/<resource>/` with parallel `domain/` and `infrastructure/db/`.
- Target (notification-svc style): flat top-level dirs `controllers/routes/schemas/services/middleware/db`.
- Mechanical flatten plan (INFERRED):
  - `app/api/v3/<resource>/controller.py` → `app/controllers/<resource>.py`.
  - `app/api/v3/<resource>/routes.py` → `app/routes/<resource>.py`.
  - `app/api/v3/<resource>/schemas.py` → `app/schemas/<resource>.py`.
  - `app/api/v3/<resource>/services/*.py` → `app/services/<resource>/*.py` (or flatten further).
  - `app/core/middleware/*` → `app/middleware/*`.
  - `app/infrastructure/db/{models, repositories}` → `app/db/{models, repositories}`.
  - `app/domain/<entity>/<entity>.py` → fold into the model module or keep as `app/db/domain/<entity>.py`.
  - Update every relative-import path (many `....core.permissions`-style chains).
- Estimated touch surface: every Python file (98 files). Lots of import rewrites; behavior preservation is mechanical.

### B. Cross-domain models — reasoned take
INFERRED 4 of the 5 non-user models are deliberate (`divisions`, `projects`, `vendors`, `project_vendors`) and have explicit docstring justification — they exist because:
1. The architecture chose shared-Postgres-single-schema (MICROSERVICE_EXTRACTION.md:48-50). Doing so means SQLAlchemy needs class declarations for tables it joins to, even if read-only.
2. `users.vendor_id` and `user_role_assignments.{organization_id, project_id}` have actual FK constraints (`models/user.py:79-83`, `models/user_role_assignment.py:66-77`) reaching `vendors.id` / `projects.id`. Splitting the DB would break referential integrity.
3. The org-scoped RBAC walk (`role_assignments/services.py:143-150`) needs to traverse `project_vendors` to find which vendor owns a project — that's a cross-domain JOIN.

The fifth model — `milestone_vendors` — has no justification in routes. **Flag as orphan.**

If a future refactor splits the DB per service, the four "deliberate" cross-domain models become a real problem (no more FK-level integrity; user-svc would need HTTP round-trips or an event bus to validate vendor / project existence on writes). Keep that in mind before approving a per-service DB split.

### C. Drift vs. monolith (shared tables)
For tables shared with monolith, user-svc's ORM has the *current* schema (UUID PKs, doc-26 `String(36)` `users.id`), but its initial Alembic migration (`7e3fa9c21b4d`) declares the *legacy* schema (Integer PK + `admin` boolean + `roles.permissions` JSON column). The drift-port migration (`b9f4d27e1a83`) adds drift columns but does NOT flip `users.id` from Integer to UUID. INFERRED: the design relies on the monolith's alembic chain having already migrated the shared DB to the UUID shape; running user-svc against a *truly fresh* DB would produce a half-migrated table. The session.py `_run_alembic_upgrade` (lines 51-92) is unaware of this and would not detect the inconsistency.

**Concretely, this service expects the monolith to have run:** the int→UUID `users.id` migration, the `users.admin` column drop, the `roles.permissions` JSON drop, and the creation of `permissions`, `role_permissions`, `user_permissions`, `user_role_assignments`, `password_reset_tokens`, `otp_codes`, `notification_log`, `vendors`, `projects`, `project_vendors`, `divisions`, `milestone_vendors`. Many of those tables have **no migration in this repo at all** — `models/__init__.py` registers them on `Base.metadata` for SQLite-test create_all only.

[UNVERIFIED — needs a real DB] which of these tables an upstream prod migration actually created.

### D. UNIVERSAL_OTP backdoor
`UNIVERSAL_OTP_ENABLED=True` accepts a fixed code (`UNIVERSAL_OTP_CODE`, default `"000000"`) for any user's 2FA. The `main.py:45-51` lifespan logs a WARNING when enabled, but it's a real backdoor. Must be off in production — flagged in /health [UNVERIFIED — health endpoint code at main.py:166 doesn't surface this flag despite the config docstring (`config.py:172`) saying it does. Drift between docstring and code.].

### E. CORS wide-open
`allow_origins=["*"]` + `allow_credentials=True` (`main.py:84-90`). Browsers ignore credentials when origin is `*` but the combination is still a smell. The `CORS_ORIGINS` setting (`config.py:90`) is declared but never read.

### F. Duplicate `src/` tree
See §9. **Top finding for the brief's "wider-than-intended extraction" question.** Recommend deleting `src/` before refactor unless someone can identify a build / packaging reason it's there. It contains stale models (project_member.py) that no longer exist in `app/`.

### G. `users/schemas.py` vs `users/schemas/` directory
See §9. Module/package shadowing risk during refactor.

### H. `core/rbac.py` likely dead
`core/middleware/rbac.py` is the live decorator file; `core/rbac.py` (separate file) is INFERRED legacy from when an in-memory `Role` enum drove auth. Confirm by grep before removing.

### I. Decisions for human before porting
1. **Keep shared-Postgres assumption or split?** If split, the four "deliberate" cross-domain models need replacement (HTTP calls for validation, or eventing for replication).
2. **Delete `src/`?** Strong recommend, but confirm nothing references it (Dockerfile doesn't, tests don't).
3. **Delete `milestone_vendors` import chain?** Confirm `vendor_repository.py` doesn't actually need it (grep `MilestoneVendorModel.` for `.query`/`.filter` use).
4. **Migrations strategy:** keep no-op downgrades + idempotent-create pattern, or finally write a proper "user-svc owns these tables" set?
5. **`/api/v3/roles/*` and `/api/v3/permissions/*`:** drop the deprecated routes during refactor, or keep stamping `Deprecation:` headers?
6. **CORS:** narrow to `CORS_ORIGINS` setting? The setting is declared but ignored.
7. **`core/rbac.py`:** delete if confirmed dead.
8. **`schemas.py` vs `schemas/` package** in `users/`: pick one.

---

## MICROSERVICE_EXTRACTION.md summary (5-10 bullets)

(From `MICROSERVICE_EXTRACTION.md`, repo root.)

- Strangler-fig extraction of user + auth from the PMIS monolith into a standalone service on **port 8001**; monolith still runs on **8000** with its full user module intact and answering requests. (lines 71-86)
- **Shared Postgres, shared schema** — monolith has FKs from business tables to users; splitting DB would lose referential integrity (lines 47-51, 127-128).
- **Shared SECRET_KEY** — both services HS256-sign/verify locally; no `/verify` HTTP. (lines 53-57, 129)
- **Shared blacklist** — logout writes to `revoked_tokens`; monolith reads same table. Instant cross-service logout, no message bus. (lines 60-66, 130)
- **Self-contained service** — no shared Python package; JWT + password + RBAC + middleware all live inside this repo. (lines 35-40, 131)
- **Separate Alembic version tables** in same DB (`alembic_version` vs `alembic_version_user_svc`). (line 132)
- **Idempotent first migration** — table-create skipped when already present in shared DB. (lines 103-107).
- Phase plan: scaffold (done) → port module (done) → idempotent first migration (done) → tests (35 passing) → cross-service auth verified manually → containerize → push → deploy → 2-week burn-in → remove monolith's user module. (lines 90-121, 137-152)
- Decision rationale spelled out as a small table (lines 125-133): same DB, shared secret, separate version tables, no shared lib, strangler fig, per-service compose.
- Current state at the time of the doc: monolith on 8000, new service on 8001, 35/35 tests pass, cross-service flows manually verified end-to-end. (lines 137-144)
