# Deployment and Integration — pmis-user-service

How to run pmis-user-service locally, in dev, and in production. Plus how it integrates with the monolith and with PMIS-notification-service.

---

## 1. Prerequisites

- Python 3.12+
- pip
- Postgres (production) or SQLite (dev/tests). For shared-DB deploys, Postgres is required.
- Network access to PMIS-OpenProject's database (same instance) and to PMIS-notification-service when `NOTIFICATION_CLIENT=http`.

---

## 2. Setup

```bash
cd PMIS-user-management
python -m venv .venv
.venv/Scripts/Activate.ps1     # PowerShell on Windows
# OR
source .venv/bin/activate      # bash / zsh

pip install -r requirements.txt
cp .env.example .env
# Edit .env — see env-vars table below
```

### Critical .env values

The two values that **must** match the monolith (otherwise tokens minted here fail verification on the monolith):

```bash
SECRET_KEY=<exactly the same value as monolith's SECRET_KEY>
DATABASE_URL=<the same Postgres URL the monolith uses, in shared-DB deploys>
```

---

## 3. Running

### Dev (foreground, auto-reload)

```bash
uvicorn app.main:app --reload --port 8001
```

### Production (multiple workers behind a load-balancer)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 4
```

Or with gunicorn:

```bash
gunicorn -w 4 -b 0.0.0.0:8001 \
  --worker-class uvicorn.workers.UvicornWorker \
  --access-logfile - \
  --error-logfile - \
  app.main:app
```

### Verify

```bash
curl http://127.0.0.1:8001/health
# {"status":"ok","service":"pmis-user-service","version":"0.1.0","secret_key_sha256_prefix":"a24717c1eed8"}
```

The `secret_key_sha256_prefix` is `sha256(SECRET_KEY)[:12]`. Operators compare it against the monolith's `/health` to confirm both services are using the same key — without exposing the secret.

---

## 4. Environment variables

### Required

```bash
SECRET_KEY=<32+ chars, identical to monolith>
DATABASE_URL=postgresql://user:pass@host:5432/pmis
```

### Migrations (doc 33 hotfix)

```bash
MIGRATIONS_AUTORUN=true     # default. SHARED-DB DEPLOYS: set false (monolith owns alembic)
MIGRATIONS_REQUIRED=true    # when false, alembic failure logs + continues boot
DATABASE_URL_MIGRATIONS=    # optional elevated URL ONLY for `alembic upgrade head` at startup
```

### JWT + refresh

```bash
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
REFRESH_TOKEN_GRACE_SECONDS=120
```

### Bootstrap admin

```bash
BOOTSTRAP_ADMIN_LOGIN=admin
BOOTSTRAP_ADMIN_EMAIL=admin@example.com
BOOTSTRAP_ADMIN_PASSWORD=admin123      # CHANGE THIS in production
```

### CORS + pagination

```bash
CORS_ORIGINS=["http://localhost:3000"]
DEFAULT_PAGE_SIZE=20
MAX_PAGE_SIZE=100
```

### 2FA + password reset (doc 33 change 3)

```bash
REQUIRE_2FA=true                    # global toggle; per-user override via users.two_factor_enabled
OTP_TTL_SECONDS=300
OTP_RESEND_COOLDOWN_SECONDS=60
OTP_MAX_ATTEMPTS=5
OTP_CODE_LENGTH=6
OTP_HASH_PEPPER=                    # set per-deployment in production; falls back to SECRET_KEY when blank
PASSWORD_RESET_TTL_SECONDS=3600
FRONTEND_BASE_URL=                  # public FE base; embedded in password-reset email links
```

### Notification dispatch (doc 33 change 3 + doc 36)

```bash
NOTIFICATION_CLIENT=mock            # mock | http
NOTIFICATION_SERVICE_URL=           # required when NOTIFICATION_CLIENT=http (e.g. http://notif:8002/api/v1)
```

### Universal OTP (break-glass — DO NOT enable in production)

```bash
UNIVERSAL_OTP_ENABLED=false
UNIVERSAL_OTP_CODE=000000
```

---

## 5. Database

### Shared-DB deploy (default)

This service shares Postgres with the monolith. Both services connect to the same DB; the monolith owns alembic migrations.

```
DATABASE_URL=postgresql://pmis:<pw>@<host>:5432/pmis  # same in both services
MIGRATIONS_AUTORUN=false  # in user-mgmt; monolith runs alembic
```

On boot, `init_db` in this service:
1. Skips alembic (`MIGRATIONS_AUTORUN=false`).
2. Runs `RbacRepository.sync_builtin_permissions()` to upsert the permission registry + 4 built-in roles.
3. Creates the bootstrap admin if missing; forces `two_factor_enabled=False` on it every boot (break-glass).
4. Seeds 6 built-in notification templates if missing.

All steps are idempotent.

### Standalone-DB deploy (rare; dev/test convenience)

```
DATABASE_URL=sqlite:///./user_service.db
MIGRATIONS_AUTORUN=true
```

User-mgmt runs alembic itself. Use this for local-only development where the monolith isn't running.

---

## 6. Migration coordination

For schema changes affecting tables shared with the monolith — see [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md) §4 for the runbook.

Short version:
- Monolith repo owns alembic migration files.
- Both repos update the SQLAlchemy model.
- Deploy monolith first (alembic runs), user-mgmt second.

---

## 7. Pre-deployment checklist

### Security

- [ ] `SECRET_KEY` rotated to a deployment-unique 32+ char value, identical between monolith and user-mgmt.
- [ ] `BOOTSTRAP_ADMIN_PASSWORD` changed; bootstrap admin password rotated via `PATCH /users/{id}/password` after first login.
- [ ] `OTP_HASH_PEPPER` set to a deployment-unique value (don't fall back to `SECRET_KEY` in prod).
- [ ] `UNIVERSAL_OTP_ENABLED=false`.
- [ ] HTTPS enforced at the load-balancer / ingress.
- [ ] `CORS_ORIGINS` set to specific FE domains (not `["*"]`).

### Database

- [ ] Postgres reachable on `DATABASE_URL`.
- [ ] In shared-DB deploys: `MIGRATIONS_AUTORUN=false`; verify the monolith has run alembic and the schema is at head.
- [ ] In standalone-DB deploys: alembic chain runs cleanly; backup configured.

### Notifications

- [ ] `NOTIFICATION_CLIENT=http` + `NOTIFICATION_SERVICE_URL` configured for production (otherwise OTPs only land in `notification_log`).
- [ ] `FRONTEND_BASE_URL` set so password-reset emails carry a clickable link.

### Operations

- [ ] Application monitoring (latency, error rate) wired up.
- [ ] Log aggregation includes `X-Request-ID` for cross-service tracing.
- [ ] `/health` endpoint health-checked by the load-balancer.

---

## 8. Integration with PMIS-OpenProject (monolith)

This service is fronted by the monolith's `UserServiceProxyMiddleware` when `USER_SERVICE_PROXY_ENABLED=true`. The FE keeps calling the monolith URL; the monolith forwards user/auth/RBAC/notification-template paths here.

```
FE  -->  Monolith :8000  --proxy-->  user-mgmt :8001
                                      ^
                                      shared SECRET_KEY
                                      shared Postgres
