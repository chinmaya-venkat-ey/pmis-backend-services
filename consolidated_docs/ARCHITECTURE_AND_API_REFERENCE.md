# PMIS-notification-service — Architecture and API Reference

**Service**: PIMS-NOTIFICATION
**Port**: 8002
**Status**: doc 38 in flight — gaining a database + admin surface for `notification_templates`. Pre-doc-38 the service was a stateless dispatcher.
**Last refresh**: 2026-05-07

This service owns email + SMS dispatch for the PMIS platform. After doc 38 it also owns the `notification_templates` master catalog (template content for OTP login, password reset, etc.).

---

## 1. Technology stack

| Component | Technology |
|-----------|-----------|
| Framework | FastAPI |
| Email providers | SMTP (default), SendGrid |
| SMS providers | Twilio, MSG91, mock (dev default) |
| Templating | Jinja2 (legacy) + DB-backed templates (doc 38) |
| Database | PostgreSQL (shared with monolith + user-service post-doc-38) |
| ORM | SQLAlchemy 2.0 |
| Auth | JWT HS256 with shared SECRET_KEY (post-doc-38, only on master endpoints) |

---

## 2. Architecture (post-doc-38)

```
app/
├── main.py                            # FastAPI entry; CORS + RequestContext + auth middleware
├── config/settings.py                 # Settings via pydantic-settings
├── controllers/                       # email, sms, otp send/verify
├── routes/
│   ├── email_routes.py                # /api/v1/notifications/email/send
│   ├── sms_routes.py                  # /api/v1/notifications/sms/send
│   ├── otp_routes.py                  # /api/v1/notifications/otp/send + /verify
│   ├── health_routes.py
│   └── master_data_routes.py          # NEW (doc 38) — /api/v3/master/notification_templates
├── services/
│   ├── email_service.py               # SMTP / SendGrid dispatch (doc 38: optional template render)
│   ├── sms_service.py                 # Twilio / MSG91 / mock dispatch (doc 38: optional template render)
│   ├── otp_service.py                 # in-memory OTP store
│   └── template_service.py            # NEW (doc 38) — DB lookup + render
├── schemas/                           # email, sms, otp, notification_template (NEW)
├── middleware/
│   ├── error_handler.py
│   ├── request_context.py
│   └── auth.py                        # NEW (doc 38) — JWT decode + permission hydration
└── db/                                # NEW (doc 38)
    ├── session.py                     # Engine + SessionLocal + Base
    ├── models/
    │   └── notification_template.py
    └── repositories/
        └── notification_template_repository.py
```

---

## 3. Endpoint reference

