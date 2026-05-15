# pmis-notification-management — Migration Log

First service ported in Phase 3 per Q19/Q29. Source: `C:\Programming\PMIS\PMIS-notification-service`. Post-refactor this service owns NO tables (Q3 moved `notification_templates` to masters-svc; Q13 moved OTP storage to `users.otp_codes`). It is a stateless dispatcher that reads `masters.notification_templates` and `users.*` / `project.*` cross-schema.

## Source

- Sibling extraction (canonical port source): `C:\Programming\PMIS\PMIS-notification-service\app\…`
- Monolith parallel callers (for inbound-contract reference):
  - `C:\Programming\PMIS\PMIS-OpenProject\app\shared\notifications.py:339` (calls `/email/send`)
  - `C:\Programming\PMIS\PMIS-OpenProject\app\shared\notifications.py:354` (calls `/sms/send`)
  - `C:\Programming\PMIS\PMIS-user-management\app\shared\notifications.py:168` (calls `/dispatch`)

## Endpoint port table

| METHOD | NEW PATH | HANDLER (new file:line) | SOURCE HANDLER (path:line) | NOTES |
|---|---|---|---|---|
| POST | `/notification/email/send` | `app/routes/email_routes.py:25` (`send_email`) | `C:\Programming\PMIS\PMIS-notification-service\app\routes\email_routes.py:21` | Prefix changed from `/api/v1/notifications/email/send`. Behavior unchanged. EmailController unchanged. |
| POST | `/notification/sms/send` | `app/routes/sms_routes.py:25` (`send_sms`) | `C:\Programming\PMIS\PMIS-notification-service\app\routes\sms_routes.py` (parallel to email_routes) | Prefix changed. Behavior unchanged. |
| POST | `/notification/dispatch` | `app/routes/dispatch_routes.py:25` (`dispatch_templated`) | `C:\Programming\PMIS\PMIS-notification-service\app\routes\dispatch_routes.py:38-67` | Inline route logic extracted to `DispatchService` (Q8). Prefix changed from `/api/v1/notifications/dispatch`. |
| POST | `/notification/cron/daily-digest` | `app/routes/cron_routes.py:46` (`daily_digest`) | `C:\Programming\PMIS\PMIS-notification-service\app\routes\cron_routes.py:70-104` | Module-level `run_daily_digest` wrapped in `DigestService` class (Q8). 503/401 raise `CronUnauthorizedError` instead of `HTTPException` (PLAN.md §2.6). Prefix changed. |
| GET | `/health` | `app/routes/health_routes.py:18` (`health`) | `C:\Programming\PMIS\PMIS-notification-service\app\routes\health_routes.py:8` | Response shape narrowed to `HealthResponse` Pydantic model (uniform across services); dropped `env/email_provider/sms_provider` fields. |
| GET | `/ready` | `app/routes/health_routes.py:40` (`ready`) | **NEW** per Decision 8d | DB ping (`SELECT 1`). Returns 503 on failure. |
| GET | `/` | `app/main.py:101` (`root`) | `C:\Programming\PMIS\PMIS-notification-service\app\main.py:68-75` | Same shape; description aligned with new service identity. |

### Endpoints intentionally NOT ported

| Old endpoint | Reason | Successor |
|---|---|---|
| `POST /api/v1/notifications/otp/send` | Q13: notification-svc no longer tracks OTP state. | `POST /user/users/login/send-otp` (canonical) |
| `POST /api/v1/notifications/otp/verify` | Q13: verify lives in user-svc against `users.otp_codes`. | `POST /user/users/login/verify-otp` |
| `GET /api/v3/master/notification_templates` | Q3: catalog moved to masters-svc. | `GET /masters/notification-templates/list` (masters-svc) |
| `GET /api/v3/master/notification_templates/{id}` | Q3 | `GET /masters/notification-templates/{id}/details` |
| `POST /api/v3/master/notification_templates/create` | Q3 | `POST /masters/notification-templates/create` |
| `PATCH /api/v3/master/notification_templates/{id}` | Q3 | `PATCH /masters/notification-templates/{id}/update` |
| `DELETE /api/v3/master/notification_templates/{id}` | Q3 | `DELETE /masters/notification-templates/{id}/delete` |
| `POST /api/v3/master/notification_templates/{id}/restore` | Q3 | `POST /masters/notification-templates/{id}/restore` |

## Models ported (owned by this service)

| Table | New model (file:line) | Source (path:line) | Schema changes vs source |
|---|---|---|---|
| _(none)_ | — | — | Service owns no tables post-refactor (Q3 + Q13). |

## Cross-schema mirrors (read-only, declared on `MirrorBase`)

