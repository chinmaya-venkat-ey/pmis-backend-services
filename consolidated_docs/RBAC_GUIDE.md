# RBAC Guide — pmis-user-service

This service is the authoritative RBAC source for PMIS. The monolith reads from the same `roles` / `permissions` / `role_permissions` / `user_roles` / `user_permissions` tables (shared DB) but doesn't write — every assignment, grant, role mutation, and permission catalog edit lands here.

This guide is a copy-with-edits of the monolith's `RBAC_GUIDE.md`, scoped to user-mgmt. The mental model + 4-role bundles + lockout protections are identical across the two services because **they share the same `app/core/permissions.py` registry**.

---

## 1. The model (one paragraph)

A user holds a set of **string permission codes** (`projects:create`, `master_data:manage`, …). The set is the **union** of permissions from every role they're assigned PLUS direct grants from `user_permissions`. The auth middleware loads the set into `request.state.user_permissions` per request via `RbacRepository.effective_permissions_for_user(user_id)`. Each route declares the code it needs via `require_permission("module:action")` — 401 if no token, 403 if the code is missing.

Four seeded roles: `admin`, `member`, `viewer`, `vendor`. The `admin` role is auto-synced to hold every registered code on every boot, and is **protected** from delete / rename / permission-set mutation through the API.

---

## 2. The four seeded roles

| Role | What they can do | What they can't |
|------|-----------------|-----------------|
| `admin` | Everything. Auto-synced to every registered permission. | Lockout protections still bite (last-admin lockout, admin-role mutation). |
| `member` | Default contributor: read/update self, full CRUD on M/A/T/S, read on master data + vendor catalog. | Cannot publish/close/delete projects, no RBAC management, no master_data writes, no `*_all` (admin-tier) flavors. |
| `viewer` | Read-only across projects + master data. Can download attachments. | No mutations. |
| `vendor` | External collaborator: full CRUD on M/A/T/S + comments + attachments + own-user update. | Cannot create/publish/close/delete projects, no RBAC management, no master_data writes, no meeting writes, no work_packages access. |

Seeded permission lists live in [`app/core/permissions.py`](../app/core/permissions.py): `MEMBER_ROLE_PERMISSIONS`, `VIEWER_ROLE_PERMISSIONS`, `VENDOR_ROLE_PERMISSIONS`, `ADMIN_ROLE_PERMISSIONS`. The seed loop in `RbacRepository.sync_builtin_permissions` upserts them on every boot.

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
| `GET /api/v3/users/{id}/roles` | `permissions:read` | List a user's roles |
| `POST /api/v3/users/{id}/roles/{role_id}` | `rbac:assign` | Assign a role |
| `DELETE /api/v3/users/{id}/roles/{role_id}` | `rbac:assign` | Unassign; **last-admin lockout fires** on the seeded admin role |

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

## 6. Lockout protections

Baked into the service layer (not into route decorators) so they fire regardless of who triggers them — including admins:

| Guard | Trigger | Response |
|---|---|---|
| Last-admin removal | `DELETE /users/{id}/roles/{admin_role_id}` on the only admin holder; soft-delete that user; status flip to inactive | 403 / 422 |
| Admin role mutation | DELETE / rename / change description / replace permissions / grant or revoke a code on the seeded `admin` role | 403 |
| Self-demote on sole admin | Sole admin demoting themselves | 422 |

Goal: `admin` is always reachable. Even an admin with `rbac:assign` can't paint themselves into a corner.

The bootstrap admin is also forced `two_factor_enabled=False` on every boot — break-glass guarantee — so a misconfigured notification channel can never lock it out.

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
| 403 + "Built-in role 'admin' cannot be modified" | Trying to delete / rename / mutate the seeded admin role |
| 403 + "Cannot remove last admin" | Last-admin lockout. Add another admin first |
| 422 + "Sole admin cannot be deactivated" | Same as above on user soft-delete / status flip |
