# PMIS-notification-service Audit

Source root: `C:\Programming\PMIS\PMIS-notification-service\`. All paths below are relative to that root unless absolute. Citations are `path:line`. Tags: `OBSERVED:` = read directly from source, `INFERRED:` = derived from multiple observations, `[UNVERIFIED]` = not directly evidenced in this repo.

---

## 1. Tech & dependencies

OBSERVED — `requirements.txt`:

| Lib | Version | Line |
|---|---|---|
| fastapi | 0.115.0 | `requirements.txt:1` |
| uvicorn[standard] | 0.30.6 | `requirements.txt:2` |
| pydantic | 2.9.2 | `requirements.txt:3` |
| pydantic-settings | 2.5.2 | `requirements.txt:4` |
| python-dotenv | 1.0.1 | `requirements.txt:5` |
| email-validator | 2.2.0 | `requirements.txt:6` |
| httpx | 0.27.2 | `requirements.txt:7` (used for SendGrid + MSG91 HTTP) |
| twilio | 9.3.2 | `requirements.txt:8` |
| jinja2 | 3.1.4 | `requirements.txt:9` (declared; not imported by source — see Section 9) |
| python-multipart | 0.0.12 | `requirements.txt:10` |
| pytest | 8.3.3 | `requirements.txt:11` |
| pytest-asyncio | 0.24.0 | `requirements.txt:12` |
| sqlalchemy | 2.0.36 | `requirements.txt:14` (Doc 38) |
| alembic | 1.13.3 | `requirements.txt:15` (Doc 38) |
| psycopg2-binary | 2.9.10 | `requirements.txt:16` |
| PyJWT | 2.9.0 | `requirements.txt:17` |

OBSERVED — Python runtime is 3.11 (`Dockerfile:1`: `FROM python:3.11-slim`). Local cache directories indicate dev machines use 3.12 (`app\__pycache__\__init__.cpython-312.pyc`), so this is a dev/prod mismatch worth flagging.

Email: SMTP (stdlib `smtplib` — `app/services/email_service.py:1`) and SendGrid HTTP (`app/services/email_service.py:108-119`). **No `aiosmtplib` despite "async" framework.**
SMS: Twilio (`app/services/sms_service.py:34-41`), MSG91 (`app/services/sms_service.py:46-69`), mock (`app/services/sms_service.py:17-22`).

---

## 2. Entry point & startup

OBSERVED — `app/main.py`:

- App factory `create_app()` defined at `app/main.py:30`; module-level instance built at `app/main.py:87`.
- Title/version: "PIMS-NOTIFICATION", 1.1.0 (`app/main.py:32,42`).
- Lifespan handler (`app/main.py:18-27`) calls `init_db()` from `app/db/session.py` on startup; failures are logged but do NOT abort boot (`app/main.py:25-26`). So **the service WILL boot with a misconfigured DB** (auth + master endpoints will then return 401/500).
- Routers mounted:
  - `api_router` (`app/main.py:64`) — prefix `/api/v1` from `settings.api_prefix` (`app/routes/__init__.py:11`). Children: `health_router`, `email_router`, `sms_router`, `otp_router`, `dispatch_router`, `cron_router` (`app/routes/__init__.py:12-17`).
  - `master_data_router` (`app/main.py:66`) — prefix `/api/v3/master/notification_templates` (`app/routes/master_data_routes.py:32-35`).
- Root `GET /` returns service info (`app/main.py:68-75`).

Middleware order (FastAPI runs LAST-added first inbound, so dispatch order on request is reverse of registration):
1. `AuthMiddleware` added last (`app/main.py:61`) → runs FIRST on inbound.
2. `RequestContextMiddleware` (`app/main.py:58`) → assigns X-Request-ID, logs.
3. `CORSMiddleware` (`app/main.py:51-57`) → outermost; CORS preflight handled before auth.

INFERRED: This means CORS preflight passes through; the auth middleware sees the request after CORS short-circuits. But `RequestContextMiddleware` runs AFTER auth so `request.state.request_id` is NOT set during auth-middleware execution — this is a latent risk if auth ever wants to log a request id. **Needs verification.**

Exception handlers registered at `app/main.py:63` via `register_exception_handlers` (`app/middleware/error_handler.py:15-62`) — `StarletteHTTPException`, `RequestValidationError`, generic `Exception`.

**Env vars** (`app/config/settings.py`, all default-assigned at class level):

| Var | Type | Default | Line |
|---|---|---|---|
| `APP_NAME` | str | `PIMS-NOTIFICATION` | `app/config/settings.py:17` |
| `APP_ENV` | str | `development` | `:18` |
| `APP_HOST` | str | `0.0.0.0` | `:19` |
| `APP_PORT` | int | `8000` | `:20` |
| `APP_DEBUG` | bool | `True` | `:21` |
| `API_PREFIX` | str | `/api/v1` | `:22` |
| `LOG_LEVEL` | str | `INFO` | `:25` |
| `CORS_ORIGINS` | str | `*` | `:28` |
| `EMAIL_PROVIDER` | str | `smtp` | `:31` |
| `EMAIL_FROM_ADDRESS` | str | `no-reply@pims.example.com` | `:32` |
| `EMAIL_FROM_NAME` | str | `PIMS Notification` | `:33` |
| `SMTP_HOST` | str | `localhost` | `:36` |
| `SMTP_PORT` | int | `587` | `:37` |
| `SMTP_USERNAME` | str | `""` | `:38` |
| `SMTP_PASSWORD` | str | `""` | `:39` |
| `SMTP_USE_TLS` | bool | `True` | `:40` |
| `SENDGRID_API_KEY` | str | `""` | `:43` |
| `SMS_PROVIDER` | str | `mock` | `:46` |
| `SMS_FROM_NUMBER` | str | `""` | `:47` |
| `TWILIO_ACCOUNT_SID` | str | `""` | `:50` |
| `TWILIO_AUTH_TOKEN` | str | `""` | `:51` |
| `MSG91_API_KEY` | str | `""` | `:54` |
| `MSG91_SENDER_ID` | str | `PIMSAP` | `:55` |
| `MSG91_ROUTE` | str | `4` | `:56` |
| `OTP_LENGTH` | int | `6` | `:59` |
| `OTP_TTL_SECONDS` | int | `300` | `:60` |
| `OTP_MAX_ATTEMPTS` | int | `5` | `:61` |
| `OTP_RESEND_COOLDOWN_SECONDS` | int | `30` | `:62` |
| `DATABASE_URL` | str | `sqlite:///./notification_service.db` | `:68-71` |
| `MIGRATIONS_AUTORUN` | bool | `False` | `:72` |
| `MIGRATIONS_REQUIRED` | bool | `True` | `:73` |
| `SECRET_KEY` | str | placeholder string | `:77-80` (shared JWT key) |
| `ALGORITHM` | str | `HS256` | `:81` |
| `FRONTEND_BASE_URL` | str | `""` | `:85` |
| `CRON_SHARED_SECRET` | str | `""` | `:92` |
| `DEADLINE_WINDOW_DAYS` | int | `5` | `:96` |

