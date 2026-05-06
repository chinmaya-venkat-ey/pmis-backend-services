# Testing and Quality — pmis-user-service

How tests work in this repo, how to run them, and what's covered vs. pending.

---

## 1. Test framework

- pytest + FastAPI `TestClient`.
- SQLite in-memory DB per test, app `init_db` short-circuited in the test fixture so each test starts from a clean slate.
- Test DB schema rebuilt via `Base.metadata.create_all` (no alembic in tests).

---

## 2. Running

```bash
# Activate venv first
.venv/Scripts/Activate.ps1   # PowerShell
# OR
source .venv/bin/activate    # bash / zsh

# Full suite
python -m pytest tests/ -q

# Single file
python -m pytest tests/test_auth.py -q

# With coverage
python -m pytest tests/ --cov=app --cov-report=html
```

If running tests against the monolith's venv (which has all deps installed):

```bash
c:/Programming/PMIS/PMIS-OpenProject/.venv/Scripts/python.exe -m pytest tests/ -q
```

---

## 3. Smoke tests (manual)

The tests below were used to verify doc 37 part 2 end-to-end. They're documented here so the pattern is easy to repeat.

### 3a. User-mgmt standalone

```powershell
# Start user-mgmt with fresh in-memory schema
$env:DATABASE_URL = "sqlite:///c:/tmp/pmis-test/usermgmt.db"
$env:MIGRATIONS_AUTORUN = "false"
$env:REQUIRE_2FA = "false"
$env:SECRET_KEY = "shared-test-secret-key-32-chars-min-shared-test"
$env:NOTIFICATION_CLIENT = "mock"

# Create schema
python -c "from app.infrastructure.db.session import Base, engine; import app.infrastructure.db.models; Base.metadata.create_all(bind=engine)"

# Boot
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

In another shell:

```bash
# Health
curl http://127.0.0.1:8001/health
# {"status":"ok","service":"pmis-user-service","version":"0.1.0","secret_key_sha256_prefix":"a24717c1eed8"}

# Login
TOKEN=$(curl -s -X POST -H "Content-Type: application/json" \
  -d '{"login":"admin","password":"admin123"}' \
  http://127.0.0.1:8001/api/v3/users/login \
  | grep -oE '"access_token":"[^"]*"' | cut -d'"' -f4)

# Me
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8001/api/v3/users/me

# Notification templates
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8001/api/v3/master/notification_templates
```

Expected: 6 seeded templates returned. RBAC seed populated 4 built-in roles + the canonical permission registry.

### 3b. End-to-end with monolith proxy

This was the doc-37-part-2 smoke test. Both services run side-by-side with the monolith proxying to user-mgmt:

```powershell
# Terminal 1 — user-mgmt on 8001
$env:DATABASE_URL = "sqlite:///c:/tmp/pmis-test/usermgmt.db"
$env:MIGRATIONS_AUTORUN = "false"
$env:REQUIRE_2FA = "false"
$env:SECRET_KEY = "shared-test-secret-key-32-chars-min-shared-test"
$env:NOTIFICATION_CLIENT = "mock"
uvicorn app.main:app --port 8001
```

```powershell
# Terminal 2 — monolith on 8000 with proxy ON
cd c:/Programming/PMIS/PMIS-OpenProject
$env:DATABASE_URL = "sqlite:///c:/tmp/pmis-test/monolith.db"
$env:MIGRATIONS_AUTORUN = "false"
$env:SECRET_KEY = "shared-test-secret-key-32-chars-min-shared-test"
$env:USER_SERVICE_PROXY_ENABLED = "true"
$env:USER_SERVICE_URL = "http://127.0.0.1:8001"
uvicorn app.main:app --port 8000
```

```bash
# Login THROUGH MONOLITH — should be proxied
TOKEN=$(curl -s -X POST -H "Content-Type: application/json" \
  -d '{"login":"admin","password":"admin123"}' \
  http://127.0.0.1:8000/api/v3/users/login \
  | grep -oE '"access_token":"[^"]*"' | cut -d'"' -f4)

# /users/me through monolith — proxied to user-mgmt
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v3/users/me

# /master/notification_templates through monolith — proxied
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v3/master/notification_templates

# /master/divisions through monolith — NOT proxied (project-management territory)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v3/master/divisions
```

Verify in user-mgmt's log: requests for `/api/v3/users/me` and `/api/v3/master/notification_templates` show up. Requests for `/api/v3/master/divisions` do NOT (handled locally by monolith).

### 3c. Fail-closed verification

Kill user-mgmt while the proxy is on. Re-issue a login through the monolith:

```bash
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"login":"admin","password":"admin123"}' \
  http://127.0.0.1:8000/api/v3/users/login

