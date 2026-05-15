# PMIS Refactor — Decisions

Captured 2026-05-14. User answers are quoted verbatim. Items prefixed
**DERIVED:** are my consequent interpretations, not user statements — flag
any that misread the intent.

---

## 1. Rollout strategy

> "I want to effectively run this as a new app, which has no dependency on
> the monolith, but not lose any functionality in the process. There will
> be endpoints which will be removed since there are duplicates, redundant
> apis and deprecated ones as well. In the meantime, before the process,
> ensure that all meaningful apis belong to the most appropriate service,
> and each api belongs to at least one service so that it is not lost
> prematurely."

**DERIVED:**
- This is **not a strangler migration**. It's **parallel-build → validate → cutover**: the new tree at `PMIS-refactor/` stands up as an independent app with zero runtime dependency on `PMIS-OpenProject` (the monolith).
- Functionality-loss prevention is gated by the Phase 1 **endpoint reconciliation table** in `AUDIT.md`. Every endpoint in the current system must have a documented disposition (`keep / move-to-<svc> / merge-with-<other> / delete-deprecated / rename-to-<new>`) before any porting begins. Nothing falls through the cracks because nothing gets ported until it's been classified.
- Removal decisions (duplicates / redundant / deprecated) happen explicitly during reconciliation, not silently during porting.

---

## 2. Scope

> "All services in scope. Do not break into very complicated structure with
> sub-modules etc. since that will make it harder for readability flow."

**DERIVED:**
- User, project, notification, masters — all four backend services in scope.
- Folder-shape priority: **flat and readable** wins over **deeply organized**. The notification-service shape (`db/`, `controllers/`, `routes/`, `config/`, `middleware/`, `schemas/`, `services/`, `tests/`) is the ceiling on nesting, not the floor. No sub-packages inside `routes/` etc. unless a single service really has 30+ files in one folder.

---

## 3. Deployment target

> "Currently this is being deployed by using docker compose."

**DERIVED:**
- Target is `docker-compose.yml` at `PMIS-refactor/` root with services: `nginx`, `user`, `project`, `notification`, `masters`, `postgres`, `frontend`. K8s is not in scope.

---

## 4. Database strategy

> "follow recommendation, but I want it to be such that inter service
> communication does not get disrupted. Having a staging db is a good idea
> since alembic migrations have been the biggest problem for us in terms
> of deployments breaking."

**DERIVED:**
- **Single Postgres, per-service schemas:** `user.`, `project.`, `notification.` (likely empty — stateless), `masters.`.
- **Inter-service communication must not break.** Two angles to call out in the plan:
  1. **Cross-service HTTP calls** (e.g. monolith → user-svc today): the audit will catalog every internal HTTP call. The new app keeps them working — services discover each other via docker-compose hostnames.
  2. **Cross-schema FK constraints** (e.g. `project.memberships.user_id → user.users.id`): allowed within a single Postgres instance and preserved where they exist today. Will be enumerated in the schema audit.
- **Staging DB is in scope.** Plan will include a throwaway `docker-compose -f docker-compose.staging.yml` Postgres against which every Alembic migration is run before it touches the real DB. Alembic coordination across four services is a known pain point and gets a dedicated section in `PLAN.md`.

---

## 5. Contract stability

> "5. Yes, it uses one base url at the moment with one port that it hits.
> this will become the nginx route. 5b recommendation accepted. response
> shape changes should be kept minimal, but not necessarily identical."

**DERIVED:**
- Frontend has a single configurable base URL. Changing all paths from `/api/v3/*` to `/<service>/*` is a **one-line FE config change**, not a sweep. (Will verify in Phase 1 by reading the FE API client.)
- Response shapes: **keep changes minimal**. Field renames and envelope changes need explicit justification in `AUDIT.md` and are listed in the `PLAN.md` "Breaking changes" section. Drift cleanup is welcome; gratuitous reshaping is not.

---

## 6. Grey-area ownership

> "the suggested ownership structure is fine, but I am telling you at this
> stage that there are also legacy modules such as work packages and
> meetings and an old implementation of project modules which are not
> going to be used in the current working app. these will be removed at
> some stage, so prepare for this as well. the caveat makes sense."

**Accepted ownership map:**

| Table / domain | Service |
|---|---|
| `permissions` | user |
| `roles` | user |
| `memberships` (user↔project) | project |
| `work_packages` | **LEGACY — flagged for removal** |
| `meetings` | **LEGACY — flagged for removal** |
| Old project-module implementation | **LEGACY — flagged for removal** |
| `project_status_transitions` | masters |
| `vendors`, `divisions`, `resource_types` | masters |

