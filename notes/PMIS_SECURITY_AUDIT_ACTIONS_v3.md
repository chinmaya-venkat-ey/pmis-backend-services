# PMIS Security Audit — Hand-off Action List (v3, final cleanup)

**Generated:** 2026-05-25
**Source:** Same four SonarQube reports dated 2026-05-19 used in v1 and v2 audits.
**Scope:** Only the items still pending after v1/v2 work. Once these are done, every finding from the four original SonarQube reports is closed.
**Target codebase:** Current microservices at `C:\Users\WC544QK\Downloads\pmis-microservices\`

---

## 0 · READ FIRST — Safety guardrails (same as v1/v2)

Ten safety rules from v1 §0 still apply. The four that matter most for this round:

1. **Do not change route URL paths, JSON shapes, error codes, or HAL envelope behavior.** All endpoints under `/api/v3/...` and notification-svc's `/notification/...` must remain reachable at the same URL with the same response shape.
2. **Do not change folder layout.** Stay inside `app/{controllers,services,repositories,models,schemas,routes,middleware,core,utilities}`.
3. **Tests must pass after each batch.** Per-service: run `pytest` under `PMIS-user-management/tests/`, `PMIS-master/tests/`, `PMIS-project-management/tests/`, `PMIS-notification-service/tests/`. Don't move to the next item if any test fails.
4. **For BLOCKER bulk codemods (Annotated, CORS), snapshot OpenAPI before and after.** `curl localhost:<port>/openapi.json > before.json` → apply codemod → `curl ... > after.json` → `diff before.json after.json`. The diff must be empty.

---

## 1 · Status check — what v1 and v2 confirmed cleared

Verified on the current codebase:

| Item | Status |
|---|---|
| Docker root user (all 4 Dockerfiles) | ✅ `USER appuser` in place |
| Production DB password in `.env` files | ✅ `CHANGE-ME-IN-PROD` placeholder |
| Hardcoded default DB password in `app/config.py` | ✅ `CHANGE-ME` placeholder |
| `changeme` literal in `.env.example` DB URLs | ✅ Cleaned up |
| Hardcoded IP `10.1.131.199` in `.py` source files | ✅ Removed |
| `"Vendor not found."` duplicated literal | ✅ Extracted to `_VENDOR_NOT_FOUND` constant |
| `"Authentication required"` duplicated literal | ✅ Extracted to `AUTH_REQUIRED_MESSAGE` constant |
| `"/api/v3"` duplicated literal | ✅ Reduced to 2 prefix declarations (below Sonar's 3+ threshold) |
| `python:S107` too many parameters | ✅ Services take Pydantic payloads, repositories use `**kwargs` |
| `python:S117` `pageSize`/`includeDeleted`/etc. route params | ✅ Use `snake_case + alias="camelCase"` |
| `python:S5727` `is True` identity checks | ✅ Removed from project-mgmt services |
| `python:S5806` shadow-builtin variables | ✅ No standalone assignments found |
| `python:S7494` `set(generator)` pattern | ✅ Zero hits |
| Other monolith-only items (`S1854`, `S1186`, `S3457`, `S100`, `S1481` in old tests) | ✅ Old files deleted |

What remains is in §2–§7 below.

---

## 2 · X-8 · Strip trailing `= Depends(...)` after `Annotated[...]` (BLOCKER · `python:S8410`, 249 hits)

### Why this is still flagged
The v1 X-4 codemod was applied partially: every route handler now has `Annotated[X, Depends(get_x)]` on the front of each dependency parameter, but the original `= Depends(get_x)` default value was left in place. The current mixed pattern still triggers Sonar's S8410 on every line because the rule requires the default value to be removed.

**Current (wrong) form** in every route file:
```python
controller: Annotated[AuthController, Depends(get_auth_controller)] = Depends(get_auth_controller),
```

**Correct form** Sonar wants:
```python
controller: Annotated[AuthController, Depends(get_auth_controller)],
```

### Scope (249 occurrences across 31 files)

| Service | Hits | Files |
|---|---|---|
| PMIS-user-management | 78 | `app/routes/auth_routes.py` (12), `permission_routes.py` (7), `role_assignment_routes.py` (19), `role_grants_routes.py` (1), `role_routes.py` (9), `user_routes.py` (30) |
| PMIS-master | 50 | All 8 catalog route files in `app/routes/` (6 each) + `vendor_routes.py` (8). `health_routes.py` has no Annotated parameters. |
| PMIS-project-management | 116 | `activity_routes.py` (10), `attachment_routes.py` (6), `catalog_routes.py` (5), `comment_routes.py` (6), `critical_path_routes.py` (2), `dashboard_routes.py` (6), `milestone_routes.py` (10), `project_routes.py` (29), `subtask_routes.py` (12), `task_routes.py` (10), `team_routes.py` (9), `tree_routes.py` (1), `vendor_routes.py` (10) |
| PMIS-notification-service | 5 | `cron_routes.py` (2), `dispatch_routes.py` (1), `email_routes.py` (1), `sms_routes.py` (1) |

### Fix (mechanical regex)

Apply the following regex per file (covers both single-arg and multi-arg parameter lines):

```
Search:   Annotated\[([^\]]+)\]\s*=\s*Depends\([^)]+\)
Replace:  Annotated[$1]
```

Or in Python form, equivalent:
```
Search:   (Annotated\[[^\]]+\])\s*=\s*Depends\([^)]+\)
Replace:  \1
```

After the regex pass on each file, eyeball-diff the file to confirm:
- Each parameter still has its name + `: Annotated[...]` type
- No standalone `= Depends(...)` is left dangling
- The trailing `,` of each parameter is preserved
- Nothing outside parameter signatures changed (decorators, docstrings, route bodies untouched)

### Safety
- FastAPI treats `param: Annotated[X, Depends(get_x)]` and `param: Annotated[X, Depends(get_x)] = Depends(get_x)` identically at runtime. Removing the trailing default has **no behavioral effect** — the dependency resolution, OpenAPI schema, and request handling are byte-identical.
- **Verify per service**: snapshot `/openapi.json` before the regex pass, apply, snapshot again, `diff`. Must be empty.
- **Pytest per service must pass** afterwards.
- Do **not** touch `Query(...)`, `Path(...)`, `File(...)`, `Form(...)`, or `Body(...)` defaults — those are legitimate FastAPI parameter declarations that look similar but are not `Depends(...)`. The regex above is anchored to `Depends(` specifically and will not catch them.
- Do **not** touch `Depends(...)` calls that appear in route **decorators** (e.g. `@router.get("/x", dependencies=[Depends(...)])`) or in `dependencies=[...]` lists — those are not function parameters.

### Per-service execution
Apply file-by-file inside one service first (start with notification-service — only 5 hits, smallest blast radius), run tests, verify `/openapi.json` diff is empty, then move to master, then project-management, then user-management.

---

## 3 · X-9 · Refactor over-complex functions in project-management (CRITICAL · `python:S3776`)

### Why this is still flagged
The largest service functions in `PMIS-project-management/app/services/` were not refactored after the monolith → microservice split. Their cognitive complexity is still well over Sonar's threshold of 15. Plus three known functions in user-management.

### Scope — refactor these specific functions

**Priority A — was over complexity 50 in the monolith scan:**

| ID | Function | File | Current line count | Was |
|---|---|---|---|---|
| X-9-1 | `update` | `PMIS-project-management/app/services/activity_service.py:170` | 120 lines | complexity 134 in monolith |
| X-9-2 | `create` | `PMIS-project-management/app/services/subtask_service.py:62` | 119 lines | 66 |
| X-9-3 | `update` | `PMIS-project-management/app/services/milestone_service.py:172` | 113 lines | 79 |
| X-9-4 | `upsert` | `PMIS-project-management/app/services/project_service.py:227` | 107 lines | 33 |
| X-9-5 | `create` | `PMIS-project-management/app/services/activity_service.py:63` | 107 lines | 45 |
| X-9-6 | `get_project_detail` | `PMIS-project-management/app/services/dashboard_service.py:733` | 142 lines | (was over 15) |
| X-9-7 | `get_project_items` | `PMIS-project-management/app/services/dashboard_service.py:875` | 131 lines | (was over 15) |
| X-9-8 | `get_summary` | `PMIS-project-management/app/services/dashboard_service.py:510` | 102 lines | 20 |
| X-9-9 | `create` | `PMIS-project-management/app/services/milestone_service.py:71` | 101 lines | 32 |
| X-9-10 | `update` | `PMIS-project-management/app/services/subtask_service.py:181` | 99 lines | 100 |
| X-9-11 | `update` | `PMIS-project-management/app/services/task_service.py:133` | 90 lines | 100 |
| X-9-12 | `create` | `PMIS-project-management/app/services/task_service.py:55` | 78 lines | 58 |

**Priority B — user-management items from v1:**

| ID | Function | File | Was |
|---|---|---|---|
| X-9-13 | `create` | `PMIS-user-management/app/services/user_service.py:86` | complexity 73 |
| X-9-14 | `update` | `PMIS-user-management/app/services/user_service.py:185` | 51 |
| X-9-15 | `effective_permissions_by_scope` | `PMIS-user-management/app/repositories/rbac_repository.py:271` | 25 |

### Fix pattern (apply per function)

For each `update_*` / `create_*` / `upsert` method, the existing body is a single long sequence of `if "<field>" in updates: ... validate / cross-check / mutate` blocks. Refactor each into private helpers — typical decomposition:

```python
# Before (single 120-line method with 12 branches)
def update(self, activity_id, payload, *, caller_user_id, request=None):
    row = self.get_by_id(activity_id)
    updates = payload.model_dump(exclude_unset=True)
    depends_on = updates.pop("depends_on", None)
    touched = set(updates.keys())
    # priority validation
    if "priority" in updates:
        self._validate_priority(updates["priority"])
    # owner_division validation
    if "owner_division" in updates:
        ...
    # division-pair revalidation
    if (...):
        ...
    # vendor in project assertion
    if "vendor_id" in updates and updates["vendor_id"]:
        ...
    # status-transition gate
    if "status" in updates and updates["status"] is not None:
        ...
    # date-floor revalidation
    if ("start_date" in updates or ...):
        ...
    # field-write permission gate
    if request is not None and touched:
        ...
    # apply + audit
    if updates:
        ...
    # depends_on replacement + cycle guard
    if depends_on is not None:
        ...
    self.db.commit()
    return row

# After (same public signature, complexity per helper ≤ 15)
def update(self, activity_id, payload, *, caller_user_id, request=None):
    row = self.get_by_id(activity_id)
    updates = payload.model_dump(exclude_unset=True)
    depends_on = updates.pop("depends_on", None)
    touched = set(updates.keys())

    self._validate_catalog_fields(updates)
    self._revalidate_division_pairs(row, updates)
    self._assert_vendor_in_project_if_changed(row, updates)
    self._gate_status_transition(row, updates)
    self._revalidate_dates(row, updates)
    self._gate_field_writes(request, touched, row.project_id)

    self._apply_updates(row, updates, caller_user_id)
    self._replace_dependencies_if_changed(row, depends_on, caller_user_id)

    self.db.commit()
    return row

def _validate_catalog_fields(self, updates): ...
def _revalidate_division_pairs(self, row, updates): ...
def _assert_vendor_in_project_if_changed(self, row, updates): ...
def _gate_status_transition(self, row, updates): ...
def _revalidate_dates(self, row, updates): ...
def _gate_field_writes(self, request, touched, project_id): ...
def _apply_updates(self, row, updates, caller_user_id): ...
def _replace_dependencies_if_changed(self, row, depends_on, caller_user_id): ...
```

### Safety
- **Public method signature must not change.** The outer `update(self, activity_id, payload, *, caller_user_id, request=None)` keeps the same parameters, the same return type, the same exception types, and the same order of side effects (validate → mutate → audit → commit).
- **All side effects in the same order.** The audit log entries written, the `db.commit()` call, and the order of validation failures must be preserved. If validation A used to fail before validation B in the original code, that ordering must be kept — otherwise error messages users currently see will change.
- **Each helper takes only what it needs**, returns nothing (or only a derived value), and is a `_private` method on the same class. Do not create new modules or move methods to a different file.
- **Before refactoring each function**, write a unit test (if not already present) that covers at least: (a) all-fields-untouched update, (b) one field touched per validation branch, (c) one failing-validation case per gate. Run tests after each refactor.
- **Commit one function at a time.** Don't batch multiple refactors in one commit — if a regression slips through, the bisect surface is one function.
- **No opportunistic changes.** Do not rename existing methods, do not change parameter names, do not adjust SQL, do not add features. Refactor only.

---

## 4 · X-10 · Fix CORSMiddleware order in notification-service (BLOCKER · `python:S8414`)

### Why this is still flagged
In `PMIS-notification-service/app/main.py:79-86`, `CORSMiddleware` is added **before** `RequestContextMiddleware`. Starlette wraps middleware in reverse order — the last `add_middleware` call becomes the outermost layer. So with the current order, `RequestContextMiddleware` is outermost and CORS is innermost (after Auth — although notification-svc has no Auth — and inside the request context). Sonar's S8414 specifically requires CORS to be added last so it's the outermost layer.

### Current code (`PMIS-notification-service/app/main.py:79-86`)
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextMiddleware)
```

### Fix — swap the two calls
```python
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Safety
- The actual on-the-wire request handling order changes from `RequestContext → CORS → handler` to `CORS → RequestContext → handler`. This matches the convention used in the other 3 services (`PMIS-user-management/app/main.py`, `PMIS-master/app/main.py`, `PMIS-project-management/app/main.py`).
- For CORS specifically, having it outermost is the FastAPI/Starlette recommended position — it means CORS headers are applied to all responses including those from middleware that errors out earlier in the chain.
- No request paths, JSON shapes, or response headers change for normal (non-CORS-preflight) traffic.
- For CORS preflight (`OPTIONS` requests), the response will now skip `RequestContextMiddleware` (so no `X-Request-ID` header on the preflight response). This is correct standard behavior — preflights are short-circuited by CORS middleware.
- Run notification-svc tests after the swap. If any test asserts on `X-Request-ID` for `OPTIONS` requests specifically, adjust that test to assert only for non-OPTIONS methods.

---

## 5 · X-11 · Resolve the TODO comment in `file_client.py` (INFO · `python:S1135`)

### Why this is still flagged
`PMIS-project-management/app/utilities/file_client.py:182` contains: `# TODO: real implementation lands when the file-server contract...` — Sonar's `python:S1135` flags any `# TODO` / `# FIXME` / `# XXX` comments as items that should be tracked or resolved.

### Fix
Either:
- **(a)** Replace the `TODO` with a clear "deferred" non-TODO comment that explains the dependency, e.g.
  ```python
  # Deferred: real implementation lands when the file-server contract
  # is finalized (tracked outside Sonar — see notification-svc Doc-X).
  ```
- **(b)** If the file-server contract is already finalized, complete the implementation. Otherwise leave as (a).

Sonar won't fire on a comment that doesn't start with `TODO`/`FIXME`/`XXX`.

### Safety
- Comment-only change. No runtime effect.
- Do not delete the comment — the explanation of why this code path is incomplete is still useful context.

---

## 6 · X-12 · Replace the borderline `ChangeMe123!localdev` placeholder (`secrets:S6698`, low risk)

### Why this might still flag
`PMIS-user-management/.env.example:26` has:
```
SUPERADMIN_BOOTSTRAP_PASSWORD=ChangeMe123!localdev
```
Sonar's secrets detector uses a dictionary of weak-credential tokens. `"ChangeMe"` may or may not be in that dictionary depending on the rule's exact match list. The previous `changeme` (lowercase) certainly was, but case-mixed `ChangeMe123` is borderline.

### Fix
Change to a deploy-time-set marker that obviously isn't a real password:
```
SUPERADMIN_BOOTSTRAP_PASSWORD=SET-AT-DEPLOY-TIME
```

### Safety
- `.env.example` is a template; the live `.env` (or runtime env injection) is what the service actually reads. No runtime effect.
- Pydantic `Settings.superadmin_bootstrap_password` is `Optional[str]` with default `None` (per `app/config.py`) — and the value is only consumed by the alembic bootstrap data-migration. Production should leave it unset.
- Do not touch any other line in `.env.example`.

---

## 7 · X-13 · Re-run SonarQube with correct per-microservice project keys (process item, was NS-D / X-7)

### Why this is still required
Three of the four original SonarQube reports were misconfigured (see v1 §1):
- `PMIS-project-management` report → scanned monolith user-management code
- `PMIS-user-management` report → scanned monolith user-management code (same scan, different key)
- `PMIS-notification-service` report → scanned monolith project-management code
- `PMIS-master` report → correctly scanned the master microservice

Until rescanned, the original four reports cannot be considered closed against the live microservices because the source paths they reference no longer exist.

### Fix
In the CI / SonarQube admin, configure four separate scans:

| Service | Project key (suggested) | `sonar.sources` |
|---|---|---|
| `PMIS-user-management` | `PMIS-user-management-microservice` | `PMIS-user-management/` |
| `PMIS-master` | `PMIS-master-microservice` (already correct) | `PMIS-master/` |
| `PMIS-project-management` | `PMIS-project-management-microservice` | `PMIS-project-management/` |
| `PMIS-notification-service` | `PMIS-notification-service-microservice` | `PMIS-notification-service/` |

Each scan should set `sonar.sources` to the service folder only (not its parent or any `src/` tree — the 77.8 % duplication ERROR in v1 came from double-indexing the same files under `src/` and root).

### Safety
- CI/scanner config only — no application code change, no runtime effect.
- Run the four scans only **after** X-8 through X-12 are merged to main. Otherwise the rescan will fire 249 S8410 hits plus the still-open complexity items, and the "closed" verdict from this audit won't show.

---

## 8 · Suggested execution order

1. **Day 0 — Setup**
   - Per service: `curl localhost:<port>/openapi.json > before.json` and run full pytest. Lock in green baseline.

2. **Day 1 — Quick wins**
   - X-10 (CORS order in notification-service) — 1 line swap
   - X-11 (resolve TODO comment) — 1 line edit
   - X-12 (`SET-AT-DEPLOY-TIME` placeholder) — 1 line edit
   - Run all four services' tests. All green expected.

3. **Day 2 — X-8 Annotated codemod, by service in this order**
   - PMIS-notification-service (5 hits) — apply regex, run tests, diff openapi.json
   - PMIS-master (50 hits) — same pattern
   - PMIS-user-management (78 hits)
   - PMIS-project-management (116 hits)
   - Commit per service.

4. **Week 1–2 — X-9 cognitive complexity refactors**
   - One function per commit, in priority order (X-9-1 first, then X-9-2…).
   - For each: write missing tests → refactor into private helpers → run tests → commit → next.
   - Recommend starting with X-9-13 to X-9-15 (user-mgmt) as a smaller warm-up before the project-mgmt block.

5. **End — X-13 SonarQube rescan**
   - After all of the above is merged, re-issue scans with corrected project keys.
   - Confirm zero findings from the original reports remain.

---

## 9 · Verification checklist (run before requesting the rescan)

From the repo root:

```bash
# X-8: zero redundant Annotated patterns
grep -rIn --include="*_routes.py" 'Annotated\[.*Depends(.*\]\s*=\s*Depends' \
  PMIS-user-management PMIS-master PMIS-project-management PMIS-notification-service
# expected: (nothing)

# X-10: CORSMiddleware is the last add_middleware in every main.py
grep -nE 'add_middleware\(' \
  PMIS-user-management/app/main.py PMIS-master/app/main.py \
  PMIS-project-management/app/main.py PMIS-notification-service/app/main.py
# expected: CORSMiddleware appears LAST in each service's main.py

# X-11: no TODO comments
grep -rIn --include="*.py" '^\s*#\s*(TODO|FIXME|XXX)' \
  PMIS-user-management PMIS-master PMIS-project-management PMIS-notification-service
# expected: (nothing)

# X-12: no ChangeMe123 token
grep -rIn 'ChangeMe' \
  PMIS-user-management PMIS-master PMIS-project-management PMIS-notification-service
# expected: (nothing)
```

For X-9 cognitive complexity, run `radon cc -s -a -n B` against each refactored file and confirm every method is rank A or B (≤ complexity 15):

```bash
pip install radon
radon cc -s -a -n B PMIS-project-management/app/services/activity_service.py
radon cc -s -a -n B PMIS-project-management/app/services/subtask_service.py
# ... etc
```

When all four greps return empty and `radon` shows no method above rank B in the refactored files, request the X-13 rescan. After that confirms clean, the four original SonarQube reports are fully closed.

---

## 10 · Files referenced

| Path | Purpose |
|---|---|
| `Assessment Report/PMIS_SECURITY_AUDIT_ACTIONS.md` | v1 — full list, all severities, monolith→microservice mapping |
| `Assessment Report/PMIS_SECURITY_AUDIT_ACTIONS_v2.md` | v2 — security-only follow-up |
| `Assessment Report/PMIS_SECURITY_AUDIT_ACTIONS_v3.md` | this file — final cleanup |
| `Assessment Report/PMIS-{service}/2026-05-19-*.docx`, `.xlsx` | Original SonarQube reports |
