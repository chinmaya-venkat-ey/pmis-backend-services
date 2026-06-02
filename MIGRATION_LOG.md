# pmis-project-management — Migration Log

Fourth (and final) service ported in Phase 3 per Q19/Q29. Owns the `project` Postgres schema (16 tables). Source: `C:\Programming\PMIS\PMIS-OpenProject\app\` — the consolidated monolith — plus the per-table source models under `C:\Programming\PMIS\PMIS-OpenProject\app\infrastructure\db\models\`.

**Doc decisions applied** (callouts):
- **Q5 / Q6**: `meetings`, `work_packages`, `meeting_agenda_items`, `meeting_participants` dropped from scope. No tables, no routes.
- **Doc-22**: legacy `depends` JSON column removed from milestones; edges live in `milestone_dependencies` (already in the monolith; preserved).
- **Doc-24**: subtask nesting via `parent_subtask_id` is supported, with two partial-unique indexes anchoring positions per parent. Service-layer caps nesting at `settings.subtask_max_nesting_depth` (default 5).
- **Doc-33**: `cloned_from_id` versioning columns gone from milestones / activities / tasks / subtasks. Not ported.
- **Doc-35**: comments are "send events" — `body` is nullable; `attachments` is a JSONB list on the comment row; no separate attachments table.
- **Doc-38**: activity / task / subtask `type` column kept for legacy reads only; new writes do not require it. `resource_mode` / `resource_count` similarly deprecated but preserved for back-compat.
- **Doc-39**: `concerned_divisions` (JSONB list) added to activities; old single `concerned_division` column kept for legacy reads.
- **Doc-41**: `users.user_role_assignments` (cross-schema) drives the scoped permission map. `require_project_permission(code)` reads `request.state.scoped_permissions[("project", project_uuid)]`; global-scope holders pass every check. AuthMiddleware hydrates the scoped map via `RbacReadRepository.effective_permissions_by_scope`.
- **Doc-44**: caller-vs-target gates are deferred to follow-up (the first port wires the FSM but leaves vendor-vs-target comparisons for later).
- **Doc-46**: `ProjectRepository.list_` narrows visibility for non-admins to projects they have an assignment on OR projects mapped to their vendor.

## Source

| Topic | Source (path:line) |
|---|---|
| Project model | `C:\Programming\PMIS\PMIS-OpenProject\app\infrastructure\db\models\project.py:23` |
| Project routes + status FSM | `…\app\api\v3\projects\routes.py` + `…\services\transitions.py` |
| Milestone model + dep edge | `…\db\models\milestone.py:16`, `…\db\models\milestone_dependency.py` |
| Activity model | `…\db\models\activity.py:16` |
| Activity resource sidecar | `…\db\models\activity_resource.py:16` |
| Task model | `…\db\models\task.py:16` |
| Subtask model (Doc-24 nesting) | `…\db\models\subtask.py:30` |
| Comment model (Doc-35 send-event) | `…\db\models\comment.py:40` |
| Project-vendor M:N | `…\db\models\project_vendor.py` |
| Status transitions FSM (catalog read) | `services/pmis-masters-management/app/models/project_status_transition.py` |
| Audit log | New table (no monolith equivalent). Captures create/update/delete/restore/transition events. |

## Endpoint port table

All business routes under `/project/*`. Health probes (`/health`, `/ready`) at app root.

### Projects

| METHOD | NEW PATH | RBAC |
|---|---|---|
| GET | `/project/projects/list` | authenticated (Doc-46 filtered) |
| POST | `/project/projects/create` | `projects:create` |
| GET | `/project/projects/{uuid}/details` | `projects:read` scoped |
| PATCH | `/project/projects/{uuid}/update` | `projects:update` scoped |
| DELETE | `/project/projects/{uuid}/delete` | `projects:delete_all` |
| POST | `/project/projects/{uuid}/restore` | `projects:delete_all` |
| POST | `/project/projects/{uuid}/status/transition` | `projects:update` scoped + FSM edge |
| PUT | `/project/projects/{uuid}/vendors/replace` | `projects:update` scoped |

### Milestones

| METHOD | NEW PATH | RBAC |
|---|---|---|
| GET | `/project/projects/{uuid}/milestones/list` | `milestones:read` scoped |
| POST | `/project/projects/{uuid}/milestones/create` | `milestones:create` scoped |
| GET | `/project/milestones/{id}/details` | `milestones:read` |
| PATCH | `/project/milestones/{id}/update` | `milestones:update` |
| DELETE | `/project/milestones/{id}/delete` | `milestones:delete` |
| POST | `/project/milestones/{id}/restore` | `milestones:restore` |
| PUT | `/project/milestones/{id}/dependencies/replace` | `milestones:update` |
| PUT | `/project/milestones/{id}/vendors/replace` | `milestones:update` |

### Activities

| METHOD | NEW PATH | RBAC |
|---|---|---|
| GET | `/project/milestones/{id}/activities/list` | `activities:read` |
| POST | `/project/activities/create` | `activities:create` |
| GET | `/project/activities/{id}/details` | `activities:read` |
| PATCH | `/project/activities/{id}/update` | `activities:update` |
| DELETE | `/project/activities/{id}/delete` | `activities:delete` |
| POST | `/project/activities/{id}/restore` | `activities:restore` |
| PUT | `/project/activities/{id}/dependencies/replace` | `activities:update` |

### Tasks

| METHOD | NEW PATH | RBAC |
|---|---|---|
| GET | `/project/activities/{id}/tasks/list` | `tasks:read` |
| POST | `/project/tasks/create` | `tasks:create` |
| GET | `/project/tasks/{id}/details` | `tasks:read` |
| PATCH | `/project/tasks/{id}/update` | `tasks:update` |
| DELETE | `/project/tasks/{id}/delete` | `tasks:delete` |
| POST | `/project/tasks/{id}/restore` | `tasks:restore` |
| PUT | `/project/tasks/{id}/dependencies/replace` | `tasks:update` |

### Subtasks

| METHOD | NEW PATH | RBAC |
|---|---|---|
| GET | `/project/tasks/{id}/subtasks/list` | `subtasks:read` |
| POST | `/project/subtasks/create` | `subtasks:create` |
| GET | `/project/subtasks/{id}/details` | `subtasks:read` |
| PATCH | `/project/subtasks/{id}/update` | `subtasks:update` |
| DELETE | `/project/subtasks/{id}/delete` | `subtasks:delete` |
| POST | `/project/subtasks/{id}/restore` | `subtasks:restore` |
| PUT | `/project/subtasks/{id}/dependencies/replace` | `subtasks:update` |

### Comments (Doc-35 send-event)

| METHOD | NEW PATH | RBAC |
|---|---|---|
| GET | `/project/{kind}/{id}/comments/list` (×4 kinds) | `comments:read` |
| POST | `/project/{kind}/{id}/comments/create` (×4 kinds) | `comments:create` |
| DELETE | `/project/comments/{id}/delete` | `require_authenticated()` + author-or-admin check in controller |

`{kind}` is `milestones` / `activities` / `tasks` / `subtasks`; the controller resolves the underlying `project_id` so the audit log can attribute correctly.

## Tables created (alembic `p1a000000001`)

16 tables under `project` schema. Key design notes:

- `projects` — UUID PK; self-FK on `parent_id` via `use_alter`; soft-delete with deleted_at + deleted_by (logical FK to users.users.id).
- `project_vendors`, `milestone_vendors` — M:N edges to `masters.vendors.id` (logical-only; no DB constraint).
- `project_audit_logs` — append-only audit trail with JSONB `changes` column.
- `milestones` / `activities` / `tasks` — partial unique indexes (`postgresql_where=deleted_at IS NULL`) enforce position uniqueness per parent for LIVE rows. Soft-deleted rows can share positions with live ones (history preserved).
- `subtasks` — TWO partial unique indexes: one for top-level (`parent_subtask_id IS NULL`), one for nested (`parent_subtask_id IS NOT NULL`). Self-FK via `use_alter`.
- `*_resources` — 1:1 sidecars with a partial unique index per parent_id ensuring exactly one live resource row per parent.
- `*_dependencies` (4 tables) — directed edge tables. Composite PK on `(from, to)`. No DB-level cycle guard; service-layer walks the frontier.
- `comments` — polymorphic via `(target_kind, target_id)`. No FK on `target_id` (target lives in different tables per kind). `attachments` is a JSONB list per Doc-35.

## CHECK constraints

- `ck_<activities|tasks|subtasks>_type`: `type IS NULL OR type IN ('standard', 'resource', 'transactional')` (Doc-38 legacy values).
- `ck_<activities|tasks|subtasks>_resource_mode`: `IN ('count', 'details')` or NULL.
- `ck_<activities|tasks|subtasks>_resource_count_positive`: `>= 1` or NULL.

## Behaviour preserved vs. monolith

- UUID PKs on all primary entities (Doc-26).
- Display labels (M{n}, A{m}.{a}, T{m}.{a}.{t}, S{m}.{a}.{t}.{s1}[.{sN}]) driven by partial-unique position indexes.
- Doc-35 attachments-on-comment model (no separate attachments table).
- Per-level independent priority + assigned_to (per Doc-41 follow-up).
- Doc-38 type column kept nullable for legacy rows.
- HAL Collection envelope shape consistent with masters-svc / user-svc.
- Verb-suffix endpoint naming (POST `/create`, DELETE `/{id}/delete`, PUT `/replace`).

## Behaviour diverged from monolith (deliberate)

- All cross-schema FKs (vendor_id, type_of_resource_id, division, created_by, etc.) are LOGICAL only. No DB-level FK constraints across schemas; service layer enforces referential integrity.
- `project_audit_logs` is new — the monolith had ad-hoc logging via `project_audit_log.py` but it wasn't wired into every service. Here every create/update/delete/restore/transition writes an audit row.

## Tests

- `tests/integration/test_health.py` — `/health`, `/ready`, `/`.
- `tests/integration/test_rbac_gates.py` — anonymous 401, reader 403 on create, admin pass.
- `tests/unit/test_project_service_transitions.py` — admin bypass + non-admin FSM rejection + no-op self-transition.
- `tests/unit/test_dependency_cycle_guards.py` — self + transitive cycles across milestones/activities/tasks/subtasks.
- `tests/unit/test_subtask_nesting_depth.py` — Doc-24 nesting cap at boundary.
- `tests/unit/test_comment_send_event.py` — Doc-35 body-or-attachments invariant + size + extension guards.

## Follow-ups (deferred)

- Doc-44 caller-vs-target gates (vendor-vs-target comparisons in the project service layer).
- Multipart upload route for the file-server (current Comment routes accept a pre-uploaded `{url, filename, ...}` JSON envelope; the multipart->file-server hop lives in a Phase-4 follow-up).
- Real-Postgres integration tests covering the partial-unique indexes + FSM table joins.
- Dashboard / tree-view aggregation routes (left out of this port; will move to a separate read-model service).
- `project_audit_logs` GC / archival cron.