# Expected:
# HTTP 503
# {"error":{"_type":"Error","errorIdentifier":"user_service_unavailable",
#  "message":"User service unavailable (proxy). Set USER_SERVICE_PROXY_ENABLED=false ..."},
#  "status":503}
```

The monolith does NOT fall back to its frozen-as-of-doc-37 local user handlers — fail-closed by design. To rollback: set `USER_SERVICE_PROXY_ENABLED=false` on the monolith.

---

## 4. Automated test coverage

### Currently covered

- `tests/test_auth.py` — login (single-stage + 2FA), refresh, logout, introspect.
- `tests/test_users.py` — user CRUD + last-admin lockout.
- `tests/test_rbac.py` (when ported from monolith) — DB-driven RBAC: permission catalog CRUD, role-permission management, user-role assignment, /me/permissions, master-router relocation.

### Pending port from monolith

These test files exist in the monolith and would give meaningful end-to-end coverage if ported here. The monolith's `tests/test_doc37_user_service_proxy.py` already covers the wire-shape contract from the proxy side, so this is a nice-to-have but not blocking:

- `test_doc33_2fa_and_password_reset.py` — 26 tests across 7 classes covering the 2FA + forgot-password + notification log flows.
- `test_doc36_notification_templates.py` — 17 tests covering template CRUD, placeholder validation, renderer DB-lookup, fallback-when-missing.

To port: copy from `PMIS-OpenProject/tests/`, fix the import paths (`app.infrastructure...` works the same in both repos because both packages are named `app`), and run.

---

## 5. Test conventions

### Fixtures

`tests/conftest.py` provides:

- `client` — FastAPI `TestClient` against an in-memory SQLite app. Patches the module-level engine + `init_db` so calls during boot don't hit the real DB.
- `db_session` — raw SQLAlchemy session bound to the test DB.
- `admin_user` / `member_user` — test users assigned to the seeded `admin` / `member` roles. Both have `two_factor_enabled=False` so the standard 2FA test pattern doesn't fire on every test.
- `admin_token` / `member_token` / `admin_headers` / `member_headers` — JWT helpers.
- `_seed_notification_templates` (autouse) — seeds the 6 built-in notification templates so renderer tests don't fall back to the generic body.

### Test style

- `arrange / act / assert` pattern, clear class organization (`class TestLogin: def test_admin_can_login(...)`).
- One test per behavior, not per scenario. Use parametrize sparingly.
- Assertions on response status + key field, not on exact JSON shape (which churns).
- Negative cases (403, 422, 409) are first-class — don't only test the happy path.

---

## 6. Code quality

### Strengths

- Clean layered architecture (Routes → Controllers → Services → Repositories) — same as monolith.
- Type-safe at every boundary (Pydantic on the wire, dataclasses in domain, SQLAlchemy in repos).
- DB-driven RBAC: permissions are extensible at runtime; per-request hydration is one indexed JOIN.
- HAL+JSON envelope is centralized — controllers don't hand-roll responses.
- Mock notification client lets every test exercise the real renderer + audit-row write without external dependencies.

### Production recommendations

- `OTP_HASH_PEPPER` set to a deployment-unique value, not falling back to `SECRET_KEY`.
- `NOTIFICATION_CLIENT=http` configured (otherwise OTPs only land in `notification_log`).
- `REQUIRE_2FA=true` per environment.
- `UNIVERSAL_OTP_ENABLED=false` in production. Universal OTP is for dev / staging / demo only.
- `BOOTSTRAP_ADMIN_PASSWORD` rotated immediately after first boot.

---

## 7. Doc 37 part 2 outcome

Three commits brought this service to monolith parity:

| Commit | Scope |
|---|---|
| `f840fde` | Foundation — 8 new model files (RBAC tables + 2FA + password reset + notification templates) + 4 overwritten + utc_datetime + permissions catalog + shared/notifications. |
| `19a30e5` | Parity — RbacRepository, two_factor + password_reset services, full users/roles/permissions slice, slim master_data router, config env vars, init_db seeds. |
| `fd1c3dc` | Smoke fixes — auth middleware now hydrates `request.state.user_permissions`; legacy `users.admin` references removed; role domain accepts doc-21B `description` field. |

Total app routes loaded cleanly: 64 (from `c:/Programming/PMIS/PMIS-user-management` boot test). Smoke-tested end-to-end with monolith proxy on (port 8000) → user-mgmt (port 8001), including fail-closed verification.

For the cross-repo deploy / cutover plan, see `planned_changes/37` in the monolith repo.
