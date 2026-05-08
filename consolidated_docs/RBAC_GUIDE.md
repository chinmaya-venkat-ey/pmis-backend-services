# RBAC Guide — pmis-user-service

**Last refresh**: 2026-05-08 (post-doc 41 deploy — scoped RBAC live).

This service is the authoritative RBAC source for PMIS. The monolith reads from the same `roles` / `permissions` / `role_permissions` / `user_roles` / `user_permissions` / `user_role_assignments` tables (shared DB) but doesn't write to RBAC — every assignment, grant, role mutation, and permission catalog edit lands here. (Monolith does mutate `user_role_assignments` on the alembic migration backfill path during deploy, but at runtime all RBAC writes flow through user-mgmt.)

This guide is a copy-with-edits of the monolith's `RBAC_GUIDE.md`, scoped to user-mgmt. The mental model + role bundles + lockout protections are identical across the two services because **they share the same `app/core/permissions.py` registry**.

---

## 1. The model (one paragraph)

A user holds a set of **string permission codes** (`projects:create`, `master_data:manage`, …). The effective set is the **union** of:
- legacy `user_roles` global grants,
- doc-41 `user_role_assignments` grants (global / org-scoped / project-scoped),
- direct grants in `user_permissions`.

Auth middleware hydrates two views per request: the flat union (`request.state.user_permissions: Set[str]`) and the per-scope view (`request.state.scoped_permissions: Dict[(scope_kind, scope_id), Set[str]]`). Routes use `require_permission(code)` for global gates, `require_project_permission(code)` / `require_org_permission(code)` for scoped gates. 401 if no token, 403 if the code is missing at the required scope.

**Six seeded roles** as of doc 43 round 4: `admin`, `super_admin`, `org_admin`, `project_admin`, `project_member`, `division_member`. Pre-doc-43-round-4 there were three more legacy roles (`member`, `viewer`, `vendor`) — those are retired and a boot-time cleanup deletes any drifted rows. `super_admin` is auto-synced to hold every registered code on every boot; `admin` is auto-synced to hold every code **except** `users:grant_superadmin` (post-doc-43 demotion). Both `admin` and `super_admin` role rows are **protected** from delete / rename / permission-set mutation through the API.

---

## 2. The six seeded roles

(Doc 43 round 4 retired `member`, `viewer`, and `vendor` — see § 6 / common errors below if you encounter a stale reference.)

| Role | Tier | What they can do | What they can't |
|------|------|-----------------|-----------------|
| `super_admin` (doc 41) | global | Everything `admin` does + `users:grant_superadmin` (the gate to grant `super_admin` itself). | Lockout-protected: last super_admin can't be revoked, deactivated, or deleted. **Post-G2/G3 (doc 43 round 2)**: a super_admin cannot change another super_admin's password or DELETE another super_admin without first revoking the target's super_admin role. |
| `admin` | global | Every code except `users:grant_superadmin`. Auto-synced. **Demoted in doc 43**: no longer the lockout-protected tier. Admin users can be freely demoted or deactivated by another user. | Cannot grant `super_admin` or `admin` (caller-vs-target). Cannot PATCH / password-change / DELETE a super_admin user (F1 hierarchy gate). Cannot self-deactivate (G1, doc 43 round 2). **Cannot change another admin's password or DELETE another admin** without first revoking the target's admin role (G4/G5, doc 43 round 3). |
| `org_admin` (doc 41) | org (vendor) | Manage user / project memberships within their owning vendor. Caller-vs-target rules limit grants to `project_admin` / `project_member` / `division_member` on projects whose owning vendor matches. | Cannot publish/close/delete projects, cannot edit project content, cannot grant `org_admin` or `super_admin`. |
| `project_admin` (doc 41) | project | Manage tasks/subtasks + project-membership on the specific project the assignment carries. Can grant `project_member` on that project only. | Cannot create projects, cannot grant `project_admin` (only `project_member`), cannot touch master data or RBAC outside their project. |
| `project_member` (doc 41) | project | Read project + M/A/T/S, contribute task/subtask updates, comment, upload/download attachments. | Cannot delete project content, cannot grant any role, cannot manage milestones/activities create/delete. |
| `division_member` (doc 41) | project | Read-only at this stage — workbox / approval workflow lands later. | Anything that mutates state. (Scoped to projects so the upcoming inbox can filter by membership.) |