**DERIVED:**
- The audit gets a **fourth disposition category for endpoints/tables: `legacy-exclude`** alongside keep / move / merge / delete / rename. Legacy items are **enumerated, cited, and reported in `AUDIT.md`** so we have a complete removal manifest — but they are **not ported into `PMIS-refactor/`**.
- Need user confirmation in Phase 1 on the boundary between "legacy work_packages" and any non-legacy use. If a current screen reads from `work_packages`, that's a contradiction I'll surface, not resolve silently.
- Caveat acknowledged: if the audit shows a legacy table has a hard FK from a kept table, I'll re-raise.

---

## 7. Auth strategy

> "auth strategy is accepted."

**DERIVED:**
- Status quo: shared `SECRET_KEY`, each service decodes JWTs locally.
- JWT verification logic lives in **one canonical copy** (in user-service) and is duplicated into the other three services with a header comment pointing back. No shared-lib package — the per-file copy keeps services independently deployable, which matches Decision 1.

---

## 8. Nginx

> "I do not want to worry about nginx implementation as the devops person
> is taking care of those decisions. Please let me know if any of these
> decisions impact the code and if yes, I will help you with the
> decisionmaking. Supply your recommendation along with the requirement
> as well."

**DERIVED:** Nginx config itself is devops-owned. The follow-up answers
below cover only the items where the nginx decision forces a code-side
decision.

### 8a. Corporate base path

> User: "follow recommendation."

- Services have **no hardcoded base path**. Each reads a `ROOT_PATH` env
  var (default `""`) and passes it to `FastAPI(root_path=...)`. Devops can
  put the app under `/pmis/` or any other prefix at deploy time with zero
  code change. OpenAPI docs and redirects work correctly under either.

### 8c. Body-size limits / max upload

> User: "i do not know about this much so make a decision as per your
> recommendation."

- **Default `MAX_UPLOAD_MB=50` per service, env-configurable.** Project
  service (the only one expected to take uploads — attachments) enforces
  this in the upload handler so an oversized request returns 413 cleanly
  instead of OOMing the container.
- **[NEEDS VERIFICATION in Phase 1]** Audit will check what file sizes
  the current attachment flow actually handles (look at the existing
  upload handler + any size checks). If real files exceed 50 MB I'll
  raise it at Checkpoint 2 and tell devops to match in nginx.
- **Contract with devops:** whatever `MAX_UPLOAD_MB` ends up at, nginx's
  `client_max_body_size` must match. Mismatch is a bug.

### 8d. Health checks

> User: "yes, recommended."

- Every backend service exposes:
  - `GET /health` — process-alive check, returns 200 with no DB hit.
  - `GET /ready` — readiness check, returns 200 only if the DB ping
    succeeds (and any other critical dep, e.g. notification service's
    SMTP config validation).
- These routes are **outside** the standardized `/<service>/*` prefix
  scheme — they live at the service root because devops/orchestrator
  hits them via the container's internal port, not through nginx.

### 8e. CORS

> User: "recommended."

- **Nginx owns CORS in production** — single source of truth, set by
  devops.
- Each service includes `CORSMiddleware` **only when `ENV=development`**,
  so a dev can hit the service directly (`localhost:8001` etc.) without
  going through nginx. In any other `ENV`, the middleware is not
  registered, so no duplicate-header bugs in prod.

---

## Phase 1 — Audit reconciliation (Checkpoint 2)

Resolves the 25 open questions in `AUDIT.md` §7 after reading the audit.
Listed with user answer + my interpretation. **DERIVED:** entries are my
consequent reading; flag any that misread.

### Q1. Vendors ownership and naming

> User: "'vendors', which will be replaced with the word 'organization'
> across the app is owned by masters since organizations can be added
> and deleted and the new ones can be used in projects and users etc.
> This should be fully configurable, and therefore lie inside masters."
> *(Later clarification:)* "don't do the vendor to organization
> migration, this is too much overhead, frontend manages the distinction"

- **vendors stay in masters-svc** (cross-schema FK targets from
  `user.user_role_assignments.organization_id`, `user.users.vendor_id`,
  `project.project_vendors.vendor_id`, etc.).
- **NO rename to organizations** at the DB / API / response-shape level.
  BE keeps `vendor`, `vendor_id`, `vendor_code`, etc. FE renders the
  label "Organization" in the UI but reads `vendor_*` fields from the
  wire.
- The "fully configurable" requirement is satisfied by masters-svc
  owning the CRUD endpoints (admin can add/delete vendors at runtime).

### Q2. `/api/v3/priorities` (picker) vs `/masters/priorities` (CRUD)

> User: "read priorities from masters, this is also configurable"

- **Unified into `/masters/priorities`** with tiered auth:
  - GET endpoints: auth-only (picker use case)
  - POST/PATCH/DELETE: `MASTER_DATA_MANAGE`
- FE picker calls the same path as the CRUD list.

### Q3. notification_templates location

