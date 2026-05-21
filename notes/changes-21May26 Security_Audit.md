# PMIS Security Audit — Hand-off Action List

**Generated:** 2026-05-21
**Source reports:** SonarQube reports dated 2026-05-19 for PMIS-project-management, PMIS-user-management, PMIS-master, PMIS-notification-service
**Source scan codebase:** Monolith snapshot of pre-split PMIS (paths like `app/api/v3/...`) — except `PMIS-master`, which already scanned the new microservice
**Target codebase:** Current microservices at `C:\Users\WC544QK\Downloads\pmis-microservices\` — per-service `app/{controllers,services,repositories,models,schemas,routes,middleware,core,utilities}` layout

---

## 0 · READ FIRST — Safety guardrails for whoever fixes these

Every fix below must preserve current working behavior. Hard rules:

1. **Do not change route URL paths.** All endpoints under `/api/v3/...` (and master's `/api/v3/master/...`, notification-svc's `/notification/...`) must remain reachable at the same URL. If renaming a Python parameter, use FastAPI `Query(..., alias="oldName")` so the URL/query param name is unchanged.
2. **Do not change request or response JSON shapes.** Field names (camelCase like `pageSize`, `includeDeleted`, `vendorId`, `milestoneId`, `delayMinDays`, `minDelay`), nullability, defaults, and validators must stay identical. PMIS uses a HAL envelope via `install_hal_route_class` — do not bypass it.
3. **Do not change folder layout.** Per the project's `feedback-preserve-structure` instruction: modifications go on top of the existing `app/{controllers,services,repositories,models,schemas,routes,middleware,core,utilities}` tree. No file renames, no new folders, no module relocation.
4. **Do not change public method signatures of services/controllers** unless the callsite is updated in the same PR. When refactoring complex functions (cognitive-complexity items), extract **private helpers** (`_foo`) inside the same class/module — the outer function name, parameters, and return type stay the same.
5. **Do not change DB schemas.** No alembic migrations as part of these fixes. Repository method renames/signature changes are out of scope.
6. **Auth invariants:** the `"AUTH_REQUIRED"` error code string must remain `"AUTH_REQUIRED"` when extracted to a constant. Anywhere a 401/403 is raised today, the same HTTP status, headers, error code, and JSON body must be raised after the change.
7. **Cross-schema mirrors:** files under `app/models/_cross_schema.py` are read-only mirrors deliberately excluded from alembic autogen. Do not "fix" them by adding fields, dropping unused ones, or merging.
8. **Tests must pass after every batch.** Run each service's `pytest` (and CI drift test `tests/test_cross_schema_drift.py` where present) before committing. Specifically:
   - `PMIS-user-management/tests/` (unit, integration, parity)
   - `PMIS-master/tests/`
   - `PMIS-project-management/tests/`
   - `PMIS-notification-service/tests/`
9. **No new features, no opportunistic refactors.** Only fix what's listed. Don't "clean up" surrounding code, don't introduce dependency injection containers, don't switch from sync to async or vice versa.
10. **For BLOCKER bulk codemods (Annotated, response_model=):** apply mechanically. The OpenAPI schema FastAPI generates for the route must be byte-identical before/after; verify with `curl /openapi.json | diff` against a pre-change snapshot.

---

## 1 · Report-to-code mapping (where each scan actually pointed)

| SonarQube report folder | Project key in report | Codebase that was actually scanned | Status |
|---|---|---|---|
| `PMIS-project-management` | `PMIS-project-management-dev` | Monolith **user-management** code | Duplicate of below |
| `PMIS-user-management` | `PMIS-user-management-dev-1` | Monolith **user-management** code | Canonical user-mgmt scan |
| `PMIS-master` | `PMIS-master-dev_micro` | **Current master microservice** | Correct scan |
| `PMIS-notification-service` | `PMIS-notification-service-dev` | Monolith **project-management** code | Mislabelled; counts toward project-mgmt |

**Implication:** the `PMIS-notification-service` folder's findings apply to the current `PMIS-project-management` microservice (not the dispatcher). The current `PMIS-notification-service` has no scan at all and only inherits the cross-cutting items in §2.

---

## 2 · Cross-cutting items (apply once per service, all 4)

### X-1 · Add non-root `USER` to every Dockerfile (MEDIUM hotspot · `docker:S6471`)
- **Reported in:** all four scans
- **Files (current):**
  - `PMIS-user-management/Dockerfile`
  - `PMIS-master/Dockerfile`
  - `PMIS-project-management/Dockerfile`
  - `PMIS-notification-service/Dockerfile`
- **Fix:** before the `CMD ...` line, add:
  ```
  RUN groupadd --system app && useradd --system --gid app --home /app --no-create-home appuser \
      && chown -R appuser:app /app
  USER appuser
  ```
- **Safety:** verify `EXPOSE` port + `HEALTHCHECK` still pass after switching user. The `app/` directory must still be readable; nothing currently writes outside `/app`, so this should be safe. Test: `docker build` succeeds, container starts, `curl localhost:<port>/health` returns 200.

### X-2 · Remove production DB password from every `.env` file (BLOCKER · `secrets:S6698` plus general hygiene)
- **Reported in:** user-management, project-management (and present in master/notification-svc by inspection)
- **Files (current):**
  - `PMIS-user-management/.env` line 14, line 15 (`DATABASE_URL`, `DATABASE_URL_MIGRATIONS` contain `aadhaarpmis2026`)
  - `PMIS-master/.env` line 11, line 12
  - `PMIS-project-management/.env` line 10, line 11
  - `PMIS-notification-service/.env` line 12
- **Fix:** replace the literal password in each `.env` with a placeholder and inject the real value from a secrets manager or CI variable at deploy time. The `.env` files in the repo should look like:
  ```
  DATABASE_URL=postgresql+psycopg2://pmis_user:${DB_PASSWORD}@10.1.131.199:5432/pmis_db
  ```
  and the real password is set in the deploy/runtime environment. Do not commit a real password.
- **Safety:** Pydantic settings already reads env vars; switching to a placeholder requires the deployer to set `DB_PASSWORD` (or however you choose to inject). Confirm the `.env.example` files also use the placeholder form.

### X-3 · Remove the hard-coded default DB password from each service's `Settings`
- **Files (current):**
  - `PMIS-user-management/app/config.py:32` — `database_url: str = Field(default="postgresql+psycopg2://pmis_app:changeme@localhost:5432/pmis")`
  - `PMIS-master/app/config.py` — verify same default; remove the `changeme` literal
  - `PMIS-project-management/app/config.py` — same
  - `PMIS-notification-service/app/config.py` — same
- **Fix:** change the Field to `Field(...)` (no default) so the service fails fast if `DATABASE_URL` is not set, **OR** keep a non-credential placeholder default like `Field(default="postgresql+psycopg2://user:CHANGE-ME@localhost:5432/pmis")` to keep dev startup ergonomic. Either is acceptable; pick one and apply consistently.
- **Safety:** services currently start in dev with the default URL pointing at localhost — if you choose the "no default" approach, update each service's local-dev README/`.env.example` to make this clear, and verify CI / Docker Compose set the var.

### X-4 · Bulk codemod: `param: X = Depends(get_x)` → `param: Annotated[X, Depends(get_x)]` (BLOCKER · `python:S8410`)
- **Reported counts:** user-mgmt 145, master 74, project-mgmt 189, notification-svc 0
- **Current counts (verified by grep):** user-mgmt 76, master 63, project-mgmt 108, notification-svc 6 — total ≈ 253 occurrences
- **Files (current):**

  **user-management** (76 hits)
  - `PMIS-user-management/app/routes/auth_routes.py` (12)
  - `PMIS-user-management/app/routes/health_routes.py` (1)
  - `PMIS-user-management/app/routes/permission_routes.py` (7)
  - `PMIS-user-management/app/routes/role_assignment_routes.py` (16)
  - `PMIS-user-management/app/routes/role_grants_routes.py` (1)
  - `PMIS-user-management/app/routes/role_routes.py` (9)
  - `PMIS-user-management/app/routes/user_routes.py` (30)

  **master** (63 hits)
  - `PMIS-master/app/routes/activity_status_routes.py` (6)
  - `PMIS-master/app/routes/activity_type_routes.py` (6)
  - `PMIS-master/app/routes/division_routes.py` (6)
  - `PMIS-master/app/routes/health_routes.py` (1)
  - `PMIS-master/app/routes/milestone_status_routes.py` (6)
  - `PMIS-master/app/routes/notification_template_routes.py` (6)
  - `PMIS-master/app/routes/priority_routes.py` (6)
  - `PMIS-master/app/routes/project_category_routes.py` (6)
  - `PMIS-master/app/routes/project_status_transition_routes.py` (6)
  - `PMIS-master/app/routes/resource_type_routes.py` (6)
  - `PMIS-master/app/routes/vendor_routes.py` (8)

  **project-management** (108 hits)
  - `PMIS-project-management/app/routes/activity_routes.py` (10)
  - `PMIS-project-management/app/routes/attachment_routes.py` (6)
  - `PMIS-project-management/app/routes/catalog_routes.py` (5)
  - `PMIS-project-management/app/routes/comment_routes.py` (6)
  - `PMIS-project-management/app/routes/critical_path_routes.py` (2)
  - `PMIS-project-management/app/routes/dashboard_routes.py` (6)
  - `PMIS-project-management/app/routes/health_routes.py` (1)
  - `PMIS-project-management/app/routes/milestone_routes.py` (10)
  - `PMIS-project-management/app/routes/project_routes.py` (29)
  - `PMIS-project-management/app/routes/subtask_routes.py` (12)
  - `PMIS-project-management/app/routes/task_routes.py` (10)
  - `PMIS-project-management/app/routes/tree_routes.py` (1)
  - `PMIS-project-management/app/routes/vendor_routes.py` (10)

  **notification-service** (6 hits)
  - `PMIS-notification-service/app/routes/cron_routes.py` (2)
  - `PMIS-notification-service/app/routes/dispatch_routes.py` (1)
  - `PMIS-notification-service/app/routes/email_routes.py` (1)
  - `PMIS-notification-service/app/routes/health_routes.py` (1)
  - `PMIS-notification-service/app/routes/sms_routes.py` (1)

- **Fix pattern (mechanical):**
  ```python
  # Before
  from fastapi import Depends
  def handler(db: Session = Depends(get_db), user_id: str = Depends(get_current_user_id)):
      ...

  # After
  from typing import Annotated
  from fastapi import Depends
  def handler(
      db: Annotated[Session, Depends(get_db)],
      user_id: Annotated[str, Depends(get_current_user_id)],
  ):
      ...
  ```
- **Safety:** OpenAPI schema and runtime dependency resolution are byte-identical between the two forms (verified by FastAPI docs). Snapshot `/openapi.json` before the codemod and `diff` after — must be empty. Default values and `Query(...)` parameters are NOT to be migrated by this codemod; only `Depends(...)`.

---

## 3 · Service: PMIS-user-management

(Same scan as the misnamed `PMIS-project-management` report. 248 deduped issues + 14 hotspots.)

### A · Real security

#### UM-A-1 · `secrets:S6698` — hard-coded Postgres password in config (BLOCKER)
- **Old:** `app/core/config.py:53` and `src/app/core/config.py:46`
- **Now:** `PMIS-user-management/app/config.py:32` (and `.env`)
- **Fix:** see cross-cutting X-2 and X-3.

#### UM-A-2 through UM-A-25 · `python:S2068` — "password" literal in tests/scripts (MAJOR)
- **Reported in (deleted files):** `tests/test_auth.py:32, 133, 160, 178`; `tests/test_doc33_2fa_and_password_reset.py:411, 428, 433, 440, 450, 468`; `tests/test_doc43_hierarchy_security.py:101, 329, 417`; `tests/test_doc44_role_projection.py:101, 249`; `tests/test_doc44_round5_user_perms.py:217`; `tests/test_doc45_org_role_column.py:59`; `tests/test_doc46_round10.py:45`; `tests/test_users.py:237, 252, 853, 866`; `scripts/generate_curls.py:74, 75`
- **Verdict:** ⚪ **MOOT** — all referenced test files and the `scripts/` folder are gone from the microservice. Do **NOT** recreate them. No fix needed.

### B · Security hotspots (post cross-cutting X-1)

- All 11 `python:S5332` (`http://` in tests) hotspots are in deleted test files — moot.
- `python:S1313` "hardcoded IP `10.1.131.199`" in `scripts/generate_curls.py:36` — script gone; the same IP exists in `.env` files but that is X-2 / acceptable since it's an internal IP.