| Mirrored table | New mirror (file:line) | Source canonical |
|---|---|---|
| `masters.notification_templates` | `app/models/_cross_schema.py:51` (`NotificationTemplate`) | Was `C:\Programming\PMIS\PMIS-notification-service\app\db\models\notification_template.py:22` — moves to masters-svc per Q3. **Will live at `services/pmis-masters-management/app/models/notification_template.py` when masters-svc is ported.** |
| `users.users` | `app/models/_cross_schema.py:73` (`User`) | `C:\Programming\PMIS\PMIS-user-management\app\infrastructure\db\models\user.py:23` |
| `users.roles` | `app/models/_cross_schema.py:90` (`Role`) | `C:\Programming\PMIS\PMIS-user-management\app\infrastructure\db\models\role.py:21` |
| `users.user_role_assignments` | `app/models/_cross_schema.py:100` (`UserRoleAssignment`) | `C:\Programming\PMIS\PMIS-user-management\app\infrastructure\db\models\user_role_assignment.py:44` |
| `project.projects` | `app/models/_cross_schema.py:115` (`Project`) | `C:\Programming\PMIS\PMIS-project-management\app\infrastructure\db\models\project.py:23` |
| `project.milestones` | `app/models/_cross_schema.py:126` (`Milestone`) | `C:\Programming\PMIS\PMIS-project-management\app\infrastructure\db\models\milestone.py:24` |
| `project.activities` | `app/models/_cross_schema.py:139` (`Activity`) | `C:\Programming\PMIS\PMIS-project-management\app\infrastructure\db\models\activity.py:16` |
| `project.project_vendors` | `app/models/_cross_schema.py:152` (`ProjectVendor`) | `C:\Programming\PMIS\PMIS-project-management\app\infrastructure\db\models\project_vendor.py:18` |

**Drift safety:** Q24 CI test in `services/pmis-user-management/tests/test_cross_schema_drift.py` (to be written when user-svc is ported) will assert these mirrors stay in sync with the canonical declarations. Until then, every canonical source file carries a `WARNING:` header listing its mirrors (PLAN.md §2.5).

## Alembic migrations

| Revision | Description | Type |
|---|---|---|
| _(none yet)_ | The alembic chain is intentionally EMPTY — no owned tables. The version table `notification.alembic_version_notification` exists for symmetry only. | — |

`app/alembic/env.py` is set up to honor the convention (`include_object` filter excludes `MirrorBase` declarations from autogenerate) so a future migration here cannot accidentally create a mirrored table.

## Cross-service HTTP calls

| FROM (file:line) | TO | METHOD | Purpose |
|---|---|---|---|
| _(none)_ | — | — | notification-svc reads cross-schema; never makes outbound PMIS-service HTTP calls. |

Outbound to external providers (unchanged from source):
- `app/services/email_service.py:99` → SMTP `settings.smtp_host:settings.smtp_port` OR SendGrid `https://api.sendgrid.com/v3/mail/send`
- `app/services/sms_service.py:60` → Twilio REST (`twilio.rest.Client`) OR MSG91 `https://api.msg91.com/api/sendhttp.php`

## Layer-by-layer port summary

| Layer | Files | Notes |
|---|---|---|
| `core/` | `errors.py`, `response.py` | New: `DomainError` hierarchy (`ProviderError`, `CronUnauthorizedError`, etc.), HAL envelope formatters. Replaces ad-hoc `HTTPException(502)` raises in source. |
| `middleware/` | `request_context.py`, `error_handler.py` | Ported from source `app/middleware/*`. Added `DomainError` exception handler (translates to `code+message+details` envelope). Removed `AuthMiddleware` (no JWT-required routes). |
| `utilities/` | `logger.py`, `timezones.py` | Logger gained `JsonFormatter` for `LOG_FORMAT=json`. |
| `models/_cross_schema.py` | 1 file | NEW. Read-only mirrors for cross-schema joins. Excluded from alembic autogen. |
| `schemas/` | `email.py`, `sms.py`, `dispatch.py`, `digest.py`, `common.py` | Ported with full Pydantic v2 conventions (`ConfigDict`, `Annotated[T, Field(...)]`, per-field `description=`). Added `HealthResponse` / `ReadyResponse` / `ErrorEnvelope` in `common.py`. |
| `repositories/` | `notification_template_repository.py`, `digest_repository.py` | New repo class for templates (reads cross-schema). New `DigestRepository` extracts queries from `digest_service.py:100-203` (PLAN.md §1.2: queries live in repos). |
| `services/` | `email_service.py`, `sms_service.py`, `template_service.py`, `dispatch_service.py`, `digest_service.py` | Provider strategy preserved (SMTP/SendGrid; mock/twilio/msg91). `template_service` and `digest_service` converted from module-level functions to classes (Q8). `EmailProviderError` / `SMSProviderError` replaced with `core.errors.ProviderError`. |
| `controllers/` | 4 files (email/sms/dispatch/cron) | Per Q8 — every resource has a thin HTTP-adapter layer. |
| `routes/` | 6 files (email/sms/dispatch/cron/health + `__init__.py`) | New `/notification/*` prefix per PLAN.md §2.4. Verb suffixes on terminal nouns (none needed — all paths end in verbs like `/send`, `/dispatch`, `/daily-digest`). |
| `dependencies.py` | 1 file | Centralized FastAPI `Depends()` factories. |
| `main.py` | 1 file | Replaced scaffold stub. Drops AuthMiddleware, master_data_router, and `init_db()` boot-time DDL. CORS gated on `ENV=development` per Decision 8e. |