> User: "notification templates can be modified, edited, and stored and
> retrieved from db, this will be in masters"

- **Move ownership of `notification_templates` from notification-svc to
  masters-svc.** CRUD lives at `/masters/notification_templates/*` with
  the same tiered auth as Q2 (GET auth-only, writes MASTER_DATA_MANAGE).
- **notification-svc reads `masters.notification_templates`
  cross-schema** for dispatch rendering (option Q11(b) pattern). No
  HTTP round-trip for template lookup.
- **DERIVED:** with this and Q13, notification-svc owns ZERO tables
  post-refactor. It's the truly-stateless dispatcher the original brief
  described.

### Q4. 5 declared-but-uncalled FE endpoints

> User: "Ensure that they are dead before deleting."

- In Phase 3 implementation, grep `src/components/**` and `src/pages/**`
  for `ENDPOINTS.{milestones,activities,tasks,subtasks}.attachments`
  and `ENDPOINTS.roles.list`. If no caller found, mark
  `delete-deprecated`. Otherwise, port.

### Q5. Legacy catalogs router paths

> User: "check what purpose they serve, what functionality they enable,
> and keep these in masters and as configurable."
> *(Confirmed:)* project_status_transitions included.

- **Three paths** consolidated into masters with the Q2-style tiered
  auth pattern:
  - `/api/v3/divisions` (legacy) + `/api/v3/master/divisions` →
    **single `/masters/divisions`** (GET auth-only, writes
    MASTER_DATA_MANAGE).
  - `/api/v3/resource_types` (legacy) + `/api/v3/master/resource_types`
    → **single `/masters/resource_types`** (same pattern).
  - `/api/v3/project_status_transitions` (legacy) +
    `/api/v3/master/project_status_transitions` →
    **single `/masters/project_status_transitions`** (same pattern).
- **DERIVED uniform rule:** every `/masters/*` resource has GET
  endpoints at auth-only and writes at `MASTER_DATA_MANAGE`. Applies to
  divisions, vendors, resource_types, project_categories, activity_types,
  activity_statuses, milestone_statuses, project_status_transitions,
  priorities, notification_templates.

### Q6. Project-scoped role-assignments path shape

> User: "keep the path-shape (`/user/projects/{uuid}/role-assignments`)."

- Path-style preserved. Lives in user-svc (RBAC domain).

### Q7. Project audit-logs scope

> User: "keep project-scoped only. the user information is required for
> project change audit, but it is primarily function of project."

- `project.project_audit_logs` stays in project-svc. user-svc actor
  info pulled via cross-schema read.
- No global `/user/audit-logs` endpoint in this refactor.

### Q8. `controllers/` layer

> User: "Keep controllers there, this is requested functionality to
> understand the caller more easily. this may be inefficiency, but is
> required across services."

- **`controllers/` layer kept in all four services** (user, project,
  notification, masters).
- Pattern: `routes/` does binding + validation + DI; `controllers/`
  unpacks request, calls service(s), shapes response. `services/`
  holds business logic.
- This promotes notification-svc's current half-adoption to full
  adoption — every route gets a controller.

### Q9. `services/` layout

> User: "follow recommendation"

- **Flat `services/<resource>_service.py`** per resource. No verb-per-
  file nesting.

### Q10. `domain/` directory

> User: "follow recommendation"

- **Drop `domain/`.** SQLAlchemy 2.0 declarative models carry domain
  semantics directly. Any computed properties co-locate with the model.

### Q11. Cross-schema RBAC reads

> User: *(after clarification on cache vs data copy)* "follow
> recommendation"

- **Option (b): cross-schema ORM declarations.** Each non-user service
  ships read-only SQLAlchemy class declarations for `user.role_permissions`,
  `user.user_roles`, `user.user_permissions`, `user.user_role_assignments`,
  `user.users`, `user.revoked_tokens` (and similarly for cross-domain
  reads into masters/project).
- **No data replication, no sync mechanism needed** — one Postgres,
  one physical table per resource. The "copies" are Python class
  declarations; data is shared via schema-qualified joins.
- Drift protection via Q24 CI test.

### Q12. `project_members` table residue

> User: "since the table is not used, just drop as per recommended methods.
> follow recommendation if that is what you said."

- Cutover migration: `DROP TABLE IF EXISTS project_members;` (idempotent).

### Q13. OTP store

> User: "follow recommendation"

- **OTP storage lives in `user.otp_codes`** (already exists as a table).
  notification-svc dispatches the code via SMS/email but does NOT track
  it. `POST /user/users/login/send-otp` writes the OTP record;
  `POST /user/users/login/verify-otp` validates against the same table.
- **notification-svc's `/api/v1/notifications/otp/{send,verify}`
  endpoints become legacy** — kept only if any non-FE caller still uses
  them; otherwise dropped.