**DB connection: YES.** `app/db/session.py:39` creates `engine` from `database_url`; `SessionLocal` factory at `:40`. `Base` declared at `:43`. Per-request session via `get_db()` (`:48-54`). The shared `SessionLocal` is also used directly by `AuthMiddleware` (`app/middleware/auth_middleware.py:80`) — NOT via FastAPI DI, to avoid coupling middleware to a route dep.

**Port:**
- `settings.app_port=8000` (`app/config/settings.py:20`).
- `.env.example` `APP_PORT=8000` (`.env.example:9`).
- `Dockerfile:24` `EXPOSE 8000` and `Dockerfile:29` runs uvicorn on `8000`.
- `docker-compose.yml:11` maps `${APP_PORT:-8000}:8000` (host:container).
- `deploy.sh:89` host-maps `-p 8002:8000`, healthcheck against `http://localhost:8002/api/v1/health` (`deploy.sh:101`).
- Cross-repo callers expect 8002 (e.g. `PMIS-OpenProject/tests/test_doc38_notification_service_proxy.py:41` and `PMIS-user-management/.env.bak-1778503524`).

INFERRED — **Resolved**: container listens on 8000; the host (and every external caller) reaches the service on **8002** via host-port mapping. The brief's "port 8002" is the external/public port; the in-process port is 8000. The README hints `APP_PORT` is the "public port" (`README.md:74`).

**Background tasks / schedulers:** None in-process. The "daily digest" runs only when an external DevOps cron POSTs `/api/v1/notifications/cron/daily-digest` (`app/routes/cron_routes.py:70-104`). The `lifespan` handler only seeds templates (`app/main.py:18-27`, `app/db/session.py:61-93`).

---

## 3. Route inventory (FULL)

All routes under `/api/v1` (from `settings.api_prefix`) unless otherwise noted. AUTH column: "public" = `_is_public_path` allow-listed in `app/middleware/auth_middleware.py:32-47`; "JWT+perm" = `require_permission(...)` dependency; "header secret" = `X-Cron-Secret`.

