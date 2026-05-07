# Doc 41 — flows summary

**Refresh date**: 2026-05-08
**Scope**: the new flows, surfaces, and state transitions introduced
by doc 41 (scoped RBAC). Use this as a high-altitude map; deeper
detail is in [`RBAC_GUIDE.md`](./RBAC_GUIDE.md) and the original
plan in [`planned_changes/41`](../planned_changes/).

---

## What doc 41 added — at a glance

| Area | Before | After |
|---|---|---|
| Role-assignment scope | Global only (`user_roles`: every grant applied to the whole product). | Three scopes via `user_role_assignments` — `global`, `org` (= vendor), `project`. The legacy `user_roles` table stays as a back-compat shim during a migration window. |
| Seeded roles | 4 — `admin`, `member`, `viewer`, `vendor`. | 9 — adds `super_admin`, `org_admin`, `project_admin`, `project_member`, `division_member`. |
| Permission gates | `require_permission(code)` only — checks the user's flat union. | Same `require_permission(code)` for global gates, plus new `require_project_permission(code)` and `require_org_permission(code)` that resolve the scope from the URL path. |
| Granting authority | Only `rbac:assign` matters; anyone with that code can grant any role. | Caller-vs-target gate (see §3): each role has a bounded set of roles it can grant + bounded scopes. New `users:grant_superadmin` permission gates the super-admin promotion path. |
| FE views | None for "who has what role on what project". | `GET /api/v3/projects/{id}/role-assignments` (per-project drill-down), `GET /api/v3/vendors/{id}/projects?expand=role-assignments` (Org-Mgmt landing), `GET /api/v3/users/{id}/projects` (User-Mgmt landing). |
| Comments / attachments | Gated on the union (single `require_permission` check). | **Unchanged** — comments + attachments left on the union path; the per-target-kind nature of those URLs makes scope-resolution awkward. Documented as a known follow-up. |

---

## 1. The five new roles + their seeded permission sets

| Role | Tier | Seeded permissions (what they grant) | Notes |
|---|---|---|---|
| `super_admin` | global | every code in `BUILTIN_PERMISSIONS` (~70) **including** `users:grant_superadmin`. | Top-tier. Only role that can promote others to `super_admin`. Lockout-protected. |
| `org_admin` | org (vendor) | `users:read`, `users:read_all`, `users:update_all`, `projects:read`, `projects:read_all`, `project_members:read/add/update/delete`, `vendors:read`, `master_data:view`, `rbac:assign`. | Manages users + projects within the bound vendor. Cannot edit project content or grant `org_admin`. |
| `project_admin` | project | `users:read`, `projects:read`, `project_members:read/add/update/delete`, `milestones:read`, `activities:read`, `tasks:create/read/update/delete`, `subtasks:create/read/update/delete`, `comments:create/read/delete`, `attachments:create/download/delete`, `rbac:assign`. | Manages tasks/subtasks + project memberships on a single project. Read-only on milestones/activities (per spec — "manage task and sub-task"). Cannot publish/close/delete the project. Can grant `project_member` only (not `project_admin` peers). |
| `project_member` | project | `users:read`, `projects:read`, `project_members:read`, `milestones:read`, `activities:read`, `tasks:read/update`, `subtasks:read/update`, `comments:create/read`, `attachments:create/download`. | Reads + contributes task/subtask updates. Cannot create or delete tasks/subtasks. No grant authority. |
| `division_member` | project | `users:read`, `projects:read`, `project_members:read`, `milestones:read`, `activities:read`, `tasks:read`, `subtasks:read`, `comments:read`, `attachments:download`. | Read-only at this stage. The workbox / approval workflow this role will eventually drive isn't built yet — the role is seeded read-only so it can be assigned now without granting writes. |

The legacy `admin`, `member`, `viewer`, `vendor` roles are kept as-is.
`admin` retains its full permission set (everything except
`users:grant_superadmin`).

---

## 2. Scope and the assignment table

A row in `user_role_assignments` carries `(user_id, role_id,
organization_id?, project_id?)`. **Exactly one** of the scope columns
may be set:

```
scope = global  ⇔  organization_id IS NULL AND project_id IS NULL
scope = org     ⇔  organization_id IS NOT NULL AND project_id IS NULL
scope = project ⇔  organization_id IS NULL  AND project_id IS NOT NULL
```

Enforced by `CHECK (organization_id IS NULL OR project_id IS NULL)`
plus a `UNIQUE (user_id, role_id, organization_id, project_id)` so
the same `(user, role, scope)` tuple cannot exist twice.

**Per-request hydration** (auth middleware, on every authenticated
call):

```
request.state.user_permissions  : Set[str]                         # flat union (back-compat)
request.state.scoped_permissions: Dict[(scope_kind, scope_id), Set[str]]  # doc 41
```

The flat union is the union of every code the user holds at any
scope plus legacy `user_permissions` direct grants. Existing
`require_permission(code)` callers keep working unchanged because
the union still contains everything.

---

## 3. Caller-vs-target authority (the grant matrix)

Lives in
[`app/api/v3/role_assignments/services.py::can_caller_grant`](../app/api/v3/role_assignments/services.py).
This is enforced AFTER the `require_permission(RBAC_ASSIGN)`
gate — the gate decides whether the caller can use the assignment
endpoints at all; this matrix decides what they're allowed to do
once they're past it.

| Caller's role | Can grant | Scope of the grant |
|---|---|---|
| `super_admin` | any role | any scope (only role that can grant `super_admin`) |
| `admin` (legacy) | any role except `super_admin` | any scope |
| `org_admin` of vendor X | `project_admin` / `project_member` / `division_member` | only on projects whose owning vendor is X |
| `project_admin` of project P | `project_member` only | only on P |
| anyone else | nothing | n/a |

Plus lockout protection: the **last global `super_admin`** cannot
be revoked. The legacy last-admin guard still applies for `admin`.

---

## 4. Routes — which to use for what

### 4.1 Catalog management (define what roles + permissions exist)

| Use this | Don't use |
|---|---|
| `GET /api/v3/master/roles` and `/api/v3/master/roles/{id}` | `GET /api/v3/roles[/{id}]` *(deprecated, stamps `Deprecation: true` + `Link: rel="successor-version"`)* |
| `POST /api/v3/master/roles/create` | `POST /api/v3/roles/create` *(deprecated)* |
| `PATCH /api/v3/master/roles/{id}` | `PATCH /api/v3/roles/{id}` *(deprecated)* |
| `DELETE /api/v3/master/roles/{id}` | `DELETE /api/v3/roles/{id}` *(deprecated)* |
| `GET /api/v3/master/roles/{id}/permissions` | `GET /api/v3/roles/{id}/permissions` *(deprecated)* |
| `PUT /api/v3/master/roles/{id}/permissions` | `PUT /api/v3/roles/{id}/permissions` *(deprecated)* |
| `POST /api/v3/master/roles/{id}/permissions/{code}` | `POST /api/v3/roles/{id}/permissions/{code}` *(deprecated)* |
| `DELETE /api/v3/master/roles/{id}/permissions/{code}` | `DELETE /api/v3/roles/{id}/permissions/{code}` *(deprecated)* |
| `GET /api/v3/master/permissions` | `GET /api/v3/permissions` *(deprecated)* |
| `GET /api/v3/master/permissions/by-module` (doc 33) | — (no legacy; this is master-only) |
| `GET /api/v3/master/permissions/{code}` | `GET /api/v3/permissions/{code}` *(deprecated)* |
| `POST /api/v3/master/permissions/create` | `POST /api/v3/permissions/create` *(deprecated)* |
| `PATCH /api/v3/master/permissions/{code}` | `PATCH /api/v3/permissions/{code}` *(deprecated)* |
| `DELETE /api/v3/master/permissions/{code}` | `DELETE /api/v3/permissions/{code}` *(deprecated)* |

The master-router endpoints **delegate** to the same handlers as the
deprecated ones — they're the same code, just a different URL prefix
without the `Deprecation` headers stamped.

### 4.2 User-side assignment (grant a role / direct permission to a specific user)

