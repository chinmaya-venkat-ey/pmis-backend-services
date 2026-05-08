# Authentication and Security — pmis-user-service

This service is the authoritative gate for every user/auth flow in PMIS. The monolith verifies JWTs locally with the same `SECRET_KEY` for downstream calls (project-management routes), but **token issuance + refresh + RBAC + 2FA + password reset all happen here**.

---

## 1. Login flow

### Single-stage (when 2FA is off)

```
POST /api/v3/users/login
{"login": "admin", "password": "admin123"}
```

Response (200):
```json
{
  "data": {
    "_type": "Login",
    "access_token": "...",
    "token_type": "bearer",
    "refresh_token": "...",
    "accessTokenExpiresAt":  "2026-04-28T18:15:00+00:00",
    "accessTokenIssuedAt":   "2026-04-28T18:00:00+00:00",
    "refreshTokenExpiresAt": "2026-05-05T18:00:00+00:00",
    "refreshTokenIssuedAt":  "2026-04-28T18:00:00+00:00",
    "expiresInSeconds": 900,
    "user": { ... }
  }
}
```

### 2FA challenge (when `users.two_factor_enabled=True` AND `REQUIRE_2FA=true`)

The same login call returns a different shape:

```json
{
  "data": {
    "_type": "LoginOtpRequired",
    "requires_otp": true,
    "ephemeral_token": "<opaque session handle>",
    "channels_available": ["email", "sms"],
    "message": "Two-factor authentication required..."
  }
}
```

`channels_available` includes `sms` only if the user has a `phoneNumber` recorded.

The FE sees `requires_otp` and follows up with two more calls.

### Two-factor steps

**Step 1 — `POST /api/v3/users/login/send-otp`**

```json
{
  "ephemeral_token": "<from /login response>",
  "channel": "email"
}
```

Returns `{expires_in_seconds, resend_after_seconds}`. The OTP itself is **never returned in the HTTP response** even with `NOTIFICATION_CLIENT=mock`. In mock mode the dispatched payload (including the plaintext code) is recorded in `notification_log`:

```sql
SELECT payload FROM notification_log
 WHERE template_kind = 'otp_login' AND user_id = '<user_uuid>'
 ORDER BY created_at DESC LIMIT 1;
```

With `NOTIFICATION_CLIENT=http` the code goes to PMIS-notification-service.

Cooldown — calls within `OTP_RESEND_COOLDOWN_SECONDS` (default 60) return **429**.

**Step 2 — `POST /api/v3/users/login/verify-otp`**

```json
{
  "ephemeral_token": "<same as send-otp>",
  "code": "123456"
}
```

Success returns the same shape as the single-stage Shape A above (real JWT pair).

Failure modes (all 401):
- Wrong code → attempt counter increments; after `OTP_MAX_ATTEMPTS` the OTP row is consumed.
- Expired (older than `OTP_TTL_SECONDS`) → "expired".
- Already verified (single-use) → "consumed".

### Universal OTP (break-glass)

When `UNIVERSAL_OTP_ENABLED=true`, `/login/verify-otp` accepts `UNIVERSAL_OTP_CODE` (default `000000`) for any user. The active OTP session row is still required — the user must have completed the password step + chosen a channel — but code verification short-circuits. Used for environments where email/SMS dispatch is broken.

**MUST be False in production.** `/health` surfaces the flag for external visibility.

### Per-user 2FA toggle

Admin updates the flag via `PATCH /api/v3/users/{id}` (permission: `users:update`):

```json
{ "twoFactorEnabled": false }
```

This is the supported way to opt service accounts and on-call automation out of the OTP step.

---

## 2. Token mechanics

| Setting | Default | Purpose |
|---|---|---|
| Algorithm | HS256 | |
| Access token TTL | 15 min | `ACCESS_TOKEN_EXPIRE_MINUTES` |
| Refresh token TTL | 7 days | `REFRESH_TOKEN_EXPIRE_DAYS` |
| Refresh grace window | 120s | `REFRESH_TOKEN_GRACE_SECONDS` — the just-rotated-out jti is held alongside the current one for this many seconds so concurrent refresh races / multi-tab logins / stale retry queues don't get locked out by the atomic swap |

### JWT payload

```json
{
  "sub":     "admin",
  "user_id": "8bd99f06-5f2a-424c-aaff-10ab163c3e42",
  "email":   "admin@example.com",
  "jti":     "...",
  "iat":     ...,
  "exp":     ...
}
```

- `user_id` is a UUID string (post-doc-26).
- `role` and `is_admin` are NOT in the JWT — they're resolved from the DB on every request. Demoting a user takes effect on their next request, not at the next refresh boundary.
- Pre-doc-26 tokens carrying an integer `user_id` are rejected with 401 (not 500) by the auth middleware.

### Token rotation

`POST /api/v3/users/refresh` with `{refresh_token: <jwt>}` returns a fresh access + refresh pair. After rotation, the previous JTI is held in `users.previous_refresh_token_jti` for `REFRESH_TOKEN_GRACE_SECONDS`. During the window, either the current OR the previous JTI is accepted.

### Token revocation

`POST /api/v3/users/logout` adds the access JTI to `revoked_tokens` and clears all four refresh-tracking columns (`refresh_token_jti`, `refresh_token_expires_at`, `previous_refresh_token_jti`, `previous_refresh_token_jti_valid_until`). The auth middleware checks the blacklist on every request.