### System

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/` | No | Service info |
| GET | `/api/v1/health` | No | Health check; surfaces email + sms provider config |
| GET | `/docs` | No | Swagger UI |

### Dispatch endpoints (legacy + extended)

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| POST | `/api/v1/notifications/email/send` | No (callable from monolith / user-service) | Legacy: `{to, subject, body, is_html, cc, bcc}`. Doc 38: also accepts `{to, template_kind, payload}` — server-side renders. |
| POST | `/api/v1/notifications/sms/send` | No | Legacy: `{to, message}`. Doc 38: also accepts `{to, template_kind, payload}`. |
| POST | `/api/v1/notifications/otp/send` | No | Generate + email/SMS an OTP for an arbitrary purpose; in-memory store. |
| POST | `/api/v1/notifications/otp/verify` | No | Verify against in-memory OTP. |
| POST | `/api/v1/notifications/dispatch` | No | Templated dispatch — `{channel, recipient, template_kind, payload}`. Renders + sends in one call. |

> The dispatch endpoints stay **unauthenticated** in this service so the monolith and user-service can call them without juggling tokens. They're inside the trust boundary.

### Cron endpoints (doc 3 — daily deadline-digest)

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| POST | `/api/v1/notifications/cron/daily-digest` | `X-Cron-Secret` header matching `CRON_SHARED_SECRET` env var | Scans `pmis_db` for milestones / activities ending within `DEADLINE_WINDOW_DAYS` (default 5) or already past due; groups them per responsible user (org_admin / project_admin / project_member scoped to each project); sends one email per user via the existing `email_service`. Returns `{ranAt, usersNotified, emailsSent, emailsFailed, itemsAggregated}`. Returns 503 when `CRON_SHARED_SECRET` is unset (endpoint disabled). DevOps's host cron is the only intended caller. |

> Empty body is fine. Optional overrides: `{today: "YYYY-MM-DD", windowDays: int}` for replays. See `planned_changes/3` for the design.

### Master data (doc 38 — new)

| Method | Path | Permission | Notes |
|--------|------|-----------|-------|
| GET | `/api/v3/master/notification_templates` | `master_data:view` | List templates; `?include_inactive=true` for admin view |
| GET | `/api/v3/master/notification_templates/{id}` | `master_data:view` | Single read |
| POST | `/api/v3/master/notification_templates/create` | `master_data:manage` | Create custom template |
| PATCH | `/api/v3/master/notification_templates/{id}` | `master_data:manage` | Edit subject/body/active/description |
| DELETE | `/api/v3/master/notification_templates/{id}` | `master_data:manage` | Soft-deactivate |
| POST | `/api/v3/master/notification_templates/{id}/restore` | `master_data:manage` | Re-activate |

These endpoints require a Bearer token and verify against the shared `permissions` table. The monolith's `NotificationServiceProxyMiddleware` forwards these paths from `:8000` to here.

---

## 4. How the service is reached

Two entry points after doc 38:

1. **Direct** at `http://10.1.131.199:8002/api/v3/master/notification_templates/...` — for ops or tooling.
2. **Through the monolith proxy** at `http://10.1.131.199:8000/api/v3/master/notification_templates/...` — when `NOTIFICATION_SERVICE_PROXY_ENABLED=true` on the monolith. Same URLs, same shapes; the monolith forwards transparently.

The legacy `/api/v1/notifications/...` endpoints stay at port 8002 only — they're internal contracts called by user-service and (in future) the monolith.

---

## 5. Cross-service relationships

| Caller | Endpoint | Why |
|--------|----------|-----|
| user-service `HttpNotificationClient` | `POST /api/v1/notifications/email/send` | OTP login emails, password-reset link emails |
| user-service `HttpNotificationClient` | `POST /api/v1/notifications/sms/send` | OTP login SMS, password-reset OTP SMS |
| monolith proxy | `/api/v3/master/notification_templates/*` | Admin CRUD on templates from the FE |
| Future monolith dispatch path | `POST /api/v1/notifications/email/send` | Project notifications (TBD) |

---

## 6. Configuration

`app/config/settings.py` — `Settings` class. Critical env vars:

```bash
APP_NAME=PIMS-NOTIFICATION
APP_PORT=8002
API_PREFIX=/api/v1

# Shared with monolith + user-service (post-doc-38)
DATABASE_URL=postgresql://...
SECRET_KEY=<32+ chars; same as monolith>

# Email
EMAIL_PROVIDER=smtp                   # smtp | sendgrid
EMAIL_FROM_ADDRESS=no-reply@pims.example.com
SMTP_HOST=...
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_USE_TLS=true
SENDGRID_API_KEY=

# SMS
SMS_PROVIDER=mock                     # mock | twilio | msg91
SMS_FROM_NUMBER=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
MSG91_API_KEY=

# Template rendering (doc 38)
FRONTEND_BASE_URL=                    # used in password-reset email links
```

---

## 7. See also

- [DEPLOYMENT_AND_INTEGRATION.md](./DEPLOYMENT_AND_INTEGRATION.md) — env vars, run instructions, integration with monolith + user-service.
- [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md) — `notification_templates` shape.
- [TESTING_AND_QUALITY.md](./TESTING_AND_QUALITY.md) — pytest + smoke recipes.
- [planned_changes/1](../planned_changes/1.%20Notification%20templates%20moved%20to%20this%20service.md) — what shipped under doc 38 from this repo's side.