| Endpoint | Status | Purpose |
|---|---|---|
| `GET /api/v3/users/me/permissions` | active | Caller's own effective permission set + `isAdmin` |
| `GET /api/v3/users/{id}/permissions` | active | Effective permissions + direct grants for any user |
| `POST /api/v3/users/{id}/permissions/{code}` | active | Grant a direct permission (additive on top of role-derived) |
| `DELETE /api/v3/users/{id}/permissions/{code}` | active | Revoke a direct permission |
| **`GET /api/v3/users/{id}/role-assignments`** *(doc 41)* | active, **canonical** | Returns global + org + project-scoped grants in one list |
| **`POST /api/v3/users/{id}/role-assignments`** *(doc 41)* | active, **canonical** | Body: `{roleId, organizationId?, projectId?}`. Both scope fields omitted ⇒ global. Caller-vs-target enforced. |
| **`DELETE /api/v3/users/{id}/role-assignments/{aid}`** *(doc 41)* | active, **canonical** | Revoke a scoped assignment. Last super_admin lockout protected. |
| `GET /api/v3/users/{id}/roles` | **DEPRECATED** | Pre-doc-41; returns only legacy `user_roles` rows. |
| `POST /api/v3/users/{id}/roles/{role_id}` | **DEPRECATED** | Pre-doc-41; writes only to `user_roles` (global scope). |
| `DELETE /api/v3/users/{id}/roles/{role_id}` | **DEPRECATED** | Pre-doc-41; revokes only from `user_roles`. |

The deprecated user-side endpoints stamp `Deprecation: true` +
`Link: </api/v3/users/{id}/role-assignments>; rel="successor-version"`
on the response — DevTools / API client libraries will surface the
deprecation visibly during the FE migration window.

### 4.3 Project / vendor-side views (doc 41 — new)

| Endpoint | Use case |
|---|---|
| `GET /api/v3/projects/{id}/role-assignments` | Per-project drill-down: groups all assignments on the project by role bucket. Powers the FE Project-Mapping mock. |
| `POST /api/v3/projects/{id}/role-assignments` | Project-side create — body `{ userId, roleId }`; project_id comes from path. Same caller-vs-target gate. |
| `DELETE /api/v3/projects/{id}/role-assignments/{aid}` | Project-side revoke. |
| `GET /api/v3/vendors/{id}/projects?expand=role-assignments` | Org-Mgmt landing: every project owned by the vendor with optional inlined per-role assignment buckets. |
| `GET /api/v3/users/{id}/projects` | User-Mgmt landing: every project a user is assigned to + their roles on each. |

---

## 5. Common flows

### 5.1 FE — "Who has what role on this project?" (project-mapping screenshot)

```
GET /api/v3/projects/{project_id}/role-assignments
→ { projectId, projectName, roles: [
      { roleId, roleName: "project_admin", users: [...] },
      { roleId, roleName: "project_member", users: [...] }
  ]}
```

Powers the table in the FE mock (Project | Roles | Users | Action).

### 5.2 FE — "Show all projects under this vendor with their members"

```
GET /api/v3/vendors/{vendor_id}/projects?expand=role-assignments
→ { vendorId, vendorName, projects: [
      { projectId, projectName, projectStatus, roleAssignments: [...] }
  ]}
```

The Org Management menu landing page.

### 5.3 FE — "Show all projects this user is on, with their role per project"

```
GET /api/v3/users/{user_id}/projects
→ { userId, userLogin, projects: [
      { projectId, projectName, roles: ["project_admin"] }
  ]}
```

The User Management menu landing page.

### 5.4 Granting a role — happy path

```
POST /api/v3/projects/{project_id}/role-assignments
Authorization: Bearer <caller token>
{ "userId": "<target user>", "roleId": <role id> }

→ require_permission(RBAC_ASSIGN)        # caller has it?
→ load target user, ensure not soft-deleted
→ load role, ensure exists
→ can_caller_grant(caller, role, scope)  # caller-vs-target rule
   if super_admin             → allow
   if granting super_admin    → reject (only super_admin can)
   if admin                   → allow
   if org_admin of vendor X   → allow iff project's vendor == X and role in
                                {project_admin, project_member, division_member}
   if project_admin of P      → allow iff project == P and role == project_member
   else                        → reject
→ insert user_role_assignments row (idempotent on (user, role, scope))
→ commit, return 201 with serialized assignment
```

