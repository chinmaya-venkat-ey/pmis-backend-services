# Deployment and Integration — pmis-notification-service

How to run the service locally, in dev, and in production. How it integrates with monolith + user-service.

---

## 1. Setup

```bash
cd PMIS-notification-service
python -m venv .venv
.venv/Scripts/Activate.ps1     # PowerShell on Windows
# OR
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# Edit .env — see env-vars table below
```

---

## 2. Running

### Dev

```bash
uvicorn app.main:app --reload --port 8002
```

### Production

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8002 --workers 4
```

Or via gunicorn:

```bash
gunicorn -w 4 -b 0.0.0.0:8002 \
  --worker-class uvicorn.workers.UvicornWorker \
  app.main:app
```

### Verify

```bash
curl http://127.0.0.1:8002/api/v1/health
# {"status":"ok","service":"PIMS-NOTIFICATION","email":"smtp","sms":"mock"}
```

---

## 3. Environment variables

### Application

```bash
APP_NAME=PIMS-NOTIFICATION
APP_PORT=8002
API_PREFIX=/api/v1
APP_DEBUG=false
LOG_LEVEL=INFO
CORS_ORIGINS=*                  # tighten in production
```

### Database (post-doc-38)

```bash
DATABASE_URL=postgresql://user:pass@host:5432/pmis    # SHARED with monolith + user-service
MIGRATIONS_AUTORUN=false        # default. Monolith owns alembic on the shared DB
MIGRATIONS_REQUIRED=true
```

### Auth (post-doc-38, only enforced on /api/v3/master/* endpoints)

```bash
SECRET_KEY=<32+ chars; identical to monolith and user-service>
ALGORITHM=HS256
```

### Email

```bash
EMAIL_PROVIDER=smtp             # smtp | sendgrid
EMAIL_FROM_ADDRESS=no-reply@pims.example.com
EMAIL_FROM_NAME=PIMS Notification

# SMTP
SMTP_HOST=...
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_USE_TLS=true

# SendGrid (alternative)
SENDGRID_API_KEY=
```

### SMS

```bash
SMS_PROVIDER=mock               # mock | twilio | msg91
SMS_FROM_NUMBER=

# Twilio
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=

# MSG91
MSG91_API_KEY=
```

### Template rendering (doc 38)

```bash
FRONTEND_BASE_URL=              # public FE base URL; embedded in password-reset email links
                                # AND in daily-digest portal links (see daily-digest cron below)
```

### Daily deadline-digest cron (doc 3)

```bash
CRON_SHARED_SECRET=             # shared secret the DevOps host cron presents as X-Cron-Secret
                                # Empty (default) → endpoint disabled, returns 503
DEADLINE_WINDOW_DAYS=5          # look-ahead in days for items considered "ending soon" (default 5)
                                # Overdue items (end_date < today) are always included regardless
```

DevOps's host crontab should call the endpoint daily, suggested 09:00 IST:

```
0 9 * * * curl -fsS -X POST -H "X-Cron-Secret: $SECRET" \
  http://localhost:8002/api/v1/notifications/cron/daily-digest \
  > /var/log/pmis/daily-digest.json
```

Smoke-test it after first deploy by curling manually with the secret and
inspecting the JSON summary. `notification_log` will show one row per
email attempt.

---

## 4. Pre-deployment checklist

### Security

- [ ] `SECRET_KEY` rotated to a deployment-unique 32+ char value, **identical** between monolith / user-service / notification-service.
- [ ] `EMAIL_PROVIDER` and `SMS_PROVIDER` configured for production (not `mock`).
- [ ] SMTP / SendGrid / Twilio / MSG91 credentials populated.
- [ ] `CORS_ORIGINS` set to specific FE domains, not `*`.
- [ ] HTTPS enforced at the load-balancer / ingress.

### Database (post-doc-38)

- [ ] Postgres reachable on `DATABASE_URL` (same instance as monolith).
- [ ] `MIGRATIONS_AUTORUN=false` so this service doesn't race the monolith on alembic.
- [ ] `notification_templates` table is at expected schema (alembic head from monolith side).

### Operations

- [ ] `/api/v1/health` health-checked by the load-balancer.
- [ ] Log aggregation includes `X-Request-ID` for cross-service tracing.

---

## 5. Integration with PMIS-OpenProject (monolith)

After doc 38, the monolith proxies notification-template admin paths to here:

```
FE  -->  Monolith :8000  --proxy-->  notification-service :8002
                                       /api/v3/master/notification_templates/*
```

To turn the proxy on:

```bash
# In monolith's environment:
NOTIFICATION_SERVICE_PROXY_ENABLED=true
NOTIFICATION_SERVICE_URL=http://<notif-host>:8002
```

To roll back: `NOTIFICATION_SERVICE_PROXY_ENABLED=false` + restart the monolith. The monolith's local handlers for those paths spring back to life. No DB change.

For the cutover plan + per-commit history, see `planned_changes/38` in the monolith repo.

---

## 6. Integration with PMIS-user-management (user-service)

After doc 38, user-service POSTs templated notification requests here:

```
user-service :8001  -->  notification-service :8002

POST /api/v1/notifications/email/send
{
  "to": ["user@example.com"],
  "template_kind": "otp_login",
  "payload": {"code": "123456", "ttl_seconds": 300}
}
```

Notification-service looks up the template, renders, dispatches. The legacy pre-rendered shape (`{to, subject, body, is_html}`) keeps working for back-compat.

User-service no longer carries the `notification_templates` table. The mock backend in user-service still writes `notification_log` rows with the rendered output for audit, but the renderer is HTTP-based against this service.

---

## 7. Health checks

```bash
# Health (no auth)
curl http://localhost:8002/api/v1/health

# Templates (post-doc-38; requires Bearer token)
curl -H "Authorization: Bearer <token>" \
  http://localhost:8002/api/v3/master/notification_templates
```

---

## 8. Scaling

Stateless dispatcher (legacy endpoints) + thin DB read (template render). Multiple instances behind a load-balancer with no special concerns. Argon2 / token verification cost is small relative to upstream provider latency.

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/api/v3/master/notification_templates` returns 401 | Bearer token missing or expired | Login via user-service first; copy access_token |
| `/api/v3/master/notification_templates` returns 403 | Token good but caller lacks `master_data:view` | Check caller has the seeded `admin` role |
| Email/SMS dispatch with `template_kind` returns 422 | Template kind not in catalog or placeholder mismatch | List templates; ensure the kind is active |
| Service starts but DB calls fail | `DATABASE_URL` mis-configured | Check env; verify shared Postgres reachable |
| Migration error on boot | `MIGRATIONS_AUTORUN=true` but monolith owns alembic | Set `MIGRATIONS_AUTORUN=false` in shared-DB deploys |