### C · CRITICAL — cognitive complexity (`python:S3776`)

For each: extract private helper methods inside the same class to bring complexity ≤ 15. Public signature must not change. Behavior must not change. Add unit-test cases that pin existing observable behavior **before** refactoring if not already covered.

#### UM-C-1 · `UserService.create()` (was complexity 73)
- **Old:** `app/api/v3/users/services/create.py:38, :103`
- **Now:** `PMIS-user-management/app/services/user_service.py:86`
- **Likely sub-steps to extract:** uniqueness checks (login/email), Round-8 C2 grant-matrix validation loop, repository insert, legacy `project_assignments[]` loop, VM-style `project_ids + org_role` loop.

#### UM-C-2 · `UserService.update()` (was complexity 49–51)
- **Old:** `app/api/v3/users/services/update.py:34, :35`
- **Now:** `PMIS-user-management/app/services/user_service.py:185`

#### UM-C-3 · `replace_project_membership` (was complexity 39)
- **Old:** `app/api/v3/users/services/replace_project_membership.py:57`
- **Now:** consolidated into `PMIS-user-management/app/services/user_service.py` (grep for `replace_project_membership` to locate exact method)

#### UM-C-4 · `RbacRepository.effective_permissions_by_scope()` (was complexity 25)
- **Old:** `app/infrastructure/db/repositories/rbac_repository.py:815`
- **Now:** `PMIS-user-management/app/repositories/rbac_repository.py:271` (~94-line method)

