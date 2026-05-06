# Testing and Quality — pmis-notification-service

How tests work in this repo, how to run them, and what's covered.

---

## 1. Framework

- pytest + FastAPI `TestClient`.
- Pre-doc-38 the service was stateless — every test was an isolated unit (no DB, no state).
- Post-doc-38 some tests need a DB session. SQLite in-memory per test, `Base.metadata.create_all` in conftest.

---

## 2. Running

```bash
# Activate venv
.venv/Scripts/Activate.ps1   # PowerShell
# OR
source .venv/bin/activate    # bash / zsh

# Full suite
python -m pytest tests/ -q

# Single file
python -m pytest tests/test_email.py -q

# With coverage
python -m pytest tests/ --cov=app --cov-report=html
```

---

## 3. Smoke tests (manual)

### 3a. Direct dispatch

```bash
# Health
curl http://127.0.0.1:8002/api/v1/health

# Email (legacy pre-rendered shape)
curl -X POST -H "Content-Type: application/json" \
  -d '{"to":["test@example.com"],"subject":"Test","body":"Hello","is_html":false}' \
  http://127.0.0.1:8002/api/v1/notifications/email/send

# Email (doc 38 templated shape)
curl -X POST -H "Content-Type: application/json" \
  -d '{"to":["test@example.com"],"template_kind":"otp_login","payload":{"code":"123456","ttl_seconds":300}}' \
  http://127.0.0.1:8002/api/v1/notifications/email/send
```

When `EMAIL_PROVIDER=mock` (or analogous for SMS), the dispatch is a no-op log entry.

### 3b. Master template CRUD (post-doc-38)

```bash
# Get a token from user-service first
TOKEN=$(curl -s -X POST -H "Content-Type: application/json" \
  -d '{"login":"admin","password":"admin123"}' \
  http://127.0.0.1:8001/api/v3/users/login \
  | grep -oE '"access_token":"[^"]*"' | cut -d'"' -f4)

# List templates directly on notification-service
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8002/api/v3/master/notification_templates

# Same call through the monolith proxy (when NOTIFICATION_SERVICE_PROXY_ENABLED=true)
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/v3/master/notification_templates
```

Both should return identical responses (the monolith proxy forwards transparently).

---

## 4. Automated test coverage

### Existing tests (pre-doc-38)

| File | Scope |
|------|-------|
| `tests/test_email.py` | Pre-rendered email send paths (smtp + sendgrid mocked) |
| `tests/test_sms.py` | Pre-rendered sms send paths (twilio + msg91 + mock) |
| `tests/test_otp.py` | OTP send + verify (in-memory store) |
| `tests/test_health.py` | `/api/v1/health` |

### Added in doc 38

| File | Scope |
|------|-------|
| `tests/test_notification_templates.py` | Template CRUD, placeholder validation, active-uniqueness, soft-deactivate + restore, fallback when no active row |
| `tests/test_templated_dispatch.py` | `/notifications/email/send` + `/sms/send` with `template_kind + payload` shape; renderer integration + edge cases |
| `tests/test_master_auth.py` | JWT auth middleware on `/api/v3/master/*` endpoints; 401 / 403 / token-decode |

---

## 5. Smoke-test the doc-38 cutover

After all three repos deploy:

1. Monolith on 8000 with `NOTIFICATION_SERVICE_PROXY_ENABLED=true` and `NOTIFICATION_SERVICE_URL=http://10.1.131.199:8002`.
2. Notification-service on 8002 with shared DB + shared SECRET_KEY.
3. User-service on 8001 (templates removed; uses HTTP to notification-service).

Verify:

| Check | Expected |
|---|---|
| `GET /health` on each port | ok |
| Login through monolith → user-service mints JWT | 200 |
| `GET /api/v3/master/notification_templates` through monolith | proxied to notification-service → 200 with 6 seeded templates |
| `GET /api/v3/master/notification_templates` direct on 8002 | 200 with same 6 templates |
| `GET /api/v3/master/roles` through monolith | proxied to user-service (unchanged) → 200 |
| `GET /api/v3/master/divisions` through monolith | NOT proxied — handled locally → 200 |
| Login OTP flow end-to-end | OTP arrives via notification-service rendering; verify succeeds |

If notification-service goes down with the proxy on:

```bash
# Kill notification-service
curl -X POST http://127.0.0.1:8000/api/v3/master/notification_templates/create \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{...}'
# Expected: 503 with errorIdentifier="notification_service_unavailable"
```

Fail-closed by design. Setting `NOTIFICATION_SERVICE_PROXY_ENABLED=false` reverts to the monolith's local handlers.

---

## 6. Code quality

### Strengths

- Stateless dispatcher pattern (legacy paths) keeps complexity low for the email/SMS providers.
- Provider abstraction means swapping SMTP for SendGrid is one config change.
- Doc 38 adds DB + auth WITHOUT changing the dispatch path — the legacy `/api/v1/notifications/email/send` and `/sms/send` keep working unchanged for callers that already render their own content.

### Production recommendations

- `SECRET_KEY` matches monolith and user-service.
- `EMAIL_PROVIDER` and `SMS_PROVIDER` set to real providers, not `mock`.
- HTTPS enforced.
- `MIGRATIONS_AUTORUN=false` in shared-DB deploys (monolith owns alembic).
