# PMIS-user-management — Architecture and API Reference

**Service**: pmis-user-service
**Port**: 8001
**Status**: Doc 37 part 2 parity — extracted from monolith and proxied via `UserServiceProxyMiddleware` from `PMIS-OpenProject` when `USER_SERVICE_PROXY_ENABLED=true` on the monolith.
**Last refresh**: 2026-05-06

This service owns user/auth/RBAC/notification-template behaviour. The monolith on port 8000 owns project-management (projects, M/A/T/S, comments, vendors, divisions, etc.). They share Postgres and the same `SECRET_KEY`.

---

## 1. Technology stack

| Component | Technology |
|-----------|-----------|
| Framework | FastAPI |
| Database | PostgreSQL (production) / SQLite (dev/tests) |
| ORM | SQLAlchemy 2.0 |
| Migrations | Alembic — gated by `MIGRATIONS_AUTORUN` (default false in shared-DB deploys; monolith owns alembic) |
| Authentication | JWT HS256, Argon2id password hashing |
| Validation | Pydantic 2 |
| Server | Uvicorn |

---

## 2. Architecture

This service mirrors the monolith's architecture for the slices it owns:

```
app/
├── main.py                            # FastAPI entry; mounts middleware + routers
├── core/
│   ├── config.py                      # Settings via pydantic-settings
│   ├── security.py                    # JWT + Argon2 helpers
│   ├── permissions.py                 # Permission registry + 4 seeded role bundles
│   ├── rbac.py                        # Permission enum (transitional bridge — see RBAC_GUIDE)
│   ├── errors.py                      # DomainError + http status mapper
│   ├── response.py / base_controller.py  # HAL+JSON envelope
│   ├── dependencies.py
│   └── middleware/
│       ├── auth.py                    # JWT decode + per-request permission hydration
│       ├── rbac.py                    # require_permission(code) FastAPI dependency
│       └── logging.py                 # X-Request-ID + duration
├── api/
│   ├── router.py                      # Mounts users / roles / permissions / master_data
│   └── v3/
│       ├── users/                     # /api/v3/users/* (login, refresh, logout, 2FA, reset, RBAC user-side)
│       ├── roles/                     # legacy /api/v3/roles/* (deprecated → /master/roles)
│       ├── permissions/               # legacy /api/v3/permissions/* (deprecated → /master/permissions)
│       └── master_data/               # /api/v3/master/{roles,permissions,notification_templates}
├── domain/                            # Pure business entities (User, Role, Vendor, ResourceType)
├── infrastructure/db/
│   ├── session.py                     # Engine, sessionmaker, init_db (alembic + RBAC seed + admin + notification templates seed)
│   ├── utc_datetime.py                # UTC-aware column type (doc 27)
│   ├── models/                        # 14 SQLAlchemy models (see DATABASE_SCHEMA.md)
│   └── repositories/                  # Slim subset: Rbac, Role, RevokedToken, User, Vendor
└── shared/
    ├── service_result.py              # ServiceResult<T>
    ├── notifications.py               # NotificationClient + Mock + Http + DB-backed renderer
    ├── otp.py                         # HMAC-SHA256 hashing + numeric/url-safe code gen
    ├── code_generators.py             # userCode / vendorCode slugs
    ├── pagination.py
    ├── datetime.py
    └── utils.py
```

### Request pipeline

```
HTTP request
   │
   ▼
LoggingMiddleware           — X-Request-ID stamping, request/response logs
   │
   ▼
AuthenticationMiddleware    — JWT decode + revoked-jti check
   │  if valid:
   │    request.state.user_id        = claim
   │    request.state.user_login     = claim
   │    request.state.user_permissions = RbacRepository.effective_permissions_for_user()
   │    request.state.is_admin       = membership in seeded "admin" role
   ▼
require_permission("module:action")  (FastAPI dependency)
   │  401 if user_id is None
   │  403 if code not in user_permissions
   ▼
Route → Service → Repository → Response (HAL+JSON)
```

> **Note**: when this service is fronted by the monolith's `UserServiceProxyMiddleware`, the monolith's middleware does NOT run for proxied paths. The monolith proxies the raw HTTP request here and this service is the authoritative auth gate.

---

## 3. Endpoint reference

### System

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | No | Root |
| GET | `/health` | No | Health check (status + service name + secret-key sha-256 prefix for cross-service ops verification) |
| GET | `/docs` | No | Swagger UI |