- **DERIVED:** with Q3, notification-svc owns no tables, has no
  in-process state (besides config). Truly stateless dispatcher.

### Q14. `UNIVERSAL_OTP_ENABLED` backdoor

> User: "follow recommendation."

- **Keep flag**, but each service raises `RuntimeError` on startup if
  `ENV=production` AND `UNIVERSAL_OTP_ENABLED=True`. Code-enforced
  safety rail.

### Q15. Refresh-token grace window columns

> User: "follow recommendation."

- Keep `users.refresh_token_jti`, `users.previous_refresh_token_jti`,
  `users.previous_refresh_token_jti_valid_until` as-is.

### Q16. Boot-time DDL

> User: "follow recommendation."

- **Drop boot-time DDL.** `init_db()` does NOT run alembic and does NOT
  perform SQLite auto-heal. Migrations run separately via
  `docker-compose run --rm <service> alembic upgrade head` against
  staging then prod.

### Q17. Pre-Doc-26 integer-id JWT guard

> User: "follow recommendation."

- **Drop the guard.** Refresh tokens expire after 7 days; cutover window
  is shorter; any in-flight integer-id JWT is already expired.

### Q18. revoked_tokens caching

> User: "follow recommendation."

- **Status quo: DB query per authed request.** No caching layer unless
  profiling later shows it as a bottleneck.

### Q19. Migration order

> User: "follow recommendation."

- Order: **notification-svc → masters-svc → user-svc → project-svc.**
  Notification first (fewest tables — possibly zero owned post-Q3).
  Masters second. User next. Project last.

### Q20. Data migration strategy

> User: "create tables in new schema, copy rows, swap on a maintenance
> window."

- **Copy + cutover (option b).** For each per-service schema:
  1. Create new schema (e.g. `CREATE SCHEMA user;`).
  2. Create empty tables in new schema with target DDL.
  3. Copy rows from `public.<table>` to `<schema>.<table>`.
  4. On maintenance window: stop all services, point each service's
     `DATABASE_URL` at its new schema (via `search_path` or qualified
     names), validate, restart.
  5. Drop `public.<migrated_table>` after burn-in.
- **PLAN.md will detail the exact SQL + downtime estimate.**

### Q21. Bootstrap data

> User: "follow recommendation."

- Each service ships its own bootstrap as a separate alembic
  data-migration. Run once per env. No more boot-time seeding.

### Q22. MAX_UPLOAD_MB

> User: "25 is the current standard stick to that."

- **MAX_UPLOAD_MB=25** in project-svc config. Matches today's
  `ATTACHMENTS_MAX_BYTES=26214400`. nginx `client_max_body_size` must
  match.

### Q23. Sentry / observability

> User: "do not make it part of refactor, keep it as a suggestion for
> post refactor enhancements."

- No `sentry_sdk.init` in the new services. stdout logs only. Sentry
  integration listed as a Phase 4 enhancement in PLAN.md.

### Q24. Cross-schema drift CI test

> User: *(after Q11 clarification)* "follow recommendation"

- Add `tests/test_cross_schema_drift.py` in user-svc that imports the
  read-only RBAC model declarations from project-svc, notification-svc,
  masters-svc and asserts column names + types match the canonical
  declarations in user-svc. Run in CI for all four repos.

### Q25. Dead permission constants

> User: "follow recommendation."

- Drop `MEETINGS_*`, `WORK_PACKAGES_*`, `WORK_PACKAGE_TYPES_*`
  constants from active code in monolith and project-svc.
- Cutover migration: `DELETE FROM user.permissions WHERE code LIKE
  'meetings:%' OR code LIKE 'work_packages:%' OR code LIKE
  'work_package_types:%';`

---

### Cross-cutting clarifications captured during Q&A

**Inter-container HTTP:** docker-compose bridge network is internal;
service-to-service HTTP calls never touch the internet. No alternative
transport (gRPC, message queues, sockets) is being pursued — the
absolute latency wins don't justify operational cost at 4-service scale.

**Cross-schema "read-only copies":** there are no data copies. One
Postgres, one row per record, one schema-qualified table. The "copies"
are SQLAlchemy class declarations in each service that point at
schema-qualified tables in other domains. Schema changes are caught at
CI time by the Q24 drift test, not at runtime.

---

## 9. Other

> "Cannot think of any other changes at the moment. Only suggestion is
> keep all changes local, and once confirmed to be working after testing
> correctly, then it will be pushed to remote with all tests."

**DERIVED:**
- **No git push, no remote operations, no PRs** at any phase without explicit per-action approval.
- All work happens locally under `C:\Programming\PMIS-refactor\`.
- Tests must pass before the user is asked to push. The plan will define what "working correctly" means per service (test fixtures + manual smoke checklist).