| METHOD | PATH | HANDLER (file:line) | AUTH | RBAC PERM | REQUEST SCHEMA | RESPONSE SCHEMA | DB TABLES | EXTERNAL | NOTES |
|---|---|---|---|---|---|---|---|---|---|
| GET | `/` | `root` `app/main.py:69` | public | — | — | inline dict | — | — | Service info |
| GET | `/api/v1/health` | `health` `app/routes/health_routes.py:8` | public | — | — | inline dict | — | — | Reports email/sms provider names |
| POST | `/api/v1/notifications/email/send` | `send_email` `app/routes/email_routes.py:21` | public | — | `EmailRequest` `app/schemas/email.py:6` | `EmailResponse` `app/schemas/email.py:26` | — | SMTP (`smtplib`) or SendGrid HTTP (`https://api.sendgrid.com/v3/mail/send`, `app/services/email_service.py:111`) | Legacy pre-Doc-38 dispatch path |
| POST | `/api/v1/notifications/sms/send` | `send_sms` `app/routes/sms_routes.py:21` | public | — | `SMSRequest` `app/schemas/sms.py:6` | `SMSResponse` `app/schemas/sms.py:20` | — | Twilio REST (`twilio.rest.Client`), MSG91 (`https://api.msg91.com/api/sendhttp.php`, `app/services/sms_service.py:64`), or mock | Legacy pre-Doc-38 dispatch path |
| POST | `/api/v1/notifications/otp/send` | `send_otp` `app/routes/otp_routes.py:26` | public | — | `OTPSendRequest` `app/schemas/otp.py:12` | `OTPSendResponse` `app/schemas/otp.py:33` | — | Indirect via Email or SMS service | OTP stored **in-process memory** (`app/services/otp_service.py:36`) |
| POST | `/api/v1/notifications/otp/verify` | `verify_otp` `app/routes/otp_routes.py:39` | public | — | `OTPVerifyRequest` `app/schemas/otp.py:42` | `OTPVerifyResponse` `app/schemas/otp.py:48` | — | — | In-memory store — single-process only |
| POST | `/api/v1/notifications/dispatch` | `dispatch_templated` `app/routes/dispatch_routes.py:38` | public | — | `DispatchRequest` `app/schemas/dispatch.py:15` | `DispatchResponse` `app/schemas/dispatch.py:35` | `notification_templates` (READ) | Email or SMS provider (above) | Doc 38 phase 2 — single round trip for callers |
| POST | `/api/v1/notifications/cron/daily-digest` | `daily_digest` `app/routes/cron_routes.py:85` | header secret | — (gated by `X-Cron-Secret`) | `DigestRequest` `app/schemas/digest.py:21` | `DigestResponse` `app/schemas/digest.py:10` | `projects`, `milestones`, `activities`, `users`, `roles`, `user_role_assignments`, `project_vendors`, `notification_templates` (all READ except templates) | Email provider per user | DevOps-driven cron; 503 if `CRON_SHARED_SECRET` unset |
| GET | `/api/v3/master/notification_templates` | `list_templates` `app/routes/master_data_routes.py:83` | JWT+perm | `master_data:view` | query `include_inactive: bool` | `_ok(_collection(...))` | `notification_templates` (READ) | — | Returns collection envelope |
| GET | `/api/v3/master/notification_templates/{template_id}` | `get_template` `app/routes/master_data_routes.py:98` | JWT+perm | `master_data:view` | path | `_ok(_to_response(row))` | `notification_templates` (READ) | — | 404 if missing |
| POST | `/api/v3/master/notification_templates/create` | `create_template` `app/routes/master_data_routes.py:121` | JWT+perm | `master_data:manage` | `NotificationTemplateCreateRequest` `app/schemas/notification_template.py:67` | `_ok(...)` | `notification_templates` (R/W) | — | 409 on (kind,channel) clash |
| PATCH | `/api/v3/master/notification_templates/{template_id}` | `update_template` `app/routes/master_data_routes.py:160` | JWT+perm | `master_data:manage` | `NotificationTemplateUpdateRequest` `app/schemas/notification_template.py:108` | `_ok(...)` | `notification_templates` (R/W) | — | Validates placeholder set against allow-list |
| DELETE | `/api/v3/master/notification_templates/{template_id}` | `delete_template` `app/routes/master_data_routes.py:235` | JWT+perm | `master_data:manage` | path | `_ok(...)` | `notification_templates` (R/W) | — | Soft-delete: sets `active=False` |
| POST | `/api/v3/master/notification_templates/{template_id}/restore` | `restore_template` `app/routes/master_data_routes.py:261` | JWT+perm | `master_data:manage` | path | `_ok(...)` | `notification_templates` (R/W) | — | Re-activates; rejects clash |

**Route count: 14** (13 application routes + 1 root).

---

## 4. DB usage

**"Is it stateless?" — NO.** OBSERVED `app/db/session.py:39-40` creates a real SQLAlchemy `engine` + `SessionLocal`; the lifespan handler calls `init_db()` at startup (`app/main.py:22-23`). The "stateless dispatcher" description in the brief reflects the **pre-Doc-38** state explicitly mentioned in three source files:
- `app/core/auth.py:7-10`: *"Pre-doc-38 this service had no auth — it was a stateless dispatcher…"*
- `app/db/session.py:3-6`: *"Pre-doc-38 this service was stateless. Doc 38 introduces SQLAlchemy session management…"*
- `planned_changes/1. Notification templates moved to this service.md:5`: *"This service was a stateless dispatcher pre-doc-38."*

After Doc 38 the service:
- **Owns** `notification_templates` (writes from `/api/v3/master/...`).
- **Read-only mirrors** seven shared tables for the daily-digest cron + the auth middleware.