## Tests

| Layer | Count | Coverage |
|---|---|---|
| Unit (`tests/unit/`) | 4 (template_service render fallback, ttl_minutes computation, missing placeholder handling) | TemplateService — most logic-heavy module |
| Integration (`tests/integration/`) | 18 across 5 files (health × 4, email_send × 3, sms_send × 3, dispatch × 3, cron × 5) | One happy-path + one validation-failure path per endpoint; cron tested for both 401 modes (mismatched / not-configured) |
| Parity | 0 (deferred) | Will run after `tools/capture_fixtures.py` captures monolith fixtures (Phase 3 follow-up). |
| Cross-schema drift | 0 here (lives in user-svc) | Q24 CI test will be written when user-svc is ported. |

All tests are TestClient-based and use `app.dependency_overrides[...]` to substitute the real Postgres session and provider clients. No tests require external infrastructure to pass.

To run locally:
```bash
cd services/pmis-notification-management
pip install -r requirements.txt
pytest -q
```

## OpenAPI / Swagger quality (docs/OPENAPI_QUALITY.md)

- [x] Every route decorator has `summary` (≤60 chars, sentence case)
- [x] Every route decorator has `description` (one paragraph, explains what + when + returns)
- [x] Tags grouped per resource (`email`, `sms`, `dispatch`, `cron`, `health`)
- [x] Request bodies use Pydantic schemas with `description=` on each `Field(...)`
- [x] `response_model=` set on every endpoint
- [x] 4xx/5xx documented via `responses={...}` (added on `/ready` for the 503 case; cron secret failures emit `code` in the envelope)
- [x] No file-upload endpoints in this service (N/A)
- [x] No `deprecated=True` endpoints (per Q13 we dropped the OTP aliases rather than retain them)
- [x] Auth requirement implicit (cron uses `_verify_cron_secret` dependency; others are unauthenticated by design)

## Open issues / deviations

| Issue | Disposition |
|---|---|
| Cross-schema mirror declarations point at masters/users/project schemas that don't exist on disk yet (masters-svc, user-svc, project-svc not yet ported). | Acceptable. The mirrors are pure column declarations; they don't reference anything outside this service at the Python level. At runtime they need the schemas to exist in Postgres — that happens at cutover when the other services' alembic chains run. |
| Parity tests have no fixtures yet. | Captured in Phase 3 follow-up via `tools/capture_fixtures.py` once monolith is running locally. |
| `Q24` cross-schema drift CI test not present. | Lives in `services/pmis-user-management/tests/test_cross_schema_drift.py` — will be written when user-svc is ported (next-but-one service in the order). |
| The `init_db()` template-seeding logic from source (`session.py:96-207`) is NOT ported here. | Intentional. Per Q3, masters-svc owns the templates and its bootstrap alembic data-migration seeds the built-in templates. This service does not seed. |
| Source's `SessionManager` and `OTPService` (in-memory dict) are absent here. | Intentional. Per Q13, OTP state is owned by user-svc. notification-svc has no OTP storage. |
| `controllers/` layer present even for the trivial `EmailController` (one method, no logic). | Intentional per Q8. Adds one indirection level for predictability. |

## Approval

- [ ] All ported routes match the endpoint plan in PLAN.md §2.4
- [ ] OpenAPI quality bar (`docs/OPENAPI_QUALITY.md`) passes — confirmed by inspection above
- [ ] Integration tests pass against the test stack (`pytest -q` clean)
- [ ] Parity tests deferred to follow-up (acceptable per Q34: scaffold tests now, capture fixtures later)
- [ ] Cross-schema drift test deferred to user-svc port
- [ ] User approval to proceed to `pmis-masters-management` ☐