Seeded permission lists live in [`app/core/permissions.py`](../app/core/permissions.py). The seed loop in `RbacRepository.sync_builtin_permissions` upserts them on every boot.

### Caller-vs-target gate (doc 41)

Lives in [`app/api/v3/role_assignments/services.py::can_caller_grant`](../app/api/v3/role_assignments/services.py).

Symmetric for grant + revoke (post-doc-43): the same matrix gates `POST` and `DELETE` on `/role-assignments`. A caller who can't grant a `(role, scope)` tuple can't revoke it either.

| Caller | Can grant / revoke |
|---|---|
| `super_admin` | any role at any scope (only role that can grant or revoke `super_admin` and `admin`) |
| `admin` | any role **except** `super_admin` and `admin` (post-doc-43 demotion — admin can no longer grant peers) |
| `org_admin` of vendor X | `project_admin` / `project_member` / `division_member` on projects in vendor X |
| `project_admin` of project P | `project_member` on P only |
| anyone else | nothing |

---

## 3. The permission catalog

Source of truth: `permissions` table in the shared DB. Codes upserted from `BUILTIN_PERMISSIONS` in `app/core/permissions.py` on every boot.

Code shape: `module:action`. Common modules: `projects`, `users`, `milestones`, `activities`, `tasks`, `subtasks`, `comments`, `attachments`, `master_data`, `roles`, `permissions`, `rbac`, `meetings`, `work_packages`.

**Built-in protection**: `is_builtin=True` rows can't be deleted via the API (422). Their `name` and `description` ARE editable so admins can rename a display label without forking source.

