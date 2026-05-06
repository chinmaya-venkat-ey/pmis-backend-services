# Doc 38 phase 2: don't re-introduce local template rendering here

## What it means

`HttpNotificationClient.send` in [app/shared/notifications.py](../app/shared/notifications.py) is now a **thin pass-through**. It posts `{channel, recipient, template_kind, payload, user_id}` to PMIS-notification-service's `POST /api/v1/notifications/dispatch` and writes an audit row to the local `notification_log` table. It does **not** look up templates, render placeholders, compute `ttl_minutes`, or build `reset_url` — all of that is owned by notification-service's [`app/services/template_service.py`](https://github.com/EY-DIGIT/PMIS-notification-service/blob/dev/app/services/template_service.py).

The `notification_templates` table is also **not** present in this service's DB layer anymore — the model file was deleted in commit `7dae3b5`, and the bootstrap seed loop was removed. There's no local catalog to read.

## Why this matters for future work

It's tempting to "just look up the template here" when something seems easier — e.g. when adding a new template kind, or when wanting to short-circuit a dispatch for a tested-locally code path. Resist it:

- **New template kinds go in notification-service**, not here. Add them to `app/services/template_service.py` (`_compute_placeholders` block + fallback rules) and to `app/schemas/notification_template.py::ALLOWED_PLACEHOLDERS`. Add a seed row in `app/db/session.py::_TEMPLATE_SEED` if it should ship as a builtin.
- **Don't add a NotificationTemplateModel back here.** Every read/write goes over HTTP to notification-service.
- **Don't add a renderer here.** If a placeholder isn't substituting the way you expect, fix it in notification-service's `template_service.py` and rerun your test against that service. Don't paper over it with local logic.

## What stays here

- [`MockNotificationClient`](../app/shared/notifications.py) for tests / dev — writes to `notification_log` without an HTTP call. That's intentional — tests want the audit-row check to be the assertion target without spinning up a real notification-service.
- The `notification_log` table itself — that's user-mgmt's own audit table for who-tried-to-send-what.
- The well-known kind constants (`TEMPLATE_OTP_LOGIN`, `TEMPLATE_PASSWORD_RESET_LINK`, `TEMPLATE_PASSWORD_RESET_OTP`) — call sites use them as identifiers when invoking `client.send(template_kind=...)`. They name the contract; they don't define the rendering.

## How to verify the contract is intact

The 7 tests in [`tests/test_doc33_2fa_and_password_reset.py::TestHttpNotificationClient`](../tests/test_doc33_2fa_and_password_reset.py) assert the wire shape (POST to `/dispatch`, body keys, audit row state). If you change anything in `app/shared/notifications.py`, those tests are the canary. Render-correctness tests live in PMIS-notification-service's `tests/test_dispatch.py`.