### Authentication

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| POST | `/api/v3/users/login` | Public | Single-stage when `users.two_factor_enabled=False`; returns `{requires_otp, ephemeral_token, channels_available}` when 2FA is required (doc 33 change 3) |
| POST | `/api/v3/users/login/send-otp` | Public (ephemeral_token) | Generate + dispatch OTP; cooldown via `OTP_RESEND_COOLDOWN_SECONDS` |
| POST | `/api/v3/users/login/verify-otp` | Public (ephemeral_token + code) | Verify + mint JWT pair |
| POST | `/api/v3/users/forgot-password` | Public | Anti-enumeration — always 200; sends URL token (email) or 6-digit OTP (sms) |
| POST | `/api/v3/users/reset-password` | Public (reset token) | Single-use token; clears refresh slots on success |
| POST | `/api/v3/users/refresh` | Public (refresh token) | Rotates the access token; 120s grace window for concurrent refresh races |
| POST | `/api/v3/users/introspect` | Public | RFC 7662 introspection (read-only metadata) |
| POST | `/api/v3/users/logout` | Authenticated | Revokes access JTI + clears all refresh slots |

### Users

| Method | Path | Permission | Notes |
|--------|------|-----------|-------|
| POST | `/api/v3/users/create` | `users:create` | login + email unique; `vendorId`, `division`, `phoneNumber`, `projectIds` required |
| GET | `/api/v3/users` | `users:read_all` | Paginated, `offset`/`pageSize` |
| GET | `/api/v3/users/{id}` | `users:read` | Path accepts UUID or `US-XXXX-YYMMDDHHMMSS` userCode |
| PATCH | `/api/v3/users/{id}` | `users:update` (self) / `users:update_all` | |
| PATCH | `/api/v3/users/{id}/password` | `users:update` | Self-service or admin-for-any |
| DELETE | `/api/v3/users/{id}` | `users:delete_all` | Soft-delete; last-admin lockout protection |
| POST | `/api/v3/users/{id}/restore` | `users:delete_all` | |
| GET | `/api/v3/users/me` | Authenticated | Current user record |
| GET | `/api/v3/users/me/permissions` | Authenticated | Effective permission set + `isAdmin` |

### RBAC user-side (assignment endpoints)

| Method | Path | Permission |
|--------|------|-----------|
| GET | `/api/v3/users/{id}/permissions` | `permissions:read` |
| POST | `/api/v3/users/{id}/permissions/{code}` | `rbac:assign` |
| DELETE | `/api/v3/users/{id}/permissions/{code}` | `rbac:assign` |
| GET | `/api/v3/users/{id}/roles` | `permissions:read` |
| POST | `/api/v3/users/{id}/roles/{role_id}` | `rbac:assign` |
| DELETE | `/api/v3/users/{id}/roles/{role_id}` | `rbac:assign` (last-admin lockout) |

### Master data — slim slice

This service hosts three master-data slices (catalog management for the data user-mgmt owns). Other slices (divisions, vendors, project_categories, etc.) live on the monolith.

| Method | Path | Permission |
|--------|------|-----------|
| GET / POST / PATCH / DELETE | `/api/v3/master/roles[/{id}]` | `master_data:view` / `master_data:manage` |
| GET / PUT | `/api/v3/master/roles/{id}/permissions` | (replace permission set) |
| POST / DELETE | `/api/v3/master/roles/{id}/permissions/{code}` | (grant / revoke single) |
| GET | `/api/v3/master/permissions` | flat catalog |
| GET | `/api/v3/master/permissions/by-module` | grouped by module prefix (doc 33 change 2) |
| POST / PATCH / DELETE | `/api/v3/master/permissions[/{code}]` | runtime permission CRUD |
| GET / POST / PATCH / DELETE | `/api/v3/master/notification_templates[/{id}]` | doc 36 — email + SMS template content |
| POST | `/api/v3/master/notification_templates/{id}/restore` | re-activate |

### Legacy paths (deprecated)

`/api/v3/roles/*` and `/api/v3/permissions/*` keep responding for back-compat but stamp `Deprecation: true` + `Link: <successor>; rel="successor-version"`. FE should use `/master/roles` and `/master/permissions` instead.

---

## 4. Response shape (HAL+JSON envelope)

Same as monolith. Single resource:

```json
{
  "data": {
    "_type": "User",
    "_links": { "self": { "href": "/api/v3/users/<uuid>", "title": "admin" } },
    "id": "8bd99f06-5f2a-424c-aaff-10ab163c3e42",
    ...
  },
  "status": 200
}
```

Errors:

```json
{
  "error": {
    "_type": "Error",
    "errorIdentifier": "validation_error",
    "message": "..."
  },
  "status": 422
}
```

Common status codes: 200 / 201 / 204 / 400 / 401 / 403 / 404 / 409 / 422 / 503 (proxy unreachable).