#### UM-C-5 · second branchy method in RbacRepository (was complexity 25)
- **Old:** `app/infrastructure/db/repositories/rbac_repository.py:652`
- **Now:** likely `effective_permissions_for_user()` at `PMIS-user-management/app/repositories/rbac_repository.py:238`

#### UM-C-6 · UserRepository methods (was complexity 22 each)
- **Old:** `app/infrastructure/db/repositories/user_repository.py:462, :522`
- **Now:** `PMIS-user-management/app/repositories/user_repository.py` — file is now only 192 lines. Verify with `radon cc` whether issue still applies; likely reduced below threshold.

#### UM-C-7 · Auth middleware decode (was complexity 18)
- **Old:** `app/core/middleware/auth.py:51`
- **Now:** `PMIS-user-management/app/middleware/auth_middleware.py` — JWT decode dispatch function. Verify still over threshold.

#### UM-C-8 · UserController method (was complexity 17)
- **Old:** `app/api/v3/users/controller.py:361`
- **Now:** `PMIS-user-management/app/controllers/user_controller.py` (file is now only 151 lines)

#### UM-C-9 · Users route handler (was complexity 21)
- **Old:** `app/api/v3/users/routes.py:338`
- **Now:** `PMIS-user-management/app/routes/user_routes.py` — likely thin now; verify before refactoring.

#### UM-C-10 through UM-C-15 · Scripts folder (3 functions in `generate_postman_collection.py:42, :119` and `grant_super_admin.py:144`)
- ⚪ **MOOT** — scripts folder deleted.

### D · CRITICAL — duplicated string literals (`python:S1192`)

#### UM-D-1 · Extract `"Authentication required"` constant
- **Old:** `app/core/middleware/rbac.py:54` (used 6× and 5× per two reports)
- **Now (verified 9 occurrences):**
  - `PMIS-user-management/app/dependencies.py:76`
  - `PMIS-user-management/app/core/rbac.py:61, 78, 101, 122, 185, 211, 265, 318`
- **Fix:** add `AUTH_REQUIRED_MESSAGE = "Authentication required"` to a constants module (e.g. top of `PMIS-user-management/app/core/rbac.py` or a new `app/core/constants.py`) and replace literals. Keep the error code argument `code="AUTH_REQUIRED"` exactly as-is — that's an API contract.
- **Safety:** the message text is part of the user-facing error JSON; do not change spelling, capitalization, or trailing punctuation. After extraction, response body for an unauthenticated request must be byte-identical.

#### UM-D-2 · Extract `"/api/v3"` constant
- **Old:** `app/core/response.py:23` (used 9×)
- **Now (verified 15 occurrences across 5 files):**
  - `PMIS-user-management/app/middleware/auth_middleware.py` (7)
  - `PMIS-user-management/app/services/auth_service.py` (1)
  - `PMIS-user-management/app/schemas/auth.py` (2)
  - `PMIS-user-management/app/routes/permission_routes.py` (1)
  - `PMIS-user-management/app/routes/__init__.py` (4)
- **Fix:** add `API_V3_PREFIX = "/api/v3"` to `PMIS-user-management/app/core/constants.py` (create file if absent) and replace literals.
- **Safety:** the path prefix `/api/v3` is the public URL prefix — the constant value must remain exactly `"/api/v3"`. Do not change to `"v3"` or `/v3` or add a trailing slash.

#### UM-D-3 · Extract `"users:read"` constant
- **Old:** `scripts/generate_curls.py:51` (used 3×)
- **Now:** ⚪ **MOOT** — script gone. The `USERS_READ` constant already exists in `PMIS-user-management/app/core/permissions.py` for production code.

### E · MAJOR — code smells

#### UM-E-1 / UM-E-2 · `python:S107` too many parameters on `create_user` / `update_user`
- **Old:** `app/api/v3/users/services/create.py:104` (15 params), `update.py:35` (14 params)
- **Now:** 🟢 **FIXED** — `UserService.create(payload: UserCreateRequest, ...)` and `update(user_id, payload: UserUpdateRequest, ...)` take Pydantic payloads. No action.

#### UM-E-3 / UM-E-4 · `python:S1066` mergeable `if`
- **Old:** `app/api/v3/role_assignments/services.py:410, :449`
- **Now:** `PMIS-user-management/app/services/role_assignment_service.py` — grep for nested `if`/`if` pairs. Verify and merge.
- **Safety:** identical truth table — merging `if A: if B:` to `if A and B:` only safe when no `else` clause exists on the outer.

#### UM-E-5 through UM-E-9 · `python:S1172` unused parameters
- **Old:**
  - `app/api/v3/role_assignments/services.py:119, :158` — param `target_organization_id`
  - `app/api/v3/users/services/restore.py:29` — param `requesting_user_id`
  - `app/infrastructure/db/repositories/user_repository.py:620, :680` — param `expected_old_jti`
- **Now:** grep current
  - `PMIS-user-management/app/services/role_assignment_service.py` for `target_organization_id`
  - `PMIS-user-management/app/services/user_service.py` `restore()` method for `requesting_user_id`
  - `PMIS-user-management/app/repositories/user_repository.py` for `expected_old_jti`
- **Fix:** if the parameter is truly unused **and** is not part of a documented public interface, remove. If callers pass it positionally, update them in the same change. If it's part of a stable signature (e.g. a Service method called from many places), prefix with `_` to suppress the warning instead of removing.
- **Safety:** **never** remove a parameter from a method that is called externally without updating all call sites. Run `pytest` to catch.

#### UM-E-10 through UM-E-13 · `python:S3358` nested conditional expressions
- **Old:**
  - `app/api/v3/users/controller.py:662, :786`
  - `app/api/v3/role_assignments/services.py:208`
  - `app/infrastructure/db/models/user_role_assignment.py:106`
- **Now:** grep in `PMIS-user-management/app/controllers/user_controller.py`, `app/services/role_assignment_service.py`, `app/models/user_role_assignment.py` for ternaries of the form `a if c1 else (b if c2 else d)`.
- **Fix:** extract the inner expression to a local variable or an early-return.
- **Safety:** the truth table must remain identical. Add a unit test if not present.

### F · MINOR — code smells

#### UM-F-1 through UM-F-10 · `python:S117` `pageSize` camelCase parameter
- 🟢 **FIXED** — current routes use `page_size: int = Query(20, ..., alias="pageSize")` pattern. Verified at `PMIS-user-management/app/routes/user_routes.py:53` and `role_routes.py:37`. No action.

#### UM-F-11 through UM-F-30 · `python:S1481` unused locals
- All but ~1 were in deleted test files. ⚪ **MOOT**. If `radon` / Sonar re-scan flags any new ones in current code, address per-occurrence then.

#### UM-F-31 / UM-F-32 · `python:S7494` set constructor → comprehension
- **Old:** `app/infrastructure/db/repositories/rbac_repository.py:706, :715`
- **Now:** 🟢 **FIXED** — no `set(generator)` pattern in current rbac_repository. Verified.

#### UM-F-33 through UM-F-35 · `python:S100` test method naming
- Deleted test files. ⚪ **MOOT**.