**The `app/core/permissions.py` file exists in BOTH this repo and the monolith** — both registries seed the shared `permissions` table on every boot (whichever service boots last wins on description fields, but they're identical). Keep the two files in lockstep when adding a new built-in permission code.

---

## 4. Endpoints

### Catalog management (`/api/v3/master/permissions/*` and `/master/roles/*`)

Both gated by `master_data:view` / `master_data:manage`.

| Endpoint | Purpose |
|---|---|
| `GET /api/v3/master/permissions` | Flat list, paginated |
| `GET /api/v3/master/permissions/by-module` | Same content grouped by module prefix; modules sorted alphabetically (doc 33 change 2) |
| `POST /api/v3/master/permissions/create` | Add a custom code (built-ins not creatable; they're owned by source) |
| `PATCH /api/v3/master/permissions/{code}` | Edit name/description (built-ins editable here) |
| `DELETE /api/v3/master/permissions/{code}` | Custom rows only |
| `GET /api/v3/master/roles[/{id}]` | List / single read |
| `POST /api/v3/master/roles/create` | Create a custom role |
| `PATCH /api/v3/master/roles/{id}` | Rename / update description; **admin role rejects (403)** |
| `DELETE /api/v3/master/roles/{id}` | Delete a custom role |
| `GET /api/v3/master/roles/{id}/permissions` | List the role's codes |
| `PUT /api/v3/master/roles/{id}/permissions` | Replace the entire permission set in one call; **admin role rejects (403)** |
| `POST /api/v3/master/roles/{id}/permissions/{code}` | Grant one code (idempotent) |
| `DELETE /api/v3/master/roles/{id}/permissions/{code}` | Revoke one code |

The legacy paths (`/api/v3/roles`, `/api/v3/permissions`) keep responding for back-compat but stamp `Deprecation: true` + `Link: <successor>; rel="successor-version"`. FE should switch to the master paths.

### User-side assignment (`/api/v3/users/*`)

Operate on a specific user, not on the catalog.

| Endpoint | Permission | Purpose |
|---|---|---|
| `GET /api/v3/users/me/permissions` | authenticated | Caller's own effective set + `isAdmin` flag |
| `GET /api/v3/users/{id}/permissions` | `permissions:read` | Effective set + direct grants for any user |
| `POST /api/v3/users/{id}/permissions/{code}` | `rbac:assign` | Direct grant (additive on top of role-derived) |
| `DELETE /api/v3/users/{id}/permissions/{code}` | `rbac:assign` | Revoke a direct grant |
| `GET /api/v3/users/{id}/roles` | `permissions:read` | List a user's roles (legacy `user_roles`) |
| `POST /api/v3/users/{id}/roles/{role_id}` | `rbac:assign` | Assign a role (legacy global `user_roles`) |
| `DELETE /api/v3/users/{id}/roles/{role_id}` | `rbac:assign` | Unassign; **last-admin lockout fires** on the seeded admin role |

### Doc 41 — scoped role assignments + project-mapping views

| Endpoint | Permission | Purpose | Proxy via :8000 |
|---|---|---|---|
| `GET /api/v3/users/{id}/role-assignments` | `users:read` (own) / `users:read_all` | List a user's scoped assignments (`user_role_assignments`) | Yes (`/users/*` prefix) |
| `POST /api/v3/users/{id}/role-assignments` | `rbac:assign` + caller-vs-target gate | Grant a scoped role | Yes |
| `DELETE /api/v3/users/{id}/role-assignments/{aid}` | `rbac:assign` + last-super_admin lockout | Revoke a scoped assignment | Yes |
| `POST /api/v3/projects/{id}/role-assignments` | `rbac:assign` | Project-side create — body must include `userId`; project comes from path | **No — :8001 only** |
| `DELETE /api/v3/projects/{id}/role-assignments/{aid}` | `rbac:assign` | Project-side revoke | **No — :8001 only** |
| `GET /api/v3/projects/{id}/role-assignments` | `project_members:read` | Per-project drill-down view, grouped by role bucket. Powers the FE Project-Mapping mock. | **No — :8001 only** |
| `GET /api/v3/vendors/{id}/projects?expand=role-assignments` | `projects:read_all` OR `org_admin` of vendor | Org-Mgmt landing — projects mapped to a vendor + optional inline role buckets | **No — :8001 only**. Monolith has its own `/vendors/{id}/projects` (different shape, no `roleAssignments`). |
| `GET /api/v3/users/{id}/projects` | `users:read` (own) / `users:read_all` | User-Mgmt landing — projects the user is assigned to + their roles on each | Yes (`/users/*` prefix) |

**Note on proxy reach**: only the user-side variants (`/users/{id}/role-assignments`, `/users/{id}/projects`) are reachable via the monolith's :8000 proxy because they match the existing `/api/v3/users/*` prefix rule. The project-side and vendor-side variants are intentionally **not** proxied — FE talks to user-mgmt :8001 directly. This keeps the new doc-41 surface decoupled from monolith and avoids dragging in monolith's `/projects/*` and `/vendors/*` namespaces.

**There is no deny semantics.** Effective set = `union(role_derived, direct_grants)`. To revoke, delete the source row.

---

## 5. Effective-permissions resolution (the per-request hot path)

`RbacRepository.effective_permissions_for_user(user_id)` returns `Set[str]`. The query is one indexed JOIN over `user_roles → role_permissions` UNION `user_permissions`. Cached only within the request (no Redis layer; profiling hasn't shown a need). The auth middleware calls it once per request and stores the result on `request.state.user_permissions`.

```
Request
  │
  ▼
AuthenticationMiddleware
  decode JWT (HS256)
  if user_id is a UUID-shape string and not in revoked_tokens:
    request.state.user_id        = claim
    request.state.user_login     = claim
    request.state.user_permissions = RbacRepository.effective_permissions_for_user(user_id)
    request.state.is_admin       = "admin" role membership
  ▼
require_permission("module:action") (FastAPI dependency)
  401 if request.state.user_id is None
  403 if "module:action" not in request.state.user_permissions
  ▼
Route handler
```

---

## 6. Lockout protections + hierarchy guards

Baked into the service layer so they fire regardless of caller. Post-doc-43 the protected tier is `super_admin`, not `admin`. Round 2 (G1/G2/G3) added the self-deactivate symmetric guard and peer-takeover blocks on destructive ops.

| Guard | Trigger | Response | Source |
|---|---|---|---|
| **Last-super_admin role-revoke** | `DELETE /users/{id}/role-assignments/{aid}` on the only global super_admin assignment | 403 | doc 43 round 1 |
| **Last-super_admin user-DELETE** | DELETE on the only live super_admin user | 422 | doc 43 round 1 |
| **Last-super_admin deactivate** | PATCH `status=inactive` on the only live super_admin (service-layer defence-in-depth — preempted at route by G1 / F1) | 422 | doc 43 round 1 |
| **F1 hierarchy gate** | admin caller PATCH / password-change / DELETE on a super_admin user | 403 | doc 43 round 1 |
| **F2 reserved permission** | grant of `users:grant_superadmin` to anyone but the super_admin role; direct user-permission grant of the same code | 403 | doc 43 round 1 |
| **L1 / L2 role-row lock** | DELETE / PATCH / permission-set mutation on the seeded `admin` or `super_admin` role row | 403 | doc 43 round 1 |
| **G1 self-deactivate** | PATCH `status=inactive` where caller == target (any tier) | 403 "Cannot deactivate your own account." | doc 43 round 2 |
| **G2 peer-SA password change** | super_admin → another super_admin via `PATCH /users/{id}/password` | 403 "Cannot perform destructive actions … Demote the target first by revoking their super_admin role assignment." | doc 43 round 2 |
| **G3 peer-SA DELETE** | super_admin → another super_admin via `DELETE /users/{id}` | 403 (same message as G2) | doc 43 round 2 |
| **G4 peer-admin password change** | admin → another admin via `PATCH /users/{id}/password` (neither holds super_admin) | 403 "Cannot perform destructive actions … on another admin. Demote the target first by revoking their admin role assignment." | doc 43 round 3 |
| **G5 peer-admin DELETE** | admin → another admin via `DELETE /users/{id}` (neither holds super_admin) | 403 (same message as G4) | doc 43 round 3 |
| **Self-delete guard** (legacy) | DELETE on caller == target | 403 | pre-doc-41 |
| **Self-demote-from-admin guard** | PATCH `admin=False` on caller's own row when they hold admin | 403 | pre-doc-41 |

Pre-doc-43 "last admin" guards have been removed. Admin is no longer protected — the only system-required identity is super_admin.

The bootstrap super_admin (`super_admin / superadmin123` by default) is created on first boot via `app/infrastructure/db/session.py`. Pre-doc-43 the system created an `admin / admin123` account on every boot — that auto-create is **gone**. A fresh deploy starts with super_admin only; the operator promotes others via `POST /users/{id}/role-assignments` once logged in. The bootstrap admin is forced `two_factor_enabled=True` on existing DBs that already had one (doc 35 monolith parity); the universal-OTP break-glass (`UNIVERSAL_OTP_ENABLED=true` + `UNIVERSAL_OTP_CODE`) provides reachability without disabling 2FA, and emits a `SECURITY: ...` `WARNING` line at startup so deploy logs flag the backdoor.

---

## 7. Legacy paths and OpenProject artifacts

Same as the monolith. This repo carries:

- **`app/api/v3/roles/`** and **`app/api/v3/permissions/`** — legacy paths, stamp `Deprecation: true`. Functional but FE should use `/master/*`.
- **`app/core/rbac.py`** — `Permission` enum kept as transitional bridge. `Role` enum / `ROLE_PERMISSIONS` dict / `has_permission` / `get_role_permissions` already deleted (doc 33 change 2 cleanup). The `Permission` enum and the string constants in `app/core/permissions.py` are interchangeable; new code should use the strings directly.
- **OpenProject reporter / member / manager / admin terminology** in old comments — not in use. Our four roles are `admin / member / viewer / vendor`.

A future doc (post-stable cutover) can delete the legacy paths and the `Permission` enum bridge.

---

## 8. JWT contents

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

- `user_id` is a UUID string (doc 26).
- `role` and `is_admin` are NOT in the JWT — resolved from the DB on every request. Demoting takes effect on the user's next request, not at the next refresh boundary.
- Pre-doc-26 integer-id tokens are rejected with 401 by the auth middleware (not 500).

---

## 9. Adding a new permission / role / grant

### Built-in permission code

1. Add a string constant + `PermissionDef(...)` entry to `BUILTIN_PERMISSIONS` in this repo's `app/core/permissions.py`.
2. **Also add it to the monolith's `app/core/permissions.py`** — both files must stay identical.
3. If it should belong to one of the seeded role bundles, add the code to `MEMBER_ROLE_PERMISSIONS` / `VIEWER_ROLE_PERMISSIONS` / `VENDOR_ROLE_PERMISSIONS` in both repos.
4. Reference the constant from a route decorator: `require_permission(MY_NEW_CODE)`.
5. Restart the service — `init_db` upserts the new code into `permissions` and (re-)syncs role grants.

### Custom permission at runtime

`POST /api/v3/master/permissions/create` with `{code, name, description}`. Immediately listable. Custom permissions can't drive route decorators (those are import-time strings) — useful for application-level features that look up permissions dynamically.

### Custom role

`POST /api/v3/master/roles/create` with `{name, description}`. Then either `PUT /master/roles/{id}/permissions` to replace its permission set in one call, or `POST /master/roles/{id}/permissions/{code}` to grant individual codes.

### Assign a role to a user

`POST /api/v3/users/{user_id}/roles/{role_id}`. Effective on the user's next request.

### Direct permission grant

`POST /api/v3/users/{user_id}/permissions/{code}`. Additive — augments role-derived perms.

---

## 10. Cross-repo permissions registry

The `app/core/permissions.py` file exists in **two places**:

- `PMIS-OpenProject/app/core/permissions.py` (monolith)
- `PMIS-user-management/app/core/permissions.py` (this repo)

They are identical and must stay so. Reasons:

- The monolith's auth middleware references the same string constants on its non-user routes (`@require_permission("projects:create")` on a project route). If the constant exists in user-mgmt's registry but not the monolith's, the seed runs from user-mgmt's side and the monolith's middleware can still use it (it's a string lookup, not a Python-level reference) — but the monolith's routes that reference the constant by Python name break at import.
- The seed loop runs on whichever service boots; if the two registries drift, the last-booted service' seed wins for the description fields.

When adding a code, edit both files in the same PR. Diffing the two before pushing is a five-second sanity check that prevents subtle production drift.

---

## 11. Common errors

| Status | Likely cause |
|---|---|
| 401 + "Authentication required" | Token missing or expired |
| 401 + "Invalid token" | Wrong signature, malformed, blacklisted (revoked), or pre-doc-26 integer-id |
| 403 + "Insufficient permissions" | Token good, route's required code missing from user's effective set. Check `GET /users/me/permissions` |
| 403 + "Built-in role '\<name\>' cannot be modified" | Trying to delete / rename / mutate the seeded `admin` or `super_admin` role |
| 403 + "Cannot perform destructive actions (DELETE / password change) on another super_admin. Demote the target first by revoking their super_admin role assignment." | G2 / G3 peer-takeover guard (doc 43 round 2). Revoke target's `super_admin` role-assignment first, then retry. |
| 403 + "Cannot perform destructive actions (DELETE / password change) on another admin. Demote the target first by revoking their admin role assignment." | G4 / G5 peer-takeover guard (doc 43 round 3). Revoke target's `admin` role first, then retry. |
| 403 + "Cannot deactivate your own account." | G1 self-deactivate guard (doc 43 round 2). Have another super_admin or admin (with appropriate hierarchy) deactivate the user instead. |
| 403 + "Cannot demote yourself from admin." | Pre-doc-41 self-demote guard. |
| 403 + "Cannot revoke last super_admin" | Last-super_admin role-assignment revoke lockout. Promote another user to super_admin first. |
| 422 + "Cannot deactivate the last active super_admin." | Last-super_admin deactivation lockout (defence-in-depth — typically preempted by F1 / G1 at route). |
| 403 + "users:grant_superadmin can only be held by the super_admin role." | F2 reserved-permission guard (doc 43 round 1). |
