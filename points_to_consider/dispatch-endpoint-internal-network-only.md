# `/api/v1/notifications/dispatch` is currently unauthenticated — internal-network only

## What it means

The dispatch endpoint added in doc 38 phase 2 ([app/routes/dispatch_routes.py](../app/routes/dispatch_routes.py)) accepts any caller that can reach the service over HTTP. It does **not** require a Bearer token, an API key, or an mTLS cert. It looks up the requested template, renders it, and dispatches via the configured email/SMS provider — no authn, no rate limit.

This matches the existing `/api/v1/notifications/email/send`, `/sms/send`, and `/otp/send` siblings, which are also unauthenticated. The intended deployment is:

- Pod / VM lives on a private network reachable only from monolith + user-mgmt
- Public ingress only exposes monolith's `/api/v3/*` surface
- `/api/v1/*` is intentionally **not** routed by the public ingress

## Why this matters for future work

If anything below changes, `/dispatch` becomes a footgun:

- **Public exposure.** If notification-service starts serving traffic from a public LB (e.g. a future "send a notification from FE" feature), `/dispatch` becomes an open SMS / email relay. Anyone could pass arbitrary `recipient` + `payload` and get a real provider call. SMS abuse cost is non-trivial — Twilio outbound to international numbers is real money.
- **Multi-tenant isolation.** `/dispatch` doesn't bind a `user_id` to "the caller's identity" — `user_id` is just an opaque audit hint. If we ever add tenants, a misbehaving tenant could spoof another tenant's `user_id` field. The audit row would lie.
- **Template content control.** Rendering happens server-side, so the caller can't inject HTML directly — they can only fill the placeholders the template author defined. This is a real safety boundary, but it disappears the moment we add a "free-form body" parameter for convenience.

## Before exposing publicly, do at least

1. Move `/dispatch` (and the legacy `/email/send`, `/sms/send`) under the same `AuthMiddleware` that already protects `/api/v3/master/*`. Require a service-token or Bearer.
2. Add per-caller rate limiting keyed on the authenticated identity, not on IP.
3. Validate `recipient` against an allowlist for the calling tenant if multi-tenancy lands.
4. Decide whether `user_id` is "audit hint" or "authenticated subject" — they're different concepts. Right now it's the former.

## What stays internal-only

- `/api/v1/notifications/dispatch`
- `/api/v1/notifications/email/send`
- `/api/v1/notifications/sms/send`
- `/api/v1/notifications/otp/send` and `/verify`

## What is already auth-gated

- `/api/v3/master/notification_templates/*` (via [app/middleware/auth_middleware.py](../app/middleware/auth_middleware.py)) — JWT + `master_data:view` / `master_data:manage`. This is the FE-facing surface and should stay gated.