| TABLE | OWNED BY THIS SVC? | R/W | PURPOSE (file:line) |
|---|---|---|---|
| `notification_templates` | YES (Doc 38 moved ownership from user-service) | R/W | Catalog of email/SMS templates. Model at `app/db/models/notification_template.py:23`. Writes via `NotificationTemplateRepository` `app/db/repositories/notification_template_repository.py:38-46` from master_data_routes. Reads via `template_service._lookup_template` `app/services/template_service.py:108-118`. |
| `role_permissions` | NO (user-service is authoritative) | READ | RBAC lookup in `app/db/repositories/rbac_read_repository.py:32-43` — `SELECT permission_code FROM role_permissions rp JOIN user_roles ur …` per request to hydrate `request.state.user_permissions`. |
| `user_roles` | NO | READ | Same query as above (`:35`) and `is_admin` check `:50-53`. **Note column name mismatch — see Section 10.** |
| `user_permissions` | NO | READ | Direct user grants UNION in `effective_permissions_for_user` (`:39-40`). |
| `roles` | NO | READ | `is_admin` lookup `app/db/repositories/rbac_read_repository.py:51-53`; daily-digest joins via `RoleModel` `app/db/models/role.py`. |
| `revoked_tokens` | NO (user-service writes) | READ | JTI blacklist check `app/db/repositories/rbac_read_repository.py:60-62`; called on every authed request `app/middleware/auth_middleware.py:84`. |
| `users` | NO (user-service writes) | READ | Daily-digest recipient resolution. Model `app/db/models/user.py:11-20`. |
| `projects` | NO (monolith / project-mgmt writes) | READ | Daily-digest project lookup. Model `app/db/models/project.py`. |
| `milestones` | NO | READ | Daily-digest item source. Model `app/db/models/milestone.py`. |
| `activities` | NO | READ | Daily-digest item source. Model `app/db/models/activity.py`. |
| `user_role_assignments` | NO | READ | Daily-digest recipient scope resolution. Model `app/db/models/user_role_assignment.py`. |
| `project_vendors` | NO | READ | Map projects to owning vendors so org-admins on those vendors get the digest. Model `app/db/models/project_vendor.py`. |

**`rbac_read_repository.py`** (`app/db/repositories/rbac_read_repository.py`):
- File header (`:1-12`) explicitly says: *"User-service is the AUTHORITATIVE writer for `users`, `roles`, `role_permissions`, `user_roles`, `user_permissions`. This service only reads them — to gate `/api/v3/master/*` endpoints with the permission a JWT-authenticated caller actually holds."*
- Three methods, all `text()` raw SQL against the shared Postgres:
  - `effective_permissions_for_user(user_id)` (`:25-43`) — UNION of role-derived + direct grants. **Note**: raw SQL JOINs `user_roles` to `role_permissions` on `role_id` but the project's full schema may name this table differently in user-service. **Needs verification** against user-service models.
  - `is_admin(user_id)` (`:45-54`) — checks for role named `admin`.
  - `is_revoked(jti)` (`:56-63`) — JTI blacklist via `revoked_tokens`.

**Why it reads RBAC**: `AuthMiddleware` (`app/middleware/auth_middleware.py:79-92`) decodes the JWT, then calls `RbacReadRepository.effective_permissions_for_user(user_id)` and `is_admin(user_id)` to populate `request.state.user_permissions` and `request.state.is_admin`. The `require_permission(code)` dependency (`app/middleware/auth_middleware.py:109-132`) then gates each `/api/v3/master/...` route.

---

## 5. Alembic migrations

OBSERVED — **No alembic configuration in this repo.** `alembic` is declared in `requirements.txt:15` but glob found no `alembic.ini`, no `alembic/` dir, no `migrations/` dir. `app/db/session.py:8-11` (file header) and `:74` (in-code comment) state explicitly:

> *"In shared-DB deploys the monolith owns alembic; this service runs with `MIGRATIONS_AUTORUN=false` and relies on the schema being at head when it boots."*

For local SQLite, `init_db()` calls `Base.metadata.create_all(engine)` (`app/db/session.py:75-80`) so tests don't need migrations. **`MIGRATIONS_AUTORUN` and `MIGRATIONS_REQUIRED` settings exist (`app/config/settings.py:72-73`) but are not referenced anywhere in source — dead toggles.** Needs verification but Grep on the codebase only finds them in `settings.py`.

---

## 6. Auth & RBAC implementation

**JWT decode** — `app/core/auth.py:36-56`:
- Library: `PyJWT` (`import jwt` at `:17`).
- Algorithm: `HS256` from `settings.algorithm` (`:44`).
- Secret: `settings.secret_key` (`:43`) — explicitly declared "**identical to monolith and user-service**" in `app/config/settings.py:75-80`. Shared `SECRET_KEY` model.
- Failure mode: returns `None` on `ExpiredSignatureError` / `InvalidTokenError` / any exception. Never raises. Middleware translates `None` claims to anonymous request state.
- Expected claims: `{sub, user_id, email, jti, iat, exp}` (`app/core/auth.py:4-5`).

**Permission constants** — `app/core/permissions.py:15-16`:
- `MASTER_DATA_VIEW = "master_data:view"`
- `MASTER_DATA_MANAGE = "master_data:manage"`
- File header (`:8-11`) warns these must be kept in sync with `PMIS-user-management/app/core/permissions.py` and `PMIS-OpenProject/app/core/permissions.py`. **Cross-repo coupling without a shared package — refactor risk.**