#### UM-F-36 / UM-F-37 · `python:S1854` unused alembic vars (`user_idx`, `user_fks`)
- **Old:** `alembic/versions/b9f4d27e1a83_user_drift_port_columns.py:63, :64`
- **Now:** ⚪ **MOOT** — alembic baseline rebuilt; current migrations are `u1a000000001_create_users_tables.py`, `u1a000000002_seed_users_builtins.py`.

#### UM-F-38 / UM-F-39 · `python:S1186` empty methods in tests
- ⚪ **MOOT** — test files deleted.

#### UM-F-40 through UM-F-45 · `python:S3457` f-string without replacement fields
- All in deleted test files / shrunken conftest. ⚪ **MOOT**.

### G · BLOCKER bulk codemod
Covered by cross-cutting **X-4** for the 76 occurrences across `PMIS-user-management/app/routes/`.

---

## 4 · Service: PMIS-master

(143 issues, 1 hotspot, **zero vulnerabilities**, zero CRITICAL bugs. Scan was already against the current microservice — no monolith-to-microservice mapping needed.)

### A · Real security

None. Sonar found no vulnerabilities in master.

### B · Security hotspots

- **MS-B-1** · Dockerfile root user — covered by cross-cutting **X-1**.

### C · CRITICAL — duplicated literal (`python:S1192`)

#### MS-C-1 · Extract `"Authentication required"` constant (used 4×)
- **Now (verified):** `PMIS-master/app/core/rbac.py` — 4 occurrences
- **Fix:** add `AUTH_REQUIRED_MESSAGE = "Authentication required"` constant at module top of `PMIS-master/app/core/rbac.py` and replace literals. Keep `code="AUTH_REQUIRED"` parameter exactly as-is.
- **Safety:** identical to UM-D-1 — error message text is an API contract.

### D · BLOCKER bulk codemod 1 — Annotated
Covered by cross-cutting **X-4** for the 63 occurrences across `PMIS-master/app/routes/`.

### E · BLOCKER bulk codemod 2 — redundant `response_model=` (`python:S8409`)

