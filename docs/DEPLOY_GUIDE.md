# PMIS Refactor — Deploy Guide (ILLUSTRATIVE)

**This is a reference, not a runbook.** Devops adapts to their orchestrator of choice (Kubernetes, ECS, plain Docker on a VM, etc.). The four backend services + frontend are independent containers; deployment shape is devops's decision.

What this guide DOES cover:
- The minimum env vars each service needs
- The expected health/readiness probe endpoints
- How alembic migrations run during deploy
- The logging output format

What this guide does NOT cover:
- TLS termination strategy
- Reverse proxy choice (illustrative nginx config in [`../nginx/`](../nginx/))
- Secret management (Vault, AWS Secrets Manager, env files — devops's call)
- Backup strategy
- Monitoring / alerting / log aggregation

---

## Local docker-compose (single-command bring-up)

```bash
cp .env.example .env       # edit values
docker compose up
```

This brings up Postgres 16 + 4 backend services + frontend behind nginx on port 80. Useful for local end-to-end smoke checks.

---

## Per-service environment variables

Full env-var matrix lives in [`../.env.example`](../.env.example). Per-service subsets:

### `pmis-user-management`

| Var | Default | Purpose |
|---|---|---|
| `ENV` | `development` | `development` / `staging` / `production` |
| `DATABASE_URL` | (required) | DML connection string |
| `DATABASE_URL_MIGRATIONS` | optional | DDL connection string (alembic) |
| `SECRET_KEY` | (required) | JWT signing key; **shared across all services** |
| `ALGORITHM` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `120` | |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | |
| `REFRESH_TOKEN_GRACE_SECONDS` | `120` | rotation grace |
| `BOOTSTRAP_SUPERADMIN_LOGIN` | `superadmin` | seeded by bootstrap migration |
| `BOOTSTRAP_SUPERADMIN_EMAIL` | (required) | |
| `SUPERADMIN_BOOTSTRAP_PASSWORD` | (required at first migration only; unset after) | argon2-hashed inside bootstrap migration |
| `REQUIRE_2FA` | `true` | |
| `OTP_*` | (see .env.example) | OTP TTLs and limits |
| `OTP_HASH_PEPPER` | (required in prod) | OTP code hashing |
| `PASSWORD_RESET_TTL_SECONDS` | `3600` | |
| `UNIVERSAL_OTP_ENABLED` | `false` | **startup error if `true` when `ENV=production` (Q14)** |
| `NOTIFICATION_SERVICE_URL` | `http://pmis-notification-management:8002` | |
| `ROOT_PATH` | `""` | nginx prefix (per Decision 8a) |

### `pmis-project-management`

| Var | Default | Purpose |
|---|---|---|
| `ENV`, `DATABASE_URL`, `SECRET_KEY`, `ALGORITHM`, `ROOT_PATH` | (as above) | |
| `SUBTASK_MAX_NESTING_DEPTH` | `5` | |
| `ATTACHMENTS_STORAGE_BASE_PATH` | `/var/lib/pmis/attachments` | volume mount |
| `ATTACHMENTS_MAX_BYTES` | `26214400` | 25 MB (Q22) |
| `ATTACHMENTS_ALLOWED_EXTENSIONS` | (see .env.example) | comma-separated |
| `ATTACHMENTS_SUBDIR_STRATEGY` | `year_month` | |
| `FILE_SERVER_PUBLIC_BASE_URL` | optional | external file server |
| `FILE_SERVER_LOCAL_FALLBACK_ENABLED` | `true` | |

### `pmis-notification-management`

| Var | Default | Purpose |
|---|---|---|
| `ENV`, `DATABASE_URL`, `SECRET_KEY`, `ROOT_PATH` | (as above) | |
| `EMAIL_PROVIDER` | `smtp` | `smtp` / `sendgrid` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS` | (see .env.example) | when `EMAIL_PROVIDER=smtp` |
| `SENDGRID_API_KEY` | optional | when `EMAIL_PROVIDER=sendgrid` |
| `SMS_PROVIDER` | `mock` | `mock` / `twilio` / `msg91` |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `SMS_FROM_NUMBER` | (required for twilio) | |
| `MSG91_API_KEY`, `MSG91_SENDER_ID`, `MSG91_ROUTE` | (required for msg91) | |
| `CRON_SHARED_SECRET` | (required) | `X-Cron-Secret` header for `/notification/cron/daily-digest` |
| `DEADLINE_WINDOW_DAYS` | `5` | digest lookahead window |

### `pmis-masters-management`

| Var | Default | Purpose |
|---|---|---|
| `ENV`, `DATABASE_URL`, `SECRET_KEY`, `ROOT_PATH` | (as above) | |
| `DIVISION_DEFAULT_EMAIL`, `DIVISION_DEFAULT_PHONE` | optional | catalog fallback |

---

## Health and readiness probes

Each backend service exposes:

| Endpoint | Purpose | DB hit? |
|---|---|---|
| `GET /health` | Process-alive check | No |
| `GET /ready` | Readiness check (DB + external deps) | Yes (cheap query) |

Expected response shape:
```json
{"status": "ok", "service": "pmis-<svc>-management", "version": "0.1.0"}
```

Status 503 + JSON body with `status: "not_ready"` and `reason` on failure.

Orchestrator probe recommendation: `/health` for liveness, `/ready` for readiness with 2-attempt grace.

---

## Migration during deploy

Each service ships its own alembic chain. Run **once per deploy** (idempotent — no-op if at head):

```bash
docker compose run --rm pmis-<svc>-management alembic upgrade head
```

For first-time bootstrap (new environment), also run the seed migration:

```bash
SUPERADMIN_BOOTSTRAP_PASSWORD='<initial_password>' \
docker compose run --rm pmis-user-management alembic upgrade head
# After completion, unset SUPERADMIN_BOOTSTRAP_PASSWORD from the env.
```

Per-service alembic version tables:
- `users.alembic_version_users`
- `project.alembic_version_project`
- `notification.alembic_version_notification`
- `masters.alembic_version_masters`

---

## Logging output format

Per [`../.env.example`](../.env.example):

- `LOG_LEVEL=INFO` (default)
- `LOG_FORMAT=text` (development) or `LOG_FORMAT=json` (production)

JSON output:
```json
{"timestamp": "2026-XX-XX...", "level": "INFO", "service": "pmis-user-management", "request_id": "...", "msg": "..."}
```

Logs go to stdout (12-factor). Devops aggregates via their preferred log collector (CloudWatch, Datadog, ELK, etc.).

---

## What devops decides

- TLS termination point
- Reverse proxy (nginx config in [`../nginx/`](../nginx/) is illustrative)
- Secret storage and injection (env vars, mounted files, Vault, etc.)
- Backup strategy and retention
- Monitoring + alerting (the services emit structured logs and probe endpoints; instrument as needed)
- Container registry and image tagging
- Rolling-deploy strategy