**Auth middleware** — `app/middleware/auth_middleware.py:50-98`:
- Subclass of `BaseHTTPMiddleware`.
- Always resets `request.state` to anonymous defaults (`:52-58`).
- Bypasses everything under `_PUBLIC_PREFIXES` (`:32-40`): `/api/v1/notifications`, `/api/v1/health`, `/health`, `/docs`, `/redoc`, `/openapi.json`, `/`. **So all legacy dispatch endpoints AND the dispatch and cron endpoints are NOT JWT-checked.** Dispatch security relies on network trust boundary; cron security relies on `X-Cron-Secret` header check inside the handler.
- For non-public paths: extracts Bearer token (`:65-68`), decodes (`:69`), checks `user_id` is a UUID-shape string (`:73-77` — silently anonymises pre-Doc-26 integer-id JWTs), opens a `SessionLocal()` directly (`:80`), checks `is_revoked(jti)` (`:84`), hydrates `user_id / user_login / user_email / token_jti / user_permissions / is_admin` (`:87-92`).
- DB lookup failures are caught and the request continues anonymous (`:93-97`) — `require_permission` will then 401.

**`require_permission(code)` dependency** — `app/middleware/auth_middleware.py:109-132`:
- Returns a `Depends(_checker)`. The checker reads `request.state.user_id` (401 if None) and `request.state.user_permissions` (403 if code missing).
- Mounted on each `/api/v3/master/...` route via `dependencies=[require_permission(...)]` (e.g. `app/routes/master_data_routes.py:81,96,119,158,233,259`).

---

## 7. Inbound / outbound calls

### Inbound (other repos calling THIS service)

