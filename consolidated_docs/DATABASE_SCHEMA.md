# Database Schema — pmis-notification-service

**Last refresh**: 2026-05-07 (in flight per doc 38)
**Source of truth**: SQLAlchemy models under [app/db/models/](../app/db/models/) (created in doc 38).
**Database**: shared with PMIS-OpenProject monolith and PMIS-user-management on the same Postgres instance.

Pre-doc-38 this service was stateless. Doc 38 adds one table — `notification_templates` — which migrates ownership from user-service to here. The table itself was created by monolith doc-36 alembic; doc 38 is purely a code-ownership shift, not a schema change.

---

## 1. Tables this service OWNS (post-doc-38)

| Table | Purpose | Doc |
|-------|---------|-----|
| `notification_templates` | DB-backed email + SMS template content | doc 36 (created) → doc 38 (ownership moved here) |

That's the entire owned-table set. Every other notification-domain piece (the OTP store, the in-flight dispatch state) is still in-process / in-memory.

## 2. Tables this service READS but doesn't write

These are read-only here so the JWT auth middleware can verify Bearer tokens against the canonical RBAC tables (owned by user-service).

| Table | Purpose |
|-------|---------|
| `users` | Caller identity from JWT `user_id` claim |
| `roles` | Role lookup |
| `role_permissions` | Role → permission junction |
| `user_roles` | User → role junction |
| `user_permissions` | Direct user-permission grants |
| `revoked_tokens` | JWT JTI blacklist |

The auth middleware does one indexed JOIN to compute `effective_permissions_for_user(user_id)` and gate `/api/v3/master/*` endpoints. The user-service is the authoritative writer for all six.

---

## 3. `notification_templates` — full reference

DB-backed email + SMS template catalog. Renderers in `app/services/template_service.py` look up active rows by `(template_kind, channel)` and run `str.format_map` over the stored copy. Computed placeholders (`ttl_minutes` from `ttl_seconds`, `reset_url` from `FRONTEND_BASE_URL` + `token`) are derived in this service before substitution.

| Column | Type | Notes |
|---|---|---|
| `id` | `INTEGER PK` | Autoincrement |
| `template_kind` | `VARCHAR(64) NOT NULL` | Free-form; built-ins: `otp_login` / `password_reset_link` / `password_reset_otp` |
| `channel` | `VARCHAR(16) NOT NULL` | `email` / `sms` |
| `subject` | `VARCHAR(500) NULL` | Required for email; null for SMS |
| `body` | `TEXT NOT NULL` | HTML for email, plaintext for SMS; `{placeholder}` substitution |
| `is_html` | `BOOLEAN NOT NULL DEFAULT TRUE` | |
| `is_builtin` | `BOOLEAN NOT NULL` | Built-ins protected from hard delete; copy IS editable |
| `active` | `BOOLEAN NOT NULL DEFAULT TRUE` | At-most-one-active per (kind, channel) — Postgres partial unique index + service-layer guard |
| `description` | `VARCHAR(1024) NULL` | Ops note |
| `created_at`, `updated_at` | `TIMESTAMP WITH TIME ZONE` | |

### Indexes

- Composite `(template_kind, channel, active)` for the renderer's hot lookup.
- Postgres partial unique index `uq_notification_templates_kind_channel_active` on `(template_kind, channel) WHERE active = TRUE` — at-most-one-active per pair.

### Allowed placeholders

Validated on PATCH/POST; unknown kinds skip the check (free-form support).

| Template kind | Channel | Placeholders |
|---|---|---|
| `otp_login` | email + sms | `{code}`, `{ttl_minutes}` |
| `password_reset_link` | email | `{reset_url}`, `{token}`, `{ttl_minutes}` |
| `password_reset_link` | sms | `{token}`, `{ttl_minutes}` |
| `password_reset_otp` | email + sms | `{code}`, `{ttl_minutes}` |

---

## 4. Migration coordination

The notification-service runs with `MIGRATIONS_AUTORUN=false` in shared-DB deploys. The monolith owns alembic on the shared Postgres. Adding a column to `notification_templates`:

1. **Monolith repo**: write the alembic migration in `alembic/versions/`. Update model. Push.
2. **Notification-service repo**: update model file (mirror the column). Push.
3. **Deploy ordering**: monolith first (alembic runs), notification-service second.

---

## 5. Doc references

- doc 36 — DB-backed templates (created the table; lived in user-service initially).
- doc 38 — ownership moved to this service; user-service drops its model + master endpoints + renderer.
