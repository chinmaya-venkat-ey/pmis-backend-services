# pmis-user-management — Migration Log

Third service ported in Phase 3 per Q19/Q29. Owns the `users` Postgres schema. Source: `C:\Programming\PMIS\PMIS-user-management\` (the half-finished extract) plus the still-authoritative monolith pieces under `C:\Programming\PMIS\PMIS-OpenProject\app\`.

**Q33 applied**: bootstrap super-admin password sourced from `SUPERADMIN_BOOTSTRAP_PASSWORD` env var. Migration 002 skips bootstrap-user creation if the var is unset; in production the var is removed after the first migration run.

**Q14 applied**: `UNIVERSAL_OTP_ENABLED=true` is rejected at startup in production (see `app/main.py:lifespan`). Local dev can still enable it for FE testing.

**Q13 applied**: OTP storage moved from notification-svc to user-svc. notification-svc DISPATCHES; user-svc GENERATES, STORES (hashed), VERIFIES. The `otp_codes` table lives in the `users` schema.

**Q17 applied**: pre-Doc-26 int-id token compatibility branch dropped — those tokens are past their 7-day refresh window by deploy.

**Doc-44** caller-vs-target gates are applied at the service layer in `UserService._assert_caller_can_modify`. The first port uses the coarse rule (self / admin / same-vendor). The fine-grained tier comparison is a follow-up.

**Doc-46** vendor scoping is applied in `UserRepository.list_`: non-admin callers are filtered to their own `vendor_id` and admin-tier users (super_admin / admin roles via either legacy `user_roles` or scoped `user_role_assignments`) are excluded via `NOT EXISTS` subqueries.

**Doc-41** scoped RBAC: `users.user_role_assignments` carries `(organization_id, project_id)` with a `CHECK NOT (org IS NOT NULL AND project IS NOT NULL)` constraint plus a uniqueness constraint on `(user_id, role_id, org, project)`. RbacRepository's `effective_permissions_by_scope` returns a `Dict[(kind, id), Set[str]]` consumed by `require_project_permission` / `require_org_permission`.

**Doc-42b** grantable-roles matrix lives in `RoleGrantsService` as a static dict. The service surface returns the matrix; per-tier enforcement is in `RoleAssignmentService._assert_caller_can_grant` (super_admin can grant SUPER_ADMIN; admin can grant anything else; non-admin needs `rbac:assign` plus a vendor-scope match).

## Source

| Topic | Source (path:line) |
|---|---|
| User model | `C:\Programming\PMIS\PMIS-user-management\app\db\models\user.py` |
| Role model | `C:\Programming\PMIS\PMIS-user-management\app\db\models\role.py` |
| Permission model | `C:\Programming\PMIS\PMIS-user-management\app\db\models\permission.py` |
| user_role + role_permission + user_permission joins | `…\app\db\models\associations.py` |
| user_role_assignments (Doc-41) | `…\app\db\models\role_assignment.py` |
| OTP / password-reset / refresh-token models | `…\app\db\models\` |
| `code_generators.generate_user_code` | `C:\Programming\PMIS\PMIS-user-management\app\shared\code_generators.py` |
| OTP HMAC helpers (Q13 move) | `C:\Programming\PMIS\PMIS-notification-service\app\services\otp_service.py` |
| AuthService + JWT issuance | `C:\Programming\PMIS\PMIS-user-management\app\services\auth_service.py` |
| Refresh + grace-window rotation | `…\app\services\refresh_service.py` |
| RBAC repository / hydration | `…\app\repositories\rbac_repository.py` |
| Doc-41 require_project_permission / require_org_permission | `C:\Programming\PMIS\PMIS-OpenProject\app\api\v3\dependencies.py` |
| Doc-44 caller-vs-target gates | `C:\Programming\PMIS\PMIS-OpenProject\app\api\v3\users\services.py` |
| Doc-42b grant matrix | `C:\Programming\PMIS\PMIS-OpenProject\app\api\v3\role_grants\services.py` |

## Endpoint port table

All routes mounted under `/user/*`. Health probes (`/health`, `/ready`) at app root (outside the prefix, per `app/routes/__init__.py`).

### Auth (public allow-list)

| METHOD | NEW PATH | HANDLER | SOURCE | NOTES |
|---|---|---|---|---|
| POST | `/user/users/login` | `app/routes/auth_routes.py:login` | `PMIS-user-management/app/routes/auth_routes.py` | Returns either LoginResponse or `{requires_otp, ephemeral_token, channels_available}` |
| POST | `/user/users/login/send-otp` | `auth_routes.py:send_otp` | `…/two_factor_routes.py` | Rate-limited via `otp_codes.last_sent_at` |
| POST | `/user/users/login/verify-otp` | `auth_routes.py:verify_otp` | `…/two_factor_routes.py` | UNIVERSAL_OTP backdoor honored in dev only (Q14) |
| POST | `/user/users/refresh` | `auth_routes.py:refresh` | `…/auth_routes.py:refresh` | Grace window via `previous_refresh_token_jti_valid_until` |
| POST | `/user/users/logout` | `auth_routes.py:logout` | `…/auth_routes.py:logout` | Inserts jti into `revoked_tokens` |
| POST | `/user/users/introspect` | `auth_routes.py:introspect` | RFC-7662 introspection (legacy `…/introspect.py`) | Anonymous endpoint; reveals nothing on invalid token |
| POST | `/user/users/forgot-password` | `auth_routes.py:forgot_password` | `…/password_reset_routes.py:request_reset` | Anti-enum always 200 |
| POST | `/user/users/reset-password` | `auth_routes.py:reset_password` | `…/password_reset_routes.py:perform_reset` | Single-use; consumed_at set on verify |
| GET | `/user/users/me/get` | `auth_routes.py:get_me` | `…/users_routes.py:get_me` | Requires auth |

### Users

| METHOD | NEW PATH | RBAC |
|---|---|---|
| POST | `/user/users/create` | `users:create` |
| GET | `/user/users/list` | `users:read_all` |
| GET | `/user/users/check-login` | authenticated |
| GET | `/user/users/{user_id}/details` | `users:read` or self |
| PATCH | `/user/users/{user_id}/update` | `users:update` + Doc-44 |
| PATCH | `/user/users/{user_id}/password/update` | self or `users:update` |
| DELETE | `/user/users/{user_id}/delete` | `users:delete_all` + Doc-44 + last-super-admin lockout |
| POST | `/user/users/{user_id}/restore` | `users:delete_all` |
| GET | `/user/users/me/permissions/list` | authenticated |
| GET | `/user/users/{user_id}/permissions/list` | `permissions:read` |
| POST | `/user/users/{user_id}/permissions/{code}/grant` | `permissions:manage` |
| DELETE | `/user/users/{user_id}/permissions/{code}/revoke` | `permissions:manage` |
| GET | `/user/users/{user_id}/projects/list` | self or `projects:read_all` |

### Roles

| METHOD | NEW PATH | RBAC |
|---|---|---|
| GET | `/user/roles/list` | `roles:read` |
| POST | `/user/roles/create` | `roles:create` |
| GET | `/user/roles/{role_id}/details` | `roles:read` |
| PATCH | `/user/roles/{role_id}/update` | `roles:update` |
| DELETE | `/user/roles/{role_id}/delete` | `roles:delete` |
| GET | `/user/roles/{role_id}/permissions/list` | `permissions:read` |
| PUT | `/user/roles/{role_id}/permissions/replace` | `roles:update` |
| POST | `/user/roles/{role_id}/permissions/{code}/grant` | `roles:update` |
| DELETE | `/user/roles/{role_id}/permissions/{code}/revoke` | `roles:update` |

### Permissions

| METHOD | NEW PATH | RBAC |
|---|---|---|
| GET | `/user/permissions/list` | `permissions:read` |
| GET | `/user/permissions/by-module/list` | `permissions:read` |
| GET | `/user/permissions/{code}/details` | `permissions:read` |
| POST | `/user/permissions/create` | `permissions:manage` |
| PATCH | `/user/permissions/{code}/update` | `permissions:manage` |
| DELETE | `/user/permissions/{code}/delete` | `permissions:manage` |

### Role assignments (Doc-41 scoped grants)

| METHOD | NEW PATH | RBAC |
|---|---|---|
| GET | `/user/users/{user_id}/role-assignments/list` | authenticated |
| POST | `/user/users/{user_id}/role-assignments/create` | `rbac:assign` |
| DELETE | `/user/users/{user_id}/role-assignments/{aid}/delete` | `rbac:assign` |
| GET | `/user/projects/{project_uuid}/role-assignments/list` | `project_members:read` |
| POST | `/user/projects/{project_uuid}/role-assignments/create` | `rbac:assign` |
| DELETE | `/user/projects/{project_uuid}/role-assignments/{aid}/delete` | `rbac:assign` |
| GET | `/user/vendors/{vendor_id}/projects/list` | `projects:read_all` |
| GET | `/user/vendors/{vendor_id}/users/list` | `users:read_all` |

### Role grants (Doc-42b matrix)

| METHOD | NEW PATH | RBAC |
|---|---|---|
| GET | `/user/role-grants/{role_name}/matrix` | authenticated |

## Tables created (alembic `u1a000000001`)

11 tables under `users` schema:
1. `users` — UUID PK, soft-delete via deleted_at+deleted_by, refresh-token rotation columns (Doc-33+), 2FA toggle, logical FKs to `masters.vendors.id` (vendor_id) and `masters.divisions.code` (division).
2. `roles` — INT PK, unique name, `builtin` flag (informational + lock on delete).
3. `permissions` — `code` String(128) PK.
4. `user_roles` (legacy global-scope) — kept for AuthMiddleware's admin-tier scan.
5. `role_permissions` — composite PK.
6. `user_permissions` — composite PK, direct (additive) grants.
7. `user_role_assignments` (Doc-41) — INT PK, scope-exclusivity CHECK, unique (user, role, org, project).
8. `revoked_tokens` — jti PK; **cross-read by all other services**.
9. `password_reset_tokens` — single-use, HMAC-hashed.
10. `otp_codes` — single-use, HMAC-hashed (Q13).
11. `notification_log` — JSONB payload, status queued/sent/failed.

## Seed data (alembic `u1a000000002`)

- **All permission codes** from `app/core/permissions.py:ALL_PERMISSIONS` (USER + PROJECT + MASTERS domains, ~80 codes).
- **6 built-in roles**: `super_admin`, `admin`, `org_admin`, `project_admin`, `project_member`, `division_member`.
- **role_permissions grants** per tier (see migration source).
- **bootstrap super_admin user** (skipped if `SUPERADMIN_BOOTSTRAP_PASSWORD` env var is unset).

All inserts are `ON CONFLICT DO NOTHING` so the migration is idempotent.

## Behaviour preserved vs. monolith

- Vendor name kept on the wire as `vendor*` (NOT renamed to organizations; FE-only label change).
- HAL envelopes used on response shapes (`_type`, `_embedded`, `_links`) for consistency with FE conventions.
- Verb-suffix endpoint naming throughout (POST `/create`, DELETE `/{id}/delete`).
- Anti-enum on `/forgot-password` — always 200.
- 2FA-required login returns `requires_otp + ephemeral_token + channels_available` (status 200, special body).
- Refresh-token grace window via `previous_refresh_token_jti_valid_until` (Doc-33+).
- `is_builtin` informational only — never blocks delete on permissions/roles (per user direction; mirrors masters-svc convention).

## Behaviour diverged from monolith (deliberate)

- OTP storage moved from notification-svc in-memory dict → `users.otp_codes` (Q13).
- Pre-Doc-26 int-id token branch dropped (Q17).
- `UNIVERSAL_OTP_ENABLED=true` startup-errors in production (Q14).
- `notification_log` (user-svc audit of dispatch requests) is new — the monolith had no audit trail of OTP / password-reset dispatches.

## Tests

- `tests/integration/test_health.py` — `/health`, `/ready`, `/`.
- `tests/integration/test_rbac_gates.py` — public allow-list reach + 401/403 surfaces.
- `tests/unit/test_user_service.py` — Doc-44 gate + last-super-admin lockout.
- `tests/unit/test_role_service.py` — name conflict + builtin lock + SUPER_ADMIN-grant restriction.
- `tests/unit/test_role_assignment_schema.py` — Doc-41 scope exclusivity validator.
- `tests/unit/test_role_grants_service.py` — Doc-42b matrix tiers.
- `tests/test_cross_schema_drift.py` — **Q24 CANONICAL** drift-detector. Imports each peer service's `_cross_schema.py` and asserts column-type parity for every users.* mirror.

## Follow-ups (deferred)

- Doc-44 fine-grained tier comparison (current `_assert_caller_can_modify` is the coarse self / admin / same-vendor rule).
- HTTP notification client (`settings.notification_client = "http"`) — first port uses the `"mock"` driver. The HTTP driver is a one-screen aiohttp wrapper to add next.
- Real-Postgres integration tests (per Q28: tests can take a local dump from prod but never modify the server).
- Cron job to GC expired rows in `revoked_tokens`, `otp_codes`, `password_reset_tokens`.
