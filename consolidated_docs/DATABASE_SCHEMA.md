# Database Schema — pmis-user-service

**Last refresh**: 2026-05-06 (post-doc 37 part 2)
**Source of truth**: SQLAlchemy models under [app/infrastructure/db/models/](../app/infrastructure/db/models/).
**Database**: shared with PMIS-OpenProject monolith on the same Postgres instance.

This service writes to a subset of the shared DB. The monolith owns alembic and runs migrations on every boot (this service has `MIGRATIONS_AUTORUN=false` in shared-DB deploys). User-mgmt's models exist so SQLAlchemy can map results — they have to stay in sync with the monolith's models. **Do not edit a model here without making the equivalent change on the monolith side.**

---

## 1. Tables this service OWNS (writes + reads)

These are the tables user-mgmt is the authoritative writer for. The monolith may read them but doesn't write.

| Table | Purpose | Doc |
|-------|---------|-----|
| `users` | User accounts; UUID PK; refresh-token rotation slots; vendor + division; doc-33 `two_factor_enabled` | doc 21B + 26 + 33 |
| `roles` | Named permission bundles; built-in flag + description | doc 21B |
| `permissions` | Permission catalog (string codes) | doc 21B |
| `role_permissions` | M-N junction (role ↔ permission) | doc 21B |
| `user_roles` | M-N junction (user ↔ role) | doc 21B |
| `user_permissions` | Direct user-level permission grants (additive) | doc 21B |
| `revoked_tokens` | JWT JTI blacklist | |
| `otp_codes` | 2FA OTP rows (hashed) | doc 33 change 3 |
| `password_reset_tokens` | Reset tokens (hashed) | doc 33 change 3 |
| `notification_log` | Every email/SMS dispatch recorded | doc 33 change 3 |
| `notification_templates` | DB-backed email + SMS template content | doc 36 |

---

## 2. Tables this service READS but doesn't write

These are mapped here so SQLAlchemy can satisfy FKs and joins (e.g. `users.vendor_id → vendors.id`). The monolith owns writes.

| Table | Purpose |
|-------|---------|
| `vendors` | Vendor catalog (referenced from `users.vendor_id`) |
| `projects` | Projects (referenced from `project_members.project_id`) |
| `project_members` | User ↔ project assignments |
| `milestone_vendors` | Vendor M-N junction (kept here only because the monolith creates the FK chain via vendors → users.deleted_by) |
| `project_vendors` | Same reasoning as milestone_vendors |

---

## 3. Per-table reference

### `users`

The canonical user table. UUID PK as of doc 26. Soft-delete with `deleted_at` + `deleted_by`.

| Column | Type | Notes |
|---|---|---|
| `id` | `VARCHAR(36) PK` | UUID (doc 26) |
| `user_code` | `VARCHAR(50) UNIQUE NULL` | `US-XXXX-YYMMDDHHMMSS` (doc 25) |
| `login` | `VARCHAR(255) UNIQUE NOT NULL` | |
| `email` | `VARCHAR(255) UNIQUE NOT NULL` | |
| `hashed_password` | `VARCHAR(255) NOT NULL` | Argon2id |
| `first_name`, `last_name` | `VARCHAR(255) NULL` | |
| `status` | `VARCHAR(50) NOT NULL` | `active` / `inactive` |
| `refresh_token_jti` | `VARCHAR(64) NULL` | Currently-active refresh JTI |
| `refresh_token_expires_at` | `UtcDateTime NULL` | |
| `previous_refresh_token_jti` | `VARCHAR(64) NULL` | Grace slot (doc 19) |
| `previous_refresh_token_jti_valid_until` | `UtcDateTime NULL` | Grace expiry |
| `vendor_id` | `VARCHAR(36) FK → vendors(id) NULL` | |
| `division` | `VARCHAR(32) NULL` | `tmd1` / `tmd2` / `others` |
| `division_other` | `VARCHAR(255) NULL` | Required when `division='others'` |
| `phone_number` | `VARCHAR(50) NULL` | Required at the wire on create (doc 23) |
| `two_factor_enabled` | `BOOLEAN NOT NULL DEFAULT TRUE` | Doc 33 change 3. Doc 35 parity: bootstrap admin forced `True` on every boot (universal-OTP break-glass covers misconfigured dispatch) |
| `created_at`, `updated_at` | `UtcDateTime NOT NULL` | |
| `deleted_at`, `deleted_by` | nullable; `deleted_by` is `VARCHAR(36) FK → users(id)` self-FK | Soft-delete |

### `roles`

Doc-21B shape: no JSON `permissions` column (junction table replaces it).

