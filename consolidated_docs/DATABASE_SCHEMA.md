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
| `template_kind` | `VARCHAR(64) NOT NULL` | Free-form; built-ins: `otp_login` / `password_reset_link` / `password_reset_otp` / `project_deadline_digest` |
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
| `project_deadline_digest` | email | `{first_name}`, `{items_html}`, `{portal_url}` — `items_html` is pre-rendered by `digest_service.render_items_html`; `portal_url` comes from `FRONTEND_BASE_URL` |

---

## 4. Read-only mirrors (doc 3 — daily deadline-digest cron)

The daily-digest cron needs to query the shared-DB tables that the monolith owns. These models are declared in `app/db/models/` for SQLAlchemy lookup; in shared-DB production deploys they map to existing rows monolith populates, and `Base.metadata.create_all` is a no-op. For SQLite test DBs `create_all` builds the columns this service reads.

| Mirror | Columns this service reads |
|---|---|
| `projects` | `id, project_code, name, status, deleted_at` |
| `milestones` | `id, project_id, name, start_date, end_date, status, deleted_at` |
| `activities` | `id, project_id, milestone_id, name, start_date, end_date, status, deleted_at` |
| `users` | `id, login, email, first_name, last_name, status, deleted_at` |
| `roles` | `id, name` |
| `user_role_assignments` | `id, user_id, role_id, organization_id, project_id` |
| `project_vendors` | `project_id, vendor_id` |

Each mirror declares ONLY the columns the cron reads. Extra columns that exist in production (e.g. `users.phone_number`, `projects.description`, etc.) are absent from this service's mapping — keeps the cross-service coupling small and the SQLite create_all minimal.

---

## 5. Migration coordination

The notification-service runs with `MIGRATIONS_AUTORUN=false` in shared-DB deploys. The monolith owns alembic on the shared Postgres. Adding a column to `notification_templates`:

1. **Monolith repo**: write the alembic migration in `alembic/versions/`. Update model. Push.
2. **Notification-service repo**: update model file (mirror the column). Push.
3. **Deploy ordering**: monolith first (alembic runs), notification-service second.

---

## 5. Doc references

- doc 36 — DB-backed templates (created the table; lived in user-service initially).
- doc 38 — ownership moved to this service; user-service drops its model + master endpoints + renderer.