### 5.5 Permission lookup — what a user can do at a given scope

When a request comes in with a project_uuid in the path, the
scope-aware gate runs:

```
require_project_permission(code)
  ↓
resolve project_id from path
  • direct param: project_uuid / project_id / projectId
  • ancestor lookup: milestone_id / activity_id / task_id / subtask_id /
    parent_subtask_id / membership_id / comment_id / attachment_id
       ↓ DB query → owning project_id
  ↓
check user holds <code> at scope ("project", project_id) OR globally
  • request.state.scoped_permissions[("global", None)]    has <code>?  → allow
  • request.state.scoped_permissions[("project", id)]     has <code>?  → allow
  • request.state.user_permissions (legacy union)          has <code>?  → allow (back-compat)
  • else                                                                → 403
```

Global beats scoped: a global super_admin / admin pass every scoped
check without needing a per-project assignment.

### 5.6 Bootstrap — first super_admin on a fresh deploy

There's no API path for an empty-state DB to acquire its first
super_admin (the gate on `POST /role-assignments` requires existing
super_admin). Bootstrap is handled at startup by
`RbacRepository.sync_builtin_permissions`, which seeds the
`super_admin` role + its full permission set. The actual *user*
who holds it on day one is whoever the deploy operator promotes
manually — typically the bootstrap admin (`admin` user) gets the
super_admin role added via direct DB write or alembic data
migration. Doc 41 deliberately does NOT auto-promote — every doc-41
deploy may not want the same user as super_admin.

---

## 6. Migration window — what's still legacy and not yet retired

Doc 41 introduces the new tables and surface but does NOT delete
the legacy ones. The following are still live and read by the
permission resolution code:

- `user_roles` — legacy global role grants. Backfilled into
  `user_role_assignments` as global rows by alembic
  `d0c41a55145d`. New writes via the deprecated `POST /api/v3/users/
  {id}/roles/{role_id}` still land here.
- `project_members.roles[]` — legacy project-scoped roles JSON
  array. Backfilled into `user_role_assignments` as project-scoped
  rows by the same migration.
- `user_permissions` — direct user-level grants. Untouched by
  doc 41 — they remain the way to give a single user a code outside
  the role system.

A follow-up doc will retire the first two once the FE reads
exclusively from `user_role_assignments`.

---

## 7. Known follow-ups

- **Comments + attachments still gate on the union**, not the scoped
  helper. Their URLs use a generic `target_id` path param with the
  target-kind implicit in the URL segment — scoping cleanly needs
  either a target-kind-aware decorator factory or URL-string parsing.
  Punted to a future doc.
- **`division_member` workbox / approval workflow**: the role is
  seeded read-only today. The activity-status-change request +
  approval permissions land alongside the workflow itself (not in
  doc 41).
- **Retire `user_roles` + `project_members.roles[]`**: both stay
  during the FE migration window. Drop happens in a follow-up doc.
- **Notification-service URL fix** (surfaced during doc 41 testing,
  applied 2026-05-08): `pmis-usermanagement/.env` was pointing
  `NOTIFICATION_SERVICE_URL` at `127.0.0.1:8002`, which is the
  container's own loopback. Changed to `host.docker.internal:8002`.
  Real OTP emails now deliver. Worth a parallel CI lint that
  asserts the URL form for any `*_SERVICE_URL` env var inside
  containers without `network_mode: host`.

---

## 8. Cross-references

- Implementation plan + outcome: [`planned_changes/41`](../planned_changes/).
- Permission catalog + role bundles: [`RBAC_GUIDE.md`](./RBAC_GUIDE.md).
- Schema for `user_role_assignments`: [`DATABASE_SCHEMA.md` § `user_role_assignments`](./DATABASE_SCHEMA.md).
- Deploy log + rollback recipe: [`DEPLOYMENT_AND_INTEGRATION.md`](./DEPLOYMENT_AND_INTEGRATION.md).