| Column | Type | Notes |
|---|---|---|
| `id` | `INTEGER PK` | |
| `name` | `VARCHAR(255) UNIQUE NOT NULL` | Seeded: `admin`, `member`, `viewer`, `vendor` |
| `description` | `VARCHAR(1024) NULL` | |
| `builtin` | `BOOLEAN NOT NULL` | True for the four seeded roles |
| `created_at`, `updated_at` | timestamps | |

**Service-layer protections**: `admin` role is locked from delete / rename / permission-set mutation.

### `permissions`

Catalog of `module:action` codes. Built-ins upserted from `app/core/permissions.py` on every boot (`RbacRepository.sync_builtin_permissions`).

| Column | Type | Notes |
|---|---|---|
| `code` | `VARCHAR(128) PK` | E.g. `users:create`, `master_data:manage`, `rbac:assign` |
| `name` | `VARCHAR(255) NOT NULL` | Display label |
| `description` | `VARCHAR(1024) NULL` | |
| `is_builtin` | `BOOLEAN NOT NULL` | Built-ins protected from delete |
| `created_at`, `updated_at` | timestamps | |

### `role_permissions`, `user_roles`, `user_permissions`

Junction tables. Composite PK: `(role_id|user_id, permission_code|role_id)`. `user_roles` and `user_permissions` carry `created_by VARCHAR(36) FK → users(id)`.

### `revoked_tokens`

| Column | Type | Notes |
|---|---|---|
| `jti` | `VARCHAR(64) PK` | |
| `user_id` | `VARCHAR(36) FK → users(id) NULL` | |
| `revoked_at` | `UtcDateTime NOT NULL` | |
| `expires_at` | `UtcDateTime NOT NULL` | Used by housekeeping to prune expired rows |

### `otp_codes` (doc 33 change 3)

2FA OTP rows. Codes hashed at rest (HMAC-SHA256 with `OTP_HASH_PEPPER`).

| Column | Type | Notes |
|---|---|---|
| `id` | `INTEGER PK` | Autoincrement |
| `user_id` | `VARCHAR(36) FK → users(id) NOT NULL` | |
| `channel` | `VARCHAR(16) NOT NULL` | `email` / `sms` |
| `code_hash` | `VARCHAR(128) NOT NULL` | HMAC-SHA256(pepper, plaintext) |
| `ephemeral_token_hash` | `VARCHAR(128) NOT NULL` | Hash of the opaque token returned at `/login` stage 1 |
| `generated_at` | `UtcDateTime NOT NULL` | |
| `expires_at` | `UtcDateTime NOT NULL` | TTL = `OTP_TTL_SECONDS` (default 300s) |
| `consumed_at` | `UtcDateTime NULL` | Set on successful verify (single-use) |
| `attempt_count` | `INTEGER NOT NULL DEFAULT 0` | After `OTP_MAX_ATTEMPTS` the row is auto-consumed |
| `last_sent_at` | `UtcDateTime NOT NULL` | For the `OTP_RESEND_COOLDOWN_SECONDS` cooldown check |

### `password_reset_tokens` (doc 33 change 3)

| Column | Type | Notes |
|---|---|---|
| `id` | `INTEGER PK` | |
| `user_id` | `VARCHAR(36) FK → users(id) NOT NULL` | |
| `channel` | `VARCHAR(16) NOT NULL` | `email` (URL token) / `sms` (numeric OTP) |
| `token_hash` | `VARCHAR(128) UNIQUE NOT NULL` | HMAC-SHA256(pepper, plaintext) |
| `generated_at` | `UtcDateTime NOT NULL` | |
| `expires_at` | `UtcDateTime NOT NULL` | TTL = `PASSWORD_RESET_TTL_SECONDS` (default 3600) |
| `consumed_at` | `UtcDateTime NULL` | Single-use |

### `notification_log` (doc 33 change 3)

Every dispatch recorded regardless of which `NotificationClient` backend handled it. Mock writes the row as the terminal sink; HTTP writes pre-call so failures are visible.

| Column | Type | Notes |
|---|---|---|
| `id` | `INTEGER PK` | |
| `user_id` | `VARCHAR(36) FK → users(id) NULL` | |
| `channel` | `VARCHAR(16) NOT NULL` | |
| `recipient` | `VARCHAR(320) NOT NULL` | Frozen at dispatch time |
| `template_kind` | `VARCHAR(64) NOT NULL` | `otp_login` / `password_reset_link` / `password_reset_otp` / future kinds |
| `payload` | `JSON NULL` | Free-form; **never stores secrets** — codes hashed in their own tables |
| `status` | `VARCHAR(16) NOT NULL DEFAULT 'queued'` | `queued` / `sent` / `failed` |
| `error` | `VARCHAR(500) NULL` | Backend-reported error |
| `created_at` | `UtcDateTime NOT NULL` | |