Best-effort grep across `C:\Programming\PMIS\`:

| Caller (file:line) | Endpoint | Purpose |
|---|---|---|
| `PMIS-OpenProject/app/shared/notifications.py:339` | `POST /api/v1/notifications/email/send` | Monolith `HttpNotificationClient.send_email` — fallback path (pre-Doc-38 phase 2 contract) |
| `PMIS-OpenProject/app/shared/notifications.py:354` | `POST /api/v1/notifications/sms/send` | Monolith `HttpNotificationClient.send_sms` |
| `PMIS-OpenProject/app/shared/notification_service_client.py:126` | `/api/v3/master/notification_templates` | Monolith proxy of master-data calls — forwards FE to this service so the FE only knows port 8000 |
| `PMIS-user-management/app/shared/notifications.py:168` | `POST /api/v1/notifications/dispatch` | user-service single-call dispatch (Doc 38 phase 2 — replaces local rendering) |

OBSERVED — `PMIS-OpenProject/app/core/config.py:447` mentions `/api/v3/master/notification_templates/*` is forwarded via the monolith's `NotificationServiceProxyMiddleware` so the FE doesn't need to know about port 8002 directly. INFERRED: monolith on `:8000` proxies → notification-service on `:8002` for the master surface; the legacy dispatch endpoints are called directly from user-service / monolith over the internal network.

### Outbound (THIS service to providers / other services)

| FROM (file:line) | TO | PURPOSE |
|---|---|---|
| `app/services/email_service.py:49,57` | SMTP `settings.smtp_host:settings.smtp_port` (TLS optional) | Send email (default Gmail per `.env.example:26-27`) |
| `app/services/email_service.py:111` | `https://api.sendgrid.com/v3/mail/send` (HTTPS POST) | SendGrid email |
| `app/services/sms_service.py:36` | Twilio REST (`twilio.rest.Client.messages.create`) | Twilio SMS |
| `app/services/sms_service.py:64` | `https://api.msg91.com/api/sendhttp.php` (HTTPS GET) | MSG91 SMS |
| `app/db/session.py:39` | Postgres (or SQLite dev) via SQLAlchemy `database_url` | Template R/W + RBAC + digest reads |

**No outbound HTTP to other PMIS services.** This service is a leaf in the call graph.

---

## 8. Folder shape (REFERENCE for refactor)

### Tree of `app/` to depth 3 (Python source only, `__pycache__` excluded)

```
app/
  __init__.py                        # empty package marker (1 line)
  main.py                            # FastAPI factory + lifespan + middleware wiring
  config/
    __init__.py                      # re-exports `settings`
    settings.py                      # Pydantic Settings (all env vars in one class)
  controllers/                       # thin orchestrators between schemas and services
    __init__.py
    email_controller.py
    otp_controller.py
    sms_controller.py
    (no controllers for dispatch / cron / master_data — those route handlers
     call services directly. INCONSISTENT — see Section 10.)
  core/                              # cross-cutting primitives
    __init__.py
    auth.py                          # JWT decode helper
    permissions.py                   # permission-code constants
  db/
    __init__.py
    session.py                       # engine, SessionLocal, Base, get_db, init_db, seed
    models/
      __init__.py                    # re-exports all models
      activity.py
      milestone.py
      notification_template.py       # OWNED
      project.py
      project_vendor.py
      role.py
      user.py
      user_role_assignment.py
    repositories/
      __init__.py
      notification_template_repository.py
      rbac_read_repository.py        # read-only RBAC via raw SQL
  middleware/
    __init__.py
    auth_middleware.py               # AuthMiddleware + require_permission dep
    error_handler.py                 # register_exception_handlers
    request_context.py               # X-Request-ID + timing
  routes/                            # FastAPI router definitions only
    __init__.py                      # builds api_router with prefix /api/v1
    cron_routes.py
    dispatch_routes.py
    email_routes.py
    health_routes.py
    master_data_routes.py            # /api/v3/master/notification_templates/*
    otp_routes.py
    sms_routes.py
  schemas/                           # Pydantic request/response shapes
    __init__.py
    digest.py
    dispatch.py
    email.py
    notification_template.py         # also hosts placeholder-validation logic
    otp.py
    sms.py
  services/                          # business logic + provider abstractions
    __init__.py
    digest_service.py                # daily-digest scan + aggregation
    email_service.py                 # SMTPProvider + SendGridProvider + EmailService
    otp_service.py                   # OTPService (in-memory store)
    sms_service.py                   # MockSMSProvider + TwilioSMSProvider + Msg91SMSProvider + SMSService
    template_service.py              # DB lookup + render_email / render_sms
  utilities/
    __init__.py
    logger.py                        # configure_logging, get_logger
    timezones.py                     # iso_ist + IST constant
```

File counts (Python files, excluding `__init__.py` and `__pycache__`):
- `app/`: 1 (main.py)
- `config/`: 1
- `controllers/`: 3
- `core/`: 2
- `db/`: 1 (session.py)
- `db/models/`: 8
- `db/repositories/`: 2
- `middleware/`: 3
- `routes/`: 7
- `schemas/`: 6
- `services/`: 5
- `utilities/`: 2
- **Total: 41 Python files** (plus 12 `__init__.py`).

### Purpose of each top-level dir (one line each)

- `config/` — Pydantic `Settings` class; single source for env vars. Re-exported `settings` singleton via `@lru_cache`.
- `controllers/` — adapt Pydantic request → service call → Pydantic response (no business logic). Only present for legacy email/sms/otp endpoints — Doc-38 routes bypass this layer.
- `core/` — cross-cutting primitives that are framework-agnostic: JWT helpers, permission constants.
- `db/` — SQLAlchemy engine, session factory, declarative Base, startup seeding.
- `db/models/` — ORM classes; one file per table, mix of owned (`notification_template`) and read-only mirrors of monolith tables.
- `db/repositories/` — query-only classes that take a `Session` in `__init__`. Two repos: one ORM-based (`notification_template_repository`), one raw-SQL `text()` (`rbac_read_repository`).
- `middleware/` — Starlette `BaseHTTPMiddleware` subclasses + exception-handler registry.
- `routes/` — FastAPI `APIRouter` declarations and route handler functions. Calls into controllers OR (post-Doc-38) directly into services.
- `schemas/` — Pydantic v2 request/response models. `notification_template.py` also hosts the placeholder validation function — slight separation-of-concerns leak.
- `services/` — business logic + external-provider abstractions (SMTP, SendGrid, Twilio, MSG91, mock). Provider strategy pattern: `EmailService._build_provider`, `SMSService._build_provider`.
- `utilities/` — helpers that don't belong elsewhere: logging config, IST timestamp formatting.

### One example flow — OTP send (`POST /api/v1/notifications/otp/send`)

1. Request hits `AuthMiddleware` (`app/middleware/auth_middleware.py:51`) → path is under `/api/v1/notifications`, so `_is_public_path` returns True (`:43-47`) → middleware bypasses auth and calls next.
2. `RequestContextMiddleware` (`app/middleware/request_context.py:15-31`) assigns request_id, logs request.
3. Routing reaches `send_otp` handler (`app/routes/otp_routes.py:26-30`).
4. FastAPI builds the dependency tree: `get_otp_service()` (`app/services/otp_service.py:144-148`) singleton, wrapped by `get_controller` (`app/routes/otp_routes.py:15-16`) → `OTPController(service)`.
5. Pydantic validates body into `OTPSendRequest` (`app/schemas/otp.py:12-30`), which also runs E.164 / EmailStr validation on the destination.
6. `OTPController.send(payload)` (`app/controllers/otp_controller.py:14-20`) unpacks the request and calls `service.send_otp(channel, destination, purpose)`.
7. `OTPService.send_otp` (`app/services/otp_service.py:48-95`): generates code via `secrets.randbelow`, stores in in-process dict under a thread lock, then calls `get_sms_service().send(...)` (`:75`) or `get_email_service().send(...)` (`:77-86`).
8. `EmailService.send` (`app/services/email_service.py:138-159`) dispatches to the configured provider (`_SMTPProvider` or `_SendGridProvider`). On `EmailProviderError` it raises `HTTPException(502)`.
9. Result dict is wrapped back into `OTPSendResponse` (`app/controllers/otp_controller.py:20`) — included `request_id` is the OTP record id, NOT the X-Request-ID.

### Conventions

- **Routes** do nothing but binding, validation, dependency injection, and shaping the response envelope. They never call models / repos directly EXCEPT in `master_data_routes.py` (which uses repos inline) and `dispatch_routes.py` / `cron_routes.py` (which call services directly).
- **Controllers** exist only for legacy email/SMS/OTP. They are extremely thin (5-15 lines each) and only re-pack the Pydantic model into kwargs for the service. **Likely redundant** — see Section 10.
- **Services** hold business logic, talk to providers, and own the public API of the module (e.g. `EmailService.send`). They expose a singleton accessor `get_<x>_service()` for DI.
- **Repositories** wrap a `Session` and expose query methods. Only used for DB-backed flows (notification_template, RBAC).
- **Schemas** are pure Pydantic — no logic except validators. The placeholder allow-list in `app/schemas/notification_template.py:18-32` is the one exception (validation logic that's also used outside the schema, by master_data routes' update handler at `:191-201`).
- **Models** are SQLAlchemy 2.0 declarative; relationships are minimal (none defined; everything uses explicit `id` keys for the digest joins).

### DI / DB session / config patterns

- **DI**: FastAPI `Depends(...)` everywhere. Service singletons use module-level `_email_service: Optional[...] = None` + `get_email_service()` (`app/services/email_service.py:162-169`). NOT a DI container — manual lazy init.
- **DB session**: per-request via `Depends(get_db)` (`app/db/session.py:48-54`). Middleware uses `SessionLocal()` directly + `try/finally` close (`app/middleware/auth_middleware.py:80-97`) because middleware can't use FastAPI deps.
- **Config**: `pydantic-settings` `BaseSettings` with `env_file=".env"`, `case_sensitive=False`, `extra="ignore"` (`app/config/settings.py:9-14`). Settings cached with `@lru_cache` (`:109-111`). Re-exported as `settings` singleton (`app/config/__init__.py:1-3`). Code uses both `from app.config import settings` and a defensive `_setting("foo", "FOO", default=...)` helper that the auth/template modules use (`app/core/auth.py:27-33`, `app/services/template_service.py:43-50`) to handle "legacy lower-case names" — INFERRED: vestigial from a prior naming convention.

---

## 9. Suspected legacy / dead code

- **`deploy.sh-bak`** (root) — old deploy script backup. Not referenced.
- **`tests/` is shipped** but no CI hook in this repo. `pytest` is in requirements; tests cover health, email, SMS, OTP, daily digest, dispatch, notification_templates (`tests/test_*.py`).
- **`jinja2==3.1.4`** in `requirements.txt:9` — `grep` of `app/` shows no `import jinja2` and no `Template(` usage. INFERRED: vestigial dependency from a prior templating approach (Doc 38 uses `str.format_map` instead — `app/services/template_service.py:96-105`). **Candidate for removal.**
- **`MIGRATIONS_AUTORUN` and `MIGRATIONS_REQUIRED`** settings (`app/config/settings.py:72-73`) — declared and documented but no code references them outside `settings.py`. Dead toggles.
- **`controllers/`** for `email`, `sms`, `otp` — extremely thin (single-method, no logic). The Doc-38 routes (`dispatch_routes.py`, `cron_routes.py`, `master_data_routes.py`) skip this layer entirely. Either the legacy controllers should be inlined into the route handlers, or the new routes should follow the same convention. **Inconsistent layering.**
- **`schemas/notification_template.py`** hosts the `validate_placeholder_set` helper and `ALLOWED_PLACEHOLDERS` map (`:18-60`). Master-data update route (`app/routes/master_data_routes.py:191-201`) re-imports the helper directly. This logic would more naturally live in `services/template_service.py` or `core/`.
- **`AuthMiddleware` always opens a DB session for any non-public path with a bearer token** (`app/middleware/auth_middleware.py:80-97`) — even when the route doesn't need permissions. Cost is one query per authenticated request that may never be checked. **Performance note, not dead code.**
- **`PMIS_Notification_Service.postman_collection.json`** present at root — manual-test collection, not used by code.

### `planned_changes/` contents (one line each)

- `planned_changes/0. TEMPLATE — Planned-change document.md` — template doc for new planned-changes files (DO NOT IMPLEMENT marker at top).
- `planned_changes/1. Notification templates moved to this service.md` — Doc 38 phase 1: adds DB, takes ownership of `notification_templates`, JWT auth on `/api/v3/master/*`.
- `planned_changes/2. Templated dispatch endpoint for internal callers.md` — Doc 38 phase 2: adds `POST /api/v1/notifications/dispatch` so user-service stops rendering locally.
- `planned_changes/3. Daily deadline-digest cron endpoint.md` — Adds `POST /api/v1/notifications/cron/daily-digest` gated by `X-Cron-Secret`; status "SHIPPED-PENDING-DEPLOY" — code is in `dev` but DevOps host cron not yet wired (`planned_changes/3...:4-5`).

INFERRED: all three numbered planned-change docs correspond to features already MERGED into the code (DB session exists; `/dispatch` exists; `/cron/daily-digest` exists). The directory is a historical record, not a TODO queue.

---

## 10. Notable findings / risks

### Stateless vs DB-using — resolution

The brief says "stateless, no DB". That description is **stale by 1-2 doc cycles**. The current service:

1. Has a SQLAlchemy engine + session factory (`app/db/session.py:39-40`).
2. Owns the `notification_templates` table (`app/db/models/notification_template.py:23`; CRUD via `/api/v3/master/notification_templates/*`).
3. Read-only-mirrors 7 monolith / user-service tables for the auth middleware and daily-digest cron.
4. Runs `init_db()` on startup to seed 7 built-in templates (`app/db/session.py:61-93,96-207`).

So: **NOT stateless. Has a DB. Both reads and writes (writes are limited to one owned table).** This was explicitly the goal of Doc 38 and is documented in three source-file headers (cited in Section 4).

The OTP store, by contrast, IS in-process memory (`app/services/otp_service.py:36`) — single-process only. **Horizontal scaling breaks OTP verify.** Comment at `:30-33` acknowledges Redis is the intended production target but it hasn't been done.

### Things NOT generalizable when other services adopt this shape

1. **`controllers/` layer is half-adopted.** Legacy routes have controllers; new (Doc-38) routes don't. If this is the reference shape, decide: keep controllers everywhere, or drop them everywhere. Three single-method controllers (~5 lines each) are not pulling weight.
2. **`db/repositories/rbac_read_repository.py` uses raw SQL `text()`** with table names hard-coded to user-service's schema. If user-service renames a column (e.g. `user_roles.role_id` → `user_roles.role`), this service breaks silently — the `Exception` catch in middleware demotes the failure to anonymous-request (`app/middleware/auth_middleware.py:93-97`), so the symptom is "every authed request 401s" not a clear DB error. Other services adopting this shape need an equivalent repo and a cross-repo test to detect drift.
3. **JWT `SECRET_KEY` is shared across three services** (`app/config/settings.py:75-80`); permission-code constants are duplicated across three repos with a manual sync note (`app/core/permissions.py:8-11`). The reference shape doesn't address how the other services will keep their constants aligned — a shared library would help, but it's out of scope.
4. **Public-prefix allow-list in auth middleware is hard-coded** (`app/middleware/auth_middleware.py:32-40`). Other services will need the same pattern but with different prefixes; generalising to a settings-driven list would help.
5. **Port mismatch story**: container internal `8000`, host-mapped `8002`. The other services likely have the same pattern (each container internally on `:8000`, host-mapped). This needs documenting as the convention, not as a per-service quirk.
6. **`schemas/notification_template.py` carries logic** (`validate_placeholder_set`) — if the reference says "schemas are pure", this is a violation that should be relocated before other services copy the pattern.

### Decisions needed before adopting this as reference shape

1. **Is `controllers/` + `services/` necessary, or one layer enough?** The current evidence (Doc-38 routes calling services directly with no quality loss) suggests one layer suffices. The legacy controllers feel like a holdover.
2. **Where does cross-cutting validation live — `schemas/`, `services/`, or `core/`?** The placeholder allow-list straddles `schemas/` and routes.
3. **Should middleware use `Depends(get_db)` or `SessionLocal()` directly?** This service uses `SessionLocal()` directly (`app/middleware/auth_middleware.py:80`). For consistency the other services should follow the same approach.
4. **Should each service own its own alembic chain, or rely on the monolith?** Today this service ships none (no `alembic.ini`, `app/db/session.py:64-71`) and relies on the monolith. If the refactor splits ownership further, the other services may need their own migrations.
5. **OTP store: in-memory or Redis?** Current shape blocks horizontal scaling. The other services don't need OTP, but the pattern of "stateful in-process storage in a microservice" should be flagged as something the reference shape does NOT endorse.
6. **`jinja2`, `MIGRATIONS_AUTORUN`, `MIGRATIONS_REQUIRED`** — dead. Should not be carried into the reference template.
7. **Python version**: Dockerfile says 3.11 (`Dockerfile:1`); local dev artefacts show 3.12. Standardise.
8. **`request_id` overlap**: `OTPService` returns a `request_id` field (`app/services/otp_service.py:25,94`) that is the OTP record id, while `RequestContextMiddleware` sets `request.state.request_id` (`app/middleware/request_context.py:18`). Same name, different concept. Risk of confusion when porting to other services.

### Smaller risks

- **No retries on outbound provider calls.** A flaky SMTP or MSG91 raises immediately into a 502 (`app/services/email_service.py:155-159`, `app/services/sms_service.py:97-101`).
- **CORS `allow_origins=["*"]` with `allow_credentials=True`** (`app/main.py:51-57`) is a Pydantic-Settings default driven by `CORS_ORIGINS=*` (`.env.example:17`). Browser will reject credentialed CORS preflight if origin is `*` — but since the legacy dispatch endpoints are server-to-server this is mostly harmless. Worth flagging.
- **`init_db()` swallows exceptions** (`app/main.py:25-26`) — service boots even when the DB is unreachable. Auth-gated endpoints will then 500 unpredictably.
- **Bare `except Exception` in 4 places** (`app/db/session.py:89`, `app/main.py:25`, `app/middleware/auth_middleware.py:93`, `app/core/auth.py:54`) — defensive but masks real errors during boot/auth diagnosis.

---

*Audit complete. Total source files inspected: 41 Python files + Dockerfile + docker-compose.yml + .env.example + requirements.txt + 4 planned_changes docs.*