### Introspection

`POST /api/v3/users/introspect` (RFC 7662) — read-only metadata, never rotates. Body: `{access_token?, refresh_token?}` (provide at least one). Inactive / expired / revoked / unparseable → `{"active": false, "tokenType": ...}` at HTTP 200 (not 401).

---

## 3. Password reset (forgot-password / reset-password)

Anti-enumeration: `/forgot-password` always returns 200 regardless of whether the account exists.

**Step 1 — `POST /api/v3/users/forgot-password`**

```json
{
  "login_or_email": "admin",
  "channel": "email"
}
```

Always 200. If the account exists, the server generates either:
- **email channel** — URL-safe random token (32 bytes) sent via the `password_reset_link` template.
- **sms channel** — 6-digit numeric OTP sent via the `password_reset_otp` template.

Both forms are HMAC-SHA256-hashed (with `OTP_HASH_PEPPER`, falls back to `SECRET_KEY`) and stored in `password_reset_tokens`. Plaintext only exists in transit / in the notification payload.

**Step 2 — `POST /api/v3/users/reset-password`**

```json
{
  "token_or_code": "<URL token from email OR 6-digit OTP from SMS>",
  "new_password": "newSecret123"
}
```

Single-use. Successful reset clears the user's refresh-token slots (existing sessions invalidated). TTL: `PASSWORD_RESET_TTL_SECONDS` (default 3600 / 1 hour).

Failure modes (all 401): expired / invalid / consumed.

---

## 4. Password storage

- **Argon2id** via argon2-cffi. Bcrypt fallback for legacy hashes (rare).
- Minimum length: 8 characters.
- Pepper: not used at the password-storage layer (only at the OTP / reset-token storage layer via `OTP_HASH_PEPPER`).
- Never logged, never returned in any response.

---

## 5. Middleware stack

```
LoggingMiddleware            X-Request-ID + duration logging
   │
   ▼
AuthenticationMiddleware     JWT decode + revoked-jti check + permission set hydration
   │
   ▼  request.state populated for downstream
   ▼
require_permission(...)      FastAPI dependency
   │
   ▼
Route handler
```

For the full per-request flow including how `request.state.user_permissions` gets populated, see [RBAC_GUIDE.md](./RBAC_GUIDE.md) §8.

---

## 6. Public endpoints (no auth)

- `GET /` — root
- `GET /health` — health check
- `POST /api/v3/users/login` — auth boundary
- `POST /api/v3/users/login/send-otp` — gated by ephemeral_token
- `POST /api/v3/users/login/verify-otp` — gated by ephemeral_token + OTP
- `POST /api/v3/users/forgot-password` — anti-enumeration always-200
- `POST /api/v3/users/reset-password` — gated by reset token
- `POST /api/v3/users/refresh` — gated by refresh token
- `POST /api/v3/users/introspect` — public read-only metadata
- `GET /docs` / `GET /openapi.json` / `GET /redoc` — Swagger / OpenAPI

Everything else under `/api/v3/*` requires a valid Bearer token.

---

## 7. Production security checklist

- [ ] `SECRET_KEY` is 32+ chars, randomly generated, **identical** to the monolith's value (otherwise JWTs from this service fail verification on the monolith side).
- [ ] `BOOTSTRAP_ADMIN_PASSWORD` rotated immediately after first boot.
- [ ] `OTP_HASH_PEPPER` set to a deployment-unique value (don't fall back to `SECRET_KEY` in prod).
- [ ] `NOTIFICATION_CLIENT=http` and `NOTIFICATION_SERVICE_URL` configured (otherwise OTPs only land in `notification_log`).
- [ ] `REQUIRE_2FA=true` for production (per-user opt-out via `users.two_factor_enabled=False`).
- [ ] `UNIVERSAL_OTP_ENABLED=false` (the universal-OTP break-glass is for dev / staging only).
- [ ] `CORS_ORIGINS` set to specific FE domains (not `["*"]`).
- [ ] HTTPS enforced at the load-balancer / ingress.
- [ ] Database connection over TLS.

---

## 8. Cross-service token verification

Tokens minted here verify successfully on the monolith because both services use the same `SECRET_KEY`. No introspection RPC needed. The monolith's auth middleware decodes the JWT, looks up the user's permissions from the shared DB, and serves protected project-management routes — completely independent of whether user-mgmt is reachable at that moment.

This is the headline benefit of the strangler pattern with stateless JWT: **once a user is logged in, project-management traffic never hops through user-mgmt.**

---

## 9. Troubleshooting

| Status | Cause |
|---|---|
| 401 + "Authentication required" | Token missing or expired. Login again. |
| 401 + "Invalid token" | Wrong signature, malformed, blacklisted (revoked), or pre-doc-26 integer-id JWT. |
| 403 + "Insufficient permissions" | Token good but the route's required code is not in the user's effective set. Check `GET /users/me/permissions`. |
| 429 + "Too soon" | OTP resend within the cooldown window. Wait `resend_after_seconds`. |
| 503 + "User service unavailable (proxy)" | You hit the monolith with the proxy on, but user-mgmt is down. Set `USER_SERVICE_PROXY_ENABLED=false` on the monolith to fall back to its (frozen, doc-37-vintage) local handlers. |

For RBAC-specific errors (last-admin lockout, admin role mutation), see [RBAC_GUIDE.md](./RBAC_GUIDE.md) §6.