### `notification_templates` (doc 36)

DB-backed email + SMS template catalog. Replaces hardcoded if/elif/else in renderers. Renderers look up active rows by `(template_kind, channel)` and `str.format_map` over stored copy.

| Column | Type | Notes |
|---|---|---|
| `id` | `INTEGER PK` | |
| `template_kind` | `VARCHAR(64) NOT NULL` | Free-form; built-ins: `otp_login` / `password_reset_link` / `password_reset_otp` |
| `channel` | `VARCHAR(16) NOT NULL` | `email` / `sms` |
| `subject` | `VARCHAR(500) NULL` | Required for email; null for SMS |
| `body` | `TEXT NOT NULL` | HTML for email, plaintext for SMS; `{placeholder}` substitution |
| `is_html` | `BOOLEAN NOT NULL DEFAULT TRUE` | |
| `is_builtin` | `BOOLEAN NOT NULL` | Built-ins protected from hard delete; copy IS editable |
| `active` | `BOOLEAN NOT NULL DEFAULT TRUE` | At-most-one-active per (kind, channel) — Postgres partial unique index + service-layer guard |
| `description` | `VARCHAR(1024) NULL` | Ops note |
| `created_at`, `updated_at` | `UtcDateTime` | |

**Allowed placeholders** validated on PATCH/POST:
- `otp_login` (email + sms): `{code}`, `{ttl_minutes}`
- `password_reset_link` (email): `{reset_url}`, `{token}`, `{ttl_minutes}`
- `password_reset_link` (sms): `{token}`, `{ttl_minutes}`
- `password_reset_otp` (email + sms): `{code}`, `{ttl_minutes}`

### `vendors` (read-only here)

Owned by the monolith. User-mgmt reads `users.vendor_id → vendors.id`.

```
id            VARCHAR(36) PK (UUID)
vendor_code   VARCHAR(50) UNIQUE NULL  (VN-XXXX-YYMMDDHHMMSS)
name          VARCHAR(255) UNIQUE NOT NULL
description   TEXT
active        BOOLEAN
email         VARCHAR(255) NULL
contact_person VARCHAR(255) NULL
phone_number  VARCHAR(50) NULL  (required at wire on create)
deleted_at, deleted_by  (soft-delete)
created_at, updated_at
```

### `projects`, `project_members`, `milestone_vendors`, `project_vendors`

User-mgmt has these mapped only to satisfy SQLAlchemy when traversing relationships. The monolith owns all writes.

---

## 4. Migration coordination — the schema-change runbook

Every schema change to a shared table needs coordinated work across the two repos. **Default**: monolith owns alembic; user-mgmt sets `MIGRATIONS_AUTORUN=false`.

### Adding a column to a shared table

1. **Monolith repo**:
   - Update the model (`app/infrastructure/db/models/<table>.py`).
   - Generate / write the alembic migration in `alembic/versions/`.
   - Update relevant Pydantic schemas, service handlers, tests.
   - Commit + push.
2. **User-mgmt repo**:
   - Update the same model file (mirror the column declaration). The model only needs to match — no alembic migration here.
   - If user-mgmt service paths read or write the column, update them.
   - Commit + push.
3. **Deploy ordering**:
   - Deploy monolith first → alembic runs → schema is at the new revision.
   - Deploy user-mgmt second → its model now matches the live schema.

### Adding a column ONLY user-mgmt cares about (e.g. another auth flag)

Same as above — monolith still owns the alembic migration. User-mgmt's model gets the new column; the monolith's model gets it too even if no monolith handler references it. Otherwise SQLAlchemy on the monolith side errors when reading rows that have the column.

### Renaming / dropping columns

Avoid in shared-DB deploys. Use the standard "expand → migrate → contract" pattern: add a new column, dual-write for one release, switch readers to the new column, drop the old in a follow-up.

---

## 5. Doc references

- doc 21B — DB-driven RBAC (permissions / role_permissions / user_roles / user_permissions; drop legacy `roles.permissions` JSON).
- doc 23 — `users.phone_number` + vendor contact details.
- doc 25 — `userCode` / `vendorCode` human-readable display IDs.
- doc 26 — `users.id` flipped from `INTEGER` to `VARCHAR(36)` UUID.
- doc 27 — `UtcDateTime` column type for IST/UTC equality safety.
- doc 33 change 3 — 2FA + password reset + notification audit (`otp_codes`, `password_reset_tokens`, `notification_log`).
- doc 36 — `notification_templates` (DB-backed renderer).
- doc 37 part 2 — this service brought to monolith parity + monolith proxy.