---

## 5. Configuration

`app/core/config.py` — `Settings` class (pydantic-settings, loads `.env`). Critical env vars below; full list in [DEPLOYMENT_AND_INTEGRATION.md](./DEPLOYMENT_AND_INTEGRATION.md).

```bash
# Critical — MUST match monolith
SECRET_KEY=<32+ chars; same value as monolith>
DATABASE_URL=postgresql://...   # shared with monolith

# Deployment
MIGRATIONS_AUTORUN=false        # default true; flip false in shared-DB deploys (monolith owns alembic)
MIGRATIONS_REQUIRED=true

# 2FA + password reset (doc 33 change 3)
REQUIRE_2FA=true
OTP_TTL_SECONDS=300
OTP_RESEND_COOLDOWN_SECONDS=60
OTP_MAX_ATTEMPTS=5
OTP_HASH_PEPPER=                # set per-deployment, falls back to SECRET_KEY
PASSWORD_RESET_TTL_SECONDS=3600

# Notification dispatch
NOTIFICATION_CLIENT=mock        # mock | http
NOTIFICATION_SERVICE_URL=
FRONTEND_BASE_URL=              # FE base used in password-reset links

# Bootstrap admin
BOOTSTRAP_ADMIN_LOGIN=admin
BOOTSTRAP_ADMIN_EMAIL=admin@example.com
BOOTSTRAP_ADMIN_PASSWORD=admin123

# Break-glass (do not enable in production)
UNIVERSAL_OTP_ENABLED=false
UNIVERSAL_OTP_CODE=000000
```

---

## 6. Operational notes

### init_db

Runs every boot. Idempotent. Order:

1. **Alembic** — `alembic upgrade head` if `MIGRATIONS_AUTORUN=true`. In shared-DB deploys this is `false` and the monolith owns migrations.
2. **RBAC seed** — `RbacRepository.sync_builtin_permissions()` upserts the canonical permission registry from `app/core/permissions.py` and creates the four built-in roles (admin, member, viewer, vendor) with their permission bundles.
3. **Bootstrap admin** — creates `admin/admin123` if missing. **Always** forces `two_factor_enabled=True` on every boot (doc 35 monolith parity). The universal-OTP break-glass (`UNIVERSAL_OTP_ENABLED=true` + `UNIVERSAL_OTP_CODE`) covers the case where notification dispatch is broken, so the admin can safely run with 2FA on. Assigns to the `admin` role.
4. **Notification templates** — seeds 6 built-in rows (`otp_login` / `password_reset_link` / `password_reset_otp` × email + sms) if missing. Subsequent edits via the master endpoint are preserved on re-seed.

### Health check

`GET /health` returns:
- `status`: `ok`
- `service`: `pmis-user-service`
- `version`
- `secret_key_sha256_prefix`: first 12 chars of `sha256(SECRET_KEY)` — operators verify monolith and user-mgmt are sharing the same key without exposing the secret.

### Running

```bash
# Dev
uvicorn app.main:app --reload --port 8001

# Prod
uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 4
```

---

## 7. Cross-service relationship

This service is one of three PMIS microservices:

| Port | Service | Owner |
|------|---------|-------|
| 8000 | PMIS-OpenProject (monolith) | Project-management (projects, M/A/T/S, vendors, divisions, etc.) + proxy to user-mgmt |
| 8001 | **PMIS-user-management** | User/auth/RBAC/notification-templates (this service) |
| 8002 | PMIS-notification-service | Stateless email/SMS dispatcher |

Both monolith and user-mgmt can call PMIS-notification-service to send actual emails/SMS — both write to `notification_log` for audit.

When `USER_SERVICE_PROXY_ENABLED=true` on the monolith, user-facing API calls hit the monolith on port 8000 and the monolith's `UserServiceProxyMiddleware` forwards them transparently to port 8001. FE doesn't change anything.

For the proxy contract + cutover plan, see `planned_changes/37` in the monolith repo.

---

## See also

- [AUTHENTICATION_AND_SECURITY.md](./AUTHENTICATION_AND_SECURITY.md) — JWT + 2FA + password reset details
- [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md) — tables this service owns / shares
- [DEPLOYMENT_AND_INTEGRATION.md](./DEPLOYMENT_AND_INTEGRATION.md) — env vars, migration coordination, deploy ordering
- [RBAC_GUIDE.md](./RBAC_GUIDE.md) — 4-role model + lockout protections + legacy artifacts
- [TESTING_AND_QUALITY.md](./TESTING_AND_QUALITY.md) — test infrastructure + smoke-test recipes