#### MS-E-1 · Remove redundant `response_model=` parameter from 55 route decorators
- **Reported:** 62 hits (deduped, all in master's `app/routes/`)
- **Current count (verified):** 55 occurrences across 10 of the 11 route files in `PMIS-master/app/routes/`
- **Files (current):**
  - `PMIS-master/app/routes/activity_status_routes.py` (6)
  - `PMIS-master/app/routes/activity_type_routes.py` (6)
  - `PMIS-master/app/routes/division_routes.py` (6)
  - `PMIS-master/app/routes/milestone_status_routes.py` (6)
  - `PMIS-master/app/routes/notification_template_routes.py` (6)
  - `PMIS-master/app/routes/priority_routes.py` (6)
  - `PMIS-master/app/routes/project_category_routes.py` (6)
  - `PMIS-master/app/routes/project_status_transition_routes.py` (6)
  - `PMIS-master/app/routes/resource_type_routes.py` (6)
  - `PMIS-master/app/routes/vendor_routes.py` (1)
- **Fix pattern:**
  ```python
  # Before — response_model duplicates the -> return type
  @router.get("/foo", response_model=List[FooResponse])
  def list_foo(...) -> List[FooResponse]:
      ...

  # After — drop the response_model kwarg; FastAPI infers from -> annotation
  @router.get("/foo")
  def list_foo(...) -> List[FooResponse]:
      ...
  ```
- **Safety:** the return type annotation `->` must exist and match what `response_model=` previously specified. If a handler has `response_model=Foo` but no `-> Foo` return annotation, **add the annotation first**, then remove `response_model=`. Snapshot `/openapi.json` before and after — must be identical.

### F · BLOCKER — methods always returning same value (`python:S3516`)

#### MS-F-1 / MS-F-2 · 2 hits, locations not yet identified
- **Reported:** 2 hits, location not pinpointed in TCD pivot
- **Action:** grep `PMIS-master/app/` for any function whose body always returns the same constant or whose every branch returns the same value (often a stale wrapper from refactor). Inspect each; either delete the redundant return or restructure to actually return varying values.
- **Safety:** if a caller relies on the function being a no-op returning a sentinel, leave the behavior intact — only adjust to silence the rule without changing observable return.

### G · MINOR

#### MS-G-1 · `python:S7504` — Remove unnecessary `list()` on already-iterable object (1 hit)
- **Now:** grep `PMIS-master/app/` for `list(` calls where the arg is already a list/tuple/set/dict.values()/etc. Sonar's "Issues" sheet has the exact line if needed.
- **Fix:** drop the redundant `list()` wrap.
- **Safety:** if the original code mutates the result (`.append`, `.sort`) and the wrapped iterable is a view (e.g. `dict.values()`), keep `list()`. Only remove when the wrapped value is already a concrete list.

#### MS-G-2 / MS-G-3 · `python:S117` — Rename `inactive_T1` and `active_T2` locals (2 hits)
- **Now:** grep `PMIS-master/app/` for `inactive_T1` and `active_T2`. Probably in a test helper or fixture data — verify these are not part of a public API/JSON shape before renaming.
- **Fix:** rename to `inactive_t1` / `active_t2` (snake_case).
- **Safety:** if the identifier is also a dict key in JSON output (e.g. `{"inactive_T1": ...}`), do **NOT** rename — that would break the response shape. Verify with grep.

---

## 5 · Service: PMIS-project-management

(Scanned under the misnamed `PMIS-notification-service` report. 422 deduped issues + 2 hotspots + 7 vulnerabilities. This is the heaviest service.)

### A · Real security

#### PM-A-1 · `secrets:S6698` — hard-coded Postgres password in config (BLOCKER)
- **Old:** `app/core/config.py:53`
- **Now:** `PMIS-project-management/app/config.py` + `.env`
- **Fix:** cross-cutting **X-2** and **X-3**.

#### PM-A-2 through PM-A-7 · `python:S2068` — "password" literal in tests (MAJOR)
- **Old:** `tests/conftest.py:162, :186`; `tests/test_assigned_to_on_ts.py:48, :65, :82`; `tests/test_scoped_rbac_mirror.py:66`
- **Verdict:** likely ⚪ **MOOT** — verify that those monolith test files exist in current `PMIS-project-management/tests/`. If they do, replace each literal with a `pytest` fixture or a module-level constant prefixed `_`. If they don't, no action.

### B · Security hotspots (post X-1)

Both `docker:S6471` hits — covered by X-1.

### C · CRITICAL — cognitive complexity (`python:S3776`, 49 unique hits, peaks at 134)

For each: extract private helpers inside the same module/class to bring complexity ≤ 15. Public signatures and observable behavior unchanged.

| ID | Old monolith path:line | Old complexity | Current microservice file |
|---|---|---|---|
| PM-C-1 | `app/api/v3/activities/services/update.py:201` | **134** | `PMIS-project-management/app/services/activity_service.py` — `update_*` |
| PM-C-2 | `app/api/v3/activities/services/update.py:162` | **126** | same file |
| PM-C-3 | `app/api/v3/subtasks/services/update.py:152` | **100** | `PMIS-project-management/app/services/subtask_service.py` — `update_*` |
| PM-C-4 | `app/api/v3/tasks/services/update.py:141` | **100** | `PMIS-project-management/app/services/task_service.py` — `update_*` |
| PM-C-5 | `app/api/v3/projects/services/update.py:36` | 94 | `PMIS-project-management/app/services/project_service.py:155` |
| PM-C-6 | `app/api/v3/subtasks/services/update.py:82` | 88 | `subtask_service.py` |
| PM-C-7 | `app/api/v3/tasks/services/update.py:96` | 88 | `task_service.py` |
| PM-C-8 | `app/api/v3/milestones/services/update.py:126` | 79 | `PMIS-project-management/app/services/milestone_service.py` |
| PM-C-9 | `app/api/v3/milestones/services/update.py:126` | 70 | same file |
| PM-C-10 | `app/api/v3/comments/services/create.py:50` | 33 | `PMIS-project-management/app/services/comment_service.py` |
| PM-C-11 | `app/api/v3/comments/services/create.py:49` | 33 | same |
| PM-C-12 | `app/api/v3/projects/services/upsert.py:38` | 33 | `project_service.py:227` `upsert()` |
| PM-C-13 | `app/api/v3/subtasks/services/create.py:128` | 66 | `subtask_service.py` `create()` |
| PM-C-14 | `app/api/v3/subtasks/services/create.py:128` | 62 | same |
| PM-C-15 | `app/api/v3/tasks/services/create.py:68` | 58 | `task_service.py` `create()` |
| PM-C-16 | `app/api/v3/tasks/services/create.py:68` | 54 | same |
| PM-C-17 | `app/api/v3/_inline_attachments.py:68` | 50 | inline-attachments helper — search `PMIS-project-management/app/` for inline-attachment handling code (likely in `attachment_service.py` or `utilities/`) |
| PM-C-18 | `app/api/v3/_inline_attachments.py:66` | 50 | same |
| PM-C-19 | `app/api/v3/vendors/routes.py:468` | 46 | `PMIS-project-management/app/routes/vendor_routes.py` |
| PM-C-20 | `app/api/v3/activities/services/create.py:42` | 45 | `PMIS-project-management/app/services/activity_service.py` `create()` |
| PM-C-21 | `app/api/v3/activities/services/create.py:42` | 42 | same |
| PM-C-22 | `app/api/v3/projects/services/create.py:30` | 44 | `project_service.py:95` `create()` |
| PM-C-23 | `app/api/v3/dashboard/services/project_items.py:35` | 41 | `PMIS-project-management/app/services/dashboard_service.py` |
| PM-C-24 | `app/api/v3/tree/service.py:150` | 36 | `PMIS-project-management/app/services/tree_service.py` |
| PM-C-25 | `app/api/v3/tree/service.py:137` | 36 | same |
| PM-C-26 | `app/api/v3/vendors/user_assignments.py:77` | 34 | look in `vendor_service.py` or similar in `PMIS-project-management/app/services/` |
| PM-C-27 | `app/api/v3/milestones/services/create.py:34` | 32 | `milestone_service.py` `create()` |
| PM-C-28 | `app/api/v3/milestones/services/create.py:34` | 29 | same |
| PM-C-29 | `app/shared/labels.py:642` | 31 | search `PMIS-project-management/app/` for label helper |
| PM-C-30 | `app/shared/labels.py:421` | 18 | same |
| PM-C-31 | `app/shared/date_rules.py:120` | 24 | search `PMIS-project-management/app/utilities/` for date helpers |
| PM-C-32 | `app/api/v3/dashboard/services/projects_list.py:33` | 23 | `dashboard_service.py` |
| PM-C-33 | `app/shared/dep_block.py:233` | 21 | search for dependency block helpers |
| PM-C-34 | `app/api/v3/projects/routes.py:480` | 25 | `PMIS-project-management/app/routes/project_routes.py` |
| PM-C-35 | `app/api/v3/projects/routes.py:787` | 25 | same file |
| PM-C-36 | `app/api/v3/dashboard/services/summary.py:30` | 20 | `dashboard_service.py` |
| PM-C-37 | `alembic/versions/8a3c5e7f9b21_initial_project_service_schema.py:36` | 20 | ⚪ likely **MOOT** if migration has been rebuilt — verify current `PMIS-project-management/alembic/versions/` |
| PM-C-38 | `alembic/versions/b7c2e8f4a9d6_doc38_field_trim.py:49` | 57 | ⚪ likely **MOOT** |
| PM-C-39 | `alembic/versions/c2d4e7f9a1b4_doc20_to_36_parity.py:67` | 69 | ⚪ likely **MOOT** |
| PM-C-40 | `alembic/versions/d3e5f7a9b1c2_doc37_static_data_masters.py:74` | 16 | ⚪ likely **MOOT** |
| PM-C-41 | `app/core/middleware/auth.py:51` | 18 | `PMIS-project-management/app/middleware/auth_middleware.py` |
| PM-C-42 | `app/infrastructure/db/repositories/dashboard_repository.py:98` | 17 | look for dashboard repository in `PMIS-project-management/app/repositories/` (may have been merged into `project_repository.py`) |
| PM-C-43 | `app/infrastructure/db/repositories/dependency_repository.py:128` | 16 | search `PMIS-project-management/app/repositories/` — may be in `_cascade.py` or merged |
| PM-C-44 | `app/infrastructure/db/repositories/dependency_repository.py:283` | 16 | same |
| PM-C-45 | `app/infrastructure/db/repositories/dependency_repository.py:434` | 16 | same |
| PM-C-46 | `app/infrastructure/db/repositories/dependency_repository.py:573` | 16 | same |
| PM-C-47 | `app/infrastructure/db/repositories/project_audit_log_repository.py:41` | 18 | `PMIS-project-management/app/repositories/project_audit_log_repository.py` |
| PM-C-48 | `app/infrastructure/db/repositories/rbac_repository.py:373` | 17 | `PMIS-project-management/app/repositories/rbac_read_repository.py` |
| PM-C-49 | `app/infrastructure/db/repositories/rbac_repository.py:348` | 17 | same |

**Approach for the big-complexity items (≥ 50):** each is a `create_*` / `update_*` / `upsert` service function. Refactor pattern: split into stages — (a) validate inputs, (b) load existing row, (c) compute updates, (d) apply, (e) emit audit + cascade. Each stage is a private helper. Keep the outer method's exception types, return type, and side effects byte-identical.

### D · CRITICAL — real bugs

#### PM-D-1 through PM-D-8 · `python:S5727` "Remove this identity check; it will always be True"
These are real logic bugs (e.g. `if x is True:` when `x` is already a non-bool truthy value, or a tautology like `if obj is not None or obj:`).
- **Old:**
  - `app/api/v3/activities/services/update.py:428, :477`
  - `app/api/v3/milestones/services/update.py:260, :298`
  - `app/api/v3/subtasks/services/update.py:238, :314`
  - `app/api/v3/tasks/services/update.py:256, :307`
- **Now:** the same `update_*` methods live in current `PMIS-project-management/app/services/{activity,milestone,subtask,task}_service.py`. Grep each for `is True`, `is False`, or any tautological condition.
- **Fix:** examine each — if the check is genuinely always-True, the inner branch is dead code; consider whether it's actually meant to check identity-of-different-object (then keep) or whether the wrong operator was used (then fix to `==` / `not None` / appropriate test).
- **Safety:** these may have been load-bearing **logic bugs that the team relied on accidentally**. Before deleting any "always True" branch, write a test that exercises the surrounding code path and verify the application's actual intent. Don't "fix" by deleting unless you've verified the dead branch is truly dead.

### E · CRITICAL — duplicated literals (`python:S1192`, 23 hits)

#### PM-E-1 · Extract `"Authentication required"` constant
- **Old:** `app/core/middleware/rbac.py:41` (3×)
- **Now (verified 9 occurrences):** `PMIS-project-management/app/dependencies.py` (1) and `PMIS-project-management/app/core/rbac.py` (8)
- **Fix:** identical to UM-D-1. Add constant in `PMIS-project-management/app/core/rbac.py` or `app/core/constants.py`.

#### PM-E-2 · Extract `"/api/v3"` constant
- **Old:** `app/core/response.py:23` (9×) and `app/api/v3/projects/controller.py:107, :128` (8× and 9×)
- **Now:** grep `PMIS-project-management/app/` for `/api/v3` — extract to `app/core/constants.py` `API_V3_PREFIX`.

#### PM-E-3 · Extract `"Vendor not found."` constant
- **Old:** `app/api/v3/vendors/routes.py:252, :300` (4× each)
- **Now:** `PMIS-project-management/app/routes/vendor_routes.py` (verify still duplicates) or controller file. Extract to module top.

#### PM-E-4 · Extract `"users.id"` constant
- **Old:** `app/infrastructure/db/models/{project,subtask,task}.py:77/90/59` (3× each)
- **Now:** `PMIS-project-management/app/models/project.py`, `subtask.py`, `task.py` — these are FK targets (`ForeignKey("users.id")`). The string is a DB identifier and probably needs to stay consistent across all 3 files. Add `USERS_ID_FK = "users.id"` in a shared models module (e.g. `app/models/__init__.py` or `app/models/_constants.py`) and reference from each.
- **Safety:** if you change "users.id" to anything else accidentally, FK creation fails. The constant value must be exactly `"users.id"`.

#### PM-E-5 · Extract `"(unknown)"` constant
- **Old:** `app/api/v3/projects/services/audit.py:190` (6×) and `app/infrastructure/db/repositories/project_audit_log_repository.py:75` (3×)
- **Now:** `PMIS-project-management/app/services/audit_log_service.py` and `PMIS-project-management/app/repositories/project_audit_log_repository.py`. Extract to a shared `UNKNOWN_LABEL = "(unknown)"` constant — the literal appears in audit log entries that may be persisted; make sure existing rows still match.
- **Safety:** if existing audit log rows in DB have `"(unknown)"` as a stored value, the constant must produce the same string (with parens).

#### PM-E-6 · Extract `"Parent project UUID"` field-description constant
- **Old:** `app/api/v3/projects/schemas.py:29` (3×)
- **Now:** `PMIS-project-management/app/schemas/project.py` (or similar) — Pydantic `Field(description=...)`. Extract.
- **Safety:** the description shows up in OpenAPI docs; same text → same docs.

#### PM-E-7 · Extract `"Date must be in the future"` validator-message constant
- **Old:** `app/api/v3/projects/schemas.py:90` (3×)
- **Now:** current `PMIS-project-management/app/schemas/` project schema. Extract.
- **Safety:** validator error messages are part of the API contract — text must remain identical.

#### PM-E-8 · Extract `"end_date cannot be before start_date"` validator-message constant
- **Old:** `app/api/v3/projects/schemas.py:100` (3×)
- **Now:** same as above. Extract.

#### PM-E-9 · Extract `"application/zip"` MIME constant
- **Old:** `app/shared/file_signature.py:59` (3×)
- **Now:** search `PMIS-project-management/app/utilities/` (or `app/services/attachment_service.py`) for `"application/zip"`. Extract `MIME_ZIP = "application/zip"`.

#### PM-E-10 through PM-E-15 · alembic-baseline literals
- **Old:** `alembic/versions/8a3c5e7f9b21_initial_project_service_schema.py:228, 431, 435, 439, 444, 535, 668, 787` — `"projects.id"`, `"tasks.id"`, etc.
- **Verdict:** ⚪ likely **MOOT** if alembic baseline has been rebuilt. Verify current `PMIS-project-management/alembic/versions/`. If the new migrations still duplicate these literals, extract per-migration constants at the top of the file (or just accept — alembic migrations are usually not Sonar-clean).

### F · MAJOR — too many parameters (`python:S107`, 22 hits)

#### PM-F-1 through PM-F-22 · All `create_*`/`update_*`/`upsert_*` functions and `*Repository.create()` methods
- **Old:**
  - `app/api/v3/activities/services/create.py:43` `create_activity` (21 params)
  - `app/api/v3/activities/services/update.py:163, :202` `update_activity` (21 params)
  - `app/api/v3/milestones/services/create.py:35` `create_milestone` (14)
  - `app/api/v3/milestones/services/update.py:127` `update_milestone` (14)
  - `app/api/v3/projects/services/create.py:31` `create_project` (17)
  - `app/api/v3/projects/services/upsert.py:39` `upsert_project` (18)
  - `app/api/v3/subtasks/services/create.py:129` `create_subtask` (17/19)
  - `app/api/v3/subtasks/services/update.py:83, :153` `update_subtask` (16/18)
  - `app/api/v3/tasks/services/create.py:69` `create_task` (16/18)
  - `app/api/v3/tasks/services/update.py:97, :142` `update_task` (16/18)
  - `app/infrastructure/db/repositories/activity_repository.py:144` `Method create` (19)
  - `app/infrastructure/db/repositories/project_repository.py:87, :153` `Method create / upsert_by_id` (19/15)
  - `app/infrastructure/db/repositories/subtask_repository.py:255, :257` `Method create` (15/17)
  - `app/infrastructure/db/repositories/task_repository.py:129, :131` `Method create` (14/16)
- **Now:** 🟢 **service-layer functions appear FIXED** — verified `ProjectService.create(payload: ProjectCreateRequest, ...)` and `ProjectService.update`, `ProjectService.upsert` take Pydantic payloads in `PMIS-project-management/app/services/project_service.py:95, :155, :227`.
- **Action:** verify the same for activity/milestone/subtask/task services. **The repository-layer methods (`*Repository.create()` with 14–19 params) likely still take flat params** — those are the real ones still applying. Refactor each to accept a TypedDict / dataclass / `**kwargs` (carefully).
- **Safety:** repository `create()` methods are called from services with positional/keyword args; any signature change must update all call sites.

### G · MAJOR — unused parameters (`python:S1172`, 9 hits)

| ID | Old path:line | Param | Action |
|---|---|---|---|
| PM-G-1 | `app/api/v3/_inline_attachments.py:308, :331` | `format_attachment_response` | grep current inline-attachment helper; remove or prefix `_` |
| PM-G-2 | `app/api/v3/dashboard/services/projects_list.py:36` | `counters` | search `PMIS-project-management/app/services/dashboard_service.py` |
| PM-G-3 | `app/api/v3/dashboard/services/projects_list.py:38` | `progress_pct` | same file |
| PM-G-4 | `app/api/v3/master_data/routes.py:712` | `request` | ⚠ master_data is owned by `PMIS-master` service; not applicable to project-mgmt anymore. ⚪ **MOOT** |
| PM-G-5 | `app/api/v3/projects/services/upsert.py:42` | `current_user_login` | `project_service.py:227` `upsert()` — check |
| PM-G-6 | `app/api/v3/projects/services/upsert.py:43` | `is_admin` | same |
| PM-G-7 | `app/shared/date_rules.py:127` | `entity_label` | search `PMIS-project-management/app/utilities/` |
| PM-G-8 | `app/shared/file_signature.py:197` | `ext` | search `PMIS-project-management/app/utilities/` |

**Safety same as UM-E-5..9** — never remove a parameter from a method called externally without updating all call sites.

### H · MAJOR — variable shadows builtin (`python:S5806`, 5 hits)

| ID | Old path:line | Likely shadowed builtin | Action |
|---|---|---|---|
| PM-H-1 | `app/api/v3/subtasks/services/create.py:160, :164` | likely `id`, `type`, `format`, or similar | `PMIS-project-management/app/services/subtask_service.py` — locate variables named after builtins inside `create()`; rename to `subtask_id`, `subtask_type`, etc. |
| PM-H-2 | `app/api/v3/tasks/services/create.py:107, :111` | same | `task_service.py` `create()` |
| PM-H-3 | `app/infrastructure/db/repositories/project_repository.py:114` | same | `PMIS-project-management/app/repositories/project_repository.py` |

**Safety:** rename inside the function scope only — the variable is local, no external effect. But verify it's not bound to a Pydantic field name or a SQLAlchemy attribute (would change ORM behavior).

### I · MAJOR — nested conditionals (`python:S3358`, 4 hits)

| ID | Old path:line | Action |
|---|---|---|
| PM-I-1 | `app/api/v3/projects/routes.py:853` | `PMIS-project-management/app/routes/project_routes.py` — extract inner ternary |
| PM-I-2 | `app/api/v3/subtasks/controller.py:414` | `PMIS-project-management/app/controllers/subtask_controller.py` |
| PM-I-3 | `app/api/v3/subtasks/controller.py:387` | same |
| PM-I-4 | `app/infrastructure/db/models/user_role_assignment.py:88` | ⚠ this model is in user-management's schema, not project-management's. ⚪ likely **MOOT** for project-mgmt; if a cross-schema mirror exists at `PMIS-project-management/app/models/_cross_schema.py`, leave it alone. |

### J · MAJOR — mergeable if (`python:S1066`, 3 hits)

| ID | Old path:line | Action |
|---|---|---|
| PM-J-1 | `app/api/v3/dashboard/services/projects_list.py:70` | `dashboard_service.py` — merge nested `if` |
| PM-J-2 | `app/api/v3/subtasks/services/update.py:399` | `subtask_service.py` `update_*` |
| PM-J-3 | `app/api/v3/tasks/services/update.py:392` | `task_service.py` `update_*` |

### K · MAJOR — `python:S8415` Document HTTPException with 404 in `responses` (2 hits)

#### PM-K-1 / PM-K-2 · Add `responses={404: ...}` to two route decorators
- **Old line refs unrecovered from pivot (rule output garbled).** Grep `PMIS-project-management/app/routes/` for route handlers that raise `HTTPException(404)` but lack `responses=` kwarg on the `@router.*` decorator. Add `responses={404: {"description": "..."}}`.
- **Safety:** changes only the OpenAPI documentation, not runtime behavior. No risk to features.

### L · MAJOR — `python:S125` Remove commented-out code (1 hit)
- **Line ref unrecovered from pivot.** Grep `PMIS-project-management/app/` for large comment blocks of valid Python. Delete if truly dead.
- **Safety:** verify the commented code isn't an intentional "future reference" — check git blame / surrounding context. If unsure, leave it.

### M · MINOR — `python:S117` camelCase parameters (25 hits)

#### PM-M-1 · Migrate route params to `snake_case + alias="camelCase"` pattern
**Most routes already use this pattern** (verified `activity_routes.py:149`, `attachment_routes.py:104`, etc. using `page_size: int = Query(20, ..., alias="pageSize")`).

**Still using raw camelCase Python identifiers (need fix):**
- `PMIS-project-management/app/routes/dashboard_routes.py:44` — `delayMinDays: int = Query(...)`
- `PMIS-project-management/app/routes/dashboard_routes.py:65` — `vendorId: Optional[str] = Query(None)`
- `PMIS-project-management/app/routes/dashboard_routes.py:68` — `pageSize: int = Query(...)`
- `PMIS-project-management/app/routes/dashboard_routes.py:94` — `delayMinDays`
- `PMIS-project-management/app/routes/dashboard_routes.py:116` — `milestoneId`
- `PMIS-project-management/app/routes/dashboard_routes.py:117` — `minDelay`
- `PMIS-project-management/app/routes/tree_routes.py:35` — `includeDeleted`

**Fix pattern:**
```python
# Before
def list_things(pageSize: int = Query(200, ge=1, le=500)):
    ...

# After
def list_things(page_size: int = Query(200, ge=1, le=500, alias="pageSize")):
    ...
```
- **Safety:** the URL query parameter name **must remain `pageSize`** (etc.) — only the Python identifier changes. Verify with a request: `GET /dashboard/...?pageSize=10` still returns the same.

### N · MINOR — unused local variables (`python:S1481`, 42 hits)
- Of the 42, 35 are in monolith-era test files (`tests/test_hierarchy_completion_gate.py`, `tests/test_unified_create_fields.py`, `tests/test_priority_catalog.py`, etc.).
- **Verdict:** if those tests have been rewritten in `PMIS-project-management/tests/`, ⚪ **MOOT**. Verify by `ls PMIS-project-management/tests/`. The remaining few may apply to current code:
  - `app/api/v3/dashboard/services/organisations.py:?` (1)
  - `app/api/v3/projects/routes.py:?` (1) — `PMIS-project-management/app/routes/project_routes.py`
- **Fix:** rename to `_` or remove if value is truly unused.

### O · MINOR — `python:S7508` redundant call (4 hits in `dependency_repository`)
- **Old:** `app/infrastructure/db/repositories/dependency_repository.py:76, :232, :365, :507`
- **Now:** `dependency_repository` may have been merged into `_cascade.py` or `project_repository.py` in `PMIS-project-management/app/repositories/`. Grep for the call pattern and remove redundancy.

### P · MINOR — `python:S7494` set constructor → comprehension (4 hits, same file as O)
- **Old:** `dependency_repository.py:77, :234, :366, :508` (one line after the S7508 entries)
- **Fix:** mechanical — `set(x for x in ...)` → `{x for x in ...}`.

### Q · MINOR — `python:S7500`/`S7498`/`S7519` Python idiom modernizations (≤ 9 hits combined)
- `S7500` (4): `app/api/v3/projects/routes.py:917, 925, 933, 941` — `dict((k, v) for ...)` → `dict(((k, v) for ...))` (passing the generator directly to `dict()` rather than converting to comprehension). Look in `PMIS-project-management/app/routes/project_routes.py`.
- `S7498` (3): `app/api/v3/subtasks/controller.py:479`, `tasks/controller.py:327`, `db/repositories/project_repository.py:197` — `list()` → `[]`, `dict()` → `{}`, `tuple()` → `()`.
- `S7519` (1): line unrecovered — `dict.fromkeys(...)` instead of `{k: None for k in ...}`.

**Safety:** all mechanical Python idiom fixes — verify equivalence with a small unit test if any of these is in a code-path that handles None / empty / generator-exhaustion.

### R · MINOR — `python:S7503` async without await (2 hits)
- **Old:** `app/api/v3/attachments/routes.py:41`, `app/api/v3/comments/routes.py:42`
- **Now:** `PMIS-project-management/app/routes/attachment_routes.py`, `app/routes/comment_routes.py` — find `async def` handlers that contain only sync code. Either:
  - **(a)** drop the `async` keyword, **OR**
  - **(b)** if the handler uses `await` indirectly through FastAPI, leave it (the rule may be a false positive).
- **Safety:** removing `async` from a route handler **does change FastAPI behavior** — sync handlers run in a threadpool, async handlers run in the event loop. If any code in the handler does I/O via async client, **keep `async`**. Default: don't touch unless you've verified the handler has no awaitable code anywhere downstream.

### S · MINOR — `python:S100` test method naming (12 hits)
- All references to monolith test files (`test_create_project_omits_isPublic`, etc.). ⚪ **MOOT** if test files have been rewritten.

### T · INFO — `python:S1135` TODO comments (2 hits)
- `app/api/v3/projects/services/update.py:260` and `app/infrastructure/storage/external_file_client.py:176`
- **Verdict:** triage individually — either complete the TODO or remove the comment with a brief explanation. Don't bulk-delete.

### U · BLOCKER — `python:S8414` CORSMiddleware not last (probably 1 hit)
- **Now:** verify `PMIS-project-management/app/main.py` middleware stack — CORS must be added last (innermost). Per `[[project-pmis-architecture]]` CORS is only installed when `ENV=development`; outside dev, nginx owns CORS. So this likely only applies in the dev path.
- **Fix:** in `main.py`, ensure `app.add_middleware(CORSMiddleware, ...)` is the **last** `add_middleware(...)` call (FastAPI adds middleware in reverse order — last-added wraps everything else).
- **Safety:** the order of `RequestContextMiddleware → AuthMiddleware → handler` must be preserved. Only the CORS layer placement should change if it's currently misplaced.

### V · BLOCKER bulk codemod — Annotated
Covered by cross-cutting **X-4** for the 108 occurrences across `PMIS-project-management/app/routes/`.

---

## 6 · Service: PMIS-notification-service

**No SonarQube scan exists for this service.** The folder labelled `PMIS-notification-service` in the report set actually scanned the monolith `project-management` code (see §1).

### NS-A · Real security
None reported. Cross-cutting **X-2** / **X-3** for `.env` and `Settings` apply.

### NS-B · Security hotspots
- **NS-B-1** · Dockerfile root user — covered by cross-cutting **X-1**.

### NS-C · BLOCKER bulk codemod — Annotated
Covered by cross-cutting **X-4** for the 6 occurrences across `PMIS-notification-service/app/routes/`.

### NS-D · One-time TODO
Re-run SonarQube with the **correct project key** (e.g. `PMIS-notification-service-dev` pointed at `PMIS-notification-service/`) and re-issue findings. The current report is invalid for this service.

---

## 7 · Suggested execution order

1. **Day 0 — Setup**: snapshot `/openapi.json` for each service (`curl localhost:<port>/openapi.json > before.json`) and run each service's full test suite to lock in green baseline.
2. **Day 1 — Cross-cutting X-1, X-2, X-3** (all 4 services): Docker `USER`, `.env` password, config default.
3. **Day 2 — Cross-cutting X-4** (Annotated codemod): all 4 services. After each service, `diff before.json after.json` (FastAPI's `/openapi.json` for `Annotated[X, Depends(...)]` is identical to `X = Depends(...)`).
4. **Day 3 — Master cleanup**: MS-E (redundant response_model), MS-C-1 (constant), MS-G-1/2/3 (small items), MS-F-1/2 (S3516 — needs investigation).
5. **Day 4 — User-management constants & easy items**: UM-D-1, UM-D-2 (constants), UM-E-3..13 (small items).
6. **Day 5–7 — User-management refactors**: UM-C-1 through UM-C-9 (cognitive complexity). One function per commit, run tests after each.
7. **Week 2 — Project-management constants & MAJOR**: PM-E-1..15 (constants), PM-H (shadow builtin), PM-G (unused param), PM-I, PM-J (small ones), PM-M (snake_case in dashboard/tree routes), PM-O, PM-P, PM-Q (idioms).
8. **Week 2 — Project-management real bugs**: PM-D-1..8 (S5727 identity check — verify each one, may be real bugs).
9. **Weeks 3–4 — Project-management complexity refactors**: PM-C-1..49. Start with the worst (134, 126, 100, 100), one per commit, test after each.
10. **Wrap-up**: re-scan all four services with correct SonarQube project keys, confirm count drops.

---

## 8 · Files referenced

| Path | Purpose |
|---|---|
| `C:\Users\WC544QK\AppData\Local\Temp\pmis_pm_Issues.tsv` | Raw 293 issues from project-management report (= user-mgmt scan) |
| `C:\Users\WC544QK\AppData\Local\Temp\pmis_pm_Issues_dedup.tsv` | 248 deduped (collapses `src/` duplicates) |
| `C:\Users\WC544QK\AppData\Local\Temp\um_Issues.tsv` | user-management raw 293 |
| `C:\Users\WC544QK\AppData\Local\Temp\um_Issues_dedup.tsv` | user-management 248 deduped |
| `C:\Users\WC544QK\AppData\Local\Temp\ms_Issues.tsv` | master raw + deduped 143 |
| `C:\Users\WC544QK\AppData\Local\Temp\ms_Issues_dedup.tsv` | master 143 |
| `C:\Users\WC544QK\AppData\Local\Temp\ns_Issues.tsv` | "notification-service" raw 588 (= project-mgmt scan) |
| `C:\Users\WC544QK\AppData\Local\Temp\ns_Issues_dedup.tsv` | project-management 422 deduped |
| `C:\Users\WC544QK\AppData\Local\Temp\*_SecHotspots.tsv` | per-report security hotspots |

Whoever picks up these fixes can grep those TSVs for any item ID needing the exact raw line.