```

To turn the proxy on:

```bash
# In monolith's environment:
USER_SERVICE_PROXY_ENABLED=true
USER_SERVICE_URL=http://<user-mgmt-host>:8001
```

To roll back: `USER_SERVICE_PROXY_ENABLED=false` + restart the monolith. Local handlers spring back to life. No DB change.

For the cutover plan + per-commit history, see `planned_changes/37` in the monolith repo.

---

## 9. Integration with PMIS-notification-service

When `NOTIFICATION_CLIENT=http`, this service POSTs notification dispatch requests to PMIS-notification-service:

```
POST {NOTIFICATION_SERVICE_URL}/api/v1/notifications/email/send
Body: {"to":["x@y"], "subject":"...", "body":"...", "is_html": true}

POST {NOTIFICATION_SERVICE_URL}/api/v1/notifications/sms/send
Body: {"to":"+91...", "message":"..."}
```

Every dispatch writes a row to `notification_log` regardless of backend. Mock backend writes the row as the terminal sink (used in dev/tests); HTTP backend writes pre-call (status `queued`) and updates after (status `sent` / `failed` with the error message + provider + message_id stashed under `payload._dispatch`).

If `NOTIFICATION_CLIENT=http` but `NOTIFICATION_SERVICE_URL` is empty, the dispatch fails with `status='failed'` and a clear error message — auth flows continue (the OTP is still saved in `otp_codes`; the user just won't receive it).

---

## 10. Health checks

```bash
# Health check (no auth)
curl http://localhost:8001/health
# {"status":"ok","service":"pmis-user-service","version":"0.1.0","secret_key_sha256_prefix":"a24717c1eed8"}

# Authenticated user check
curl -H "Authorization: Bearer <token>" http://localhost:8001/api/v3/users/me
```

---

## 11. Scaling

- Single instance: ~500 req/sec capacity (auth flows are CPU-bound on Argon2 password hashing).
- Horizontal: stateless — multiple instances behind a load-balancer with sticky sessions NOT required (every request carries its own JWT).
- Database: standard Postgres replication for HA. Argon2 cost parameter is the dominant CPU consumer; tune via `argon2.PasswordHasher` defaults if necessary (don't lower below industry-standard memory cost).
- Caching: not currently used. The per-request RBAC hydration is one indexed JOIN — adding a Redis cache hasn't proven necessary in load testing.

---

## 12. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/health` returns but every authenticated call is 401 | `SECRET_KEY` doesn't match monolith's | Verify `secret_key_sha256_prefix` in both `/health` outputs match |
| Login returns 500 with "no module named X" | `app/core/permissions.py` or related file missing | `pip install -r requirements.txt`; check `git status` for missing files |
| 2FA OTP never arrives | `NOTIFICATION_CLIENT=mock` (default) — code is in `notification_log` table, not in email | Set `NOTIFICATION_CLIENT=http` + `NOTIFICATION_SERVICE_URL` |
| Bootstrap admin can't log in after restart | Password rotation didn't persist; or someone changed the seed values without flushing the DB | Check `BOOTSTRAP_ADMIN_PASSWORD`; `init_db` only creates the admin if missing — it doesn't re-seed the password |
| 503 from monolith on `/users/login` | Monolith proxy is on but user-mgmt is unreachable | Verify user-mgmt is running and `USER_SERVICE_URL` resolves; check `/health` on port 8001 directly |
| User-mgmt boot crashes with "alembic head mismatch" | Schema changed on monolith side without coordinating | Pull latest user-mgmt model files; deploy monolith first to run alembic, then user-mgmt |
