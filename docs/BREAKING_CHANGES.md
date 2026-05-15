# Breaking Changes (cumulative)

Mirrors PLAN.md §9. Updated as each service is ported in Phase 3. Each item below requires either FE coordination or operator awareness.

---

## 1. Path scheme changes (FE-affecting)

All FE-called endpoints change prefix from `/api/v3/*` to `/<service>/*` AND get verb suffixes per PLAN.md §2.4.

| Old prefix | New prefix | Service |
|---|---|---|
| `/api/v3/users/*` | `/user/users/*` (with verb suffixes) | pmis-user-management |
| `/api/v3/master/roles/*`, `/api/v3/master/permissions/*` | `/user/roles/*`, `/user/permissions/*` | pmis-user-management |
| `/api/v3/role-grants/*` | `/user/role-grants/*` | pmis-user-management |
| `/api/v3/projects/*`, `/api/v3/milestones/*`, `/api/v3/activities/*`, `/api/v3/tasks/*`, `/api/v3/subtasks/*`, `/api/v3/comments/*`, `/api/v3/attachments/*` | `/project/<resource>/*` with verb suffixes | pmis-project-management |
| `/api/v3/dashboard/*` | `/project/dashboard/*` | pmis-project-management |
| `/api/v3/master/*` (catalogs) | `/masters/*` with verb suffixes | pmis-masters-management |
| `/api/v3/divisions`, `/api/v3/resource_types`, `/api/v3/project_status_transitions`, `/api/v3/vendors/*` (legacy) | `/masters/<resource>/*` (unified) | pmis-masters-management |
| `/api/v3/master/notification_templates/*` | `/masters/notification-templates/*` (per Q3) | pmis-masters-management |
| `/api/v3/priorities` | `/masters/priorities/picker` (auth-only) + `/masters/priorities/list` (MASTER_DATA_VIEW) | pmis-masters-management |
| `/api/v1/notifications/*` | `/notification/*` | pmis-notification-management (server-to-server only; not FE) |

FE update: one file (`src/api/endpoint.js`), ~64 entries.

---

## 2. Deleted endpoints

- `/api/v3/users/{id}/roles/{role_id}` (legacy assign-role) → use `/user/users/{id}/role-assignments/create`
- `/api/v3/users/{id}/roles` (legacy role list) → use `/user/users/{id}/role-assignments/list`
- `/api/v3/roles/*` (legacy roles router, 9 routes) → use `/user/roles/*` with verb suffixes
- `/api/v3/permissions/*` (legacy permissions router, 5 routes) → use `/user/permissions/*`
- `/api/v3/projects/{uuid}/memberships/*` (legacy memberships, 4 routes; table already migrated)

---

## 3. Removed features (entire functionality goes away)

- **Work packages** (6 routes + 2 tables): user-flagged legacy
- **Work package types** (5 routes + 1 table): user-flagged legacy
- **Meetings** (13 routes + 3 tables: meetings, meeting_agenda_items, meeting_participants): user-flagged legacy
- `MEETINGS_*`, `WORK_PACKAGES_*`, `WORK_PACKAGE_TYPES_*` permission codes dropped from `users.permissions`

---

## 4. Auth-behavior changes

- **Pre-Doc-26 int-id JWT guard dropped** (Q17). All sessions older than refresh-expire (7 days) are already invalid; no real protection lost.
- **`UNIVERSAL_OTP_ENABLED=True` in `ENV=production` raises startup error** (Q14).

---

## 5. OTP flow changes

- OTP storage moves from notification-svc's in-process dict to `users.otp_codes` (Q13).
- `/notification/otp/send` and `/notification/otp/verify` retained for one release cycle as deprecated aliases; the canonical paths are `/user/users/login/send-otp` and `/user/users/login/verify-otp`.

---

## 6. Masters RBAC (Option C — granular per-catalog permissions)

Each catalog gets its own `<catalog>:read` and `<catalog>:manage` permission code. No `/picker` variants — a single endpoint per CRUD verb.

- `GET /masters/<resource>/list` / `/details` — `<catalog>:read`
- `POST/PATCH/DELETE /masters/<resource>/…` — `<catalog>:manage`

New permission codes (seeded by user-svc bootstrap migration):
- divisions, vendors, resource_types, priorities, project_categories, activity_types, activity_statuses, milestone_statuses, project_status_transitions, notification_templates × {`:read`, `:manage`} = **20 new codes**

**Default grants** (first pass; refined during user-svc port):
- `<catalog>:read` → every standard role (`super_admin`, `admin`, `org_admin`, `project_admin`, `project_member`, `division_member`)
- `<catalog>:manage` → `super_admin` + `admin` only

**Scoping beyond auth gates:** row-level filtering (e.g. "user sees vendors in their org only") is implemented as **service-layer filters** in `masters-svc/app/services/<catalog>_service.py`, NOT as additional permission codes. The exact rules are deferred to the user-svc port (per user's note: "RBAC will be built to handle the scoping via other constraints on the read").

**Legacy `MASTER_DATA_VIEW` and `MASTER_DATA_MANAGE`** are no longer required by any new endpoint. Left in `users.permissions` for back-compat during cutover; orphaned post burn-in.

---

## 7. Response shapes

- **No field renames** (per Q1 clarification). `vendor_id`, `vendor_code`, etc. stay on the wire. FE labels them "Organization".
- Per-service response-envelope normalization may produce small differences (consistent `code`+`message`+`details` in error responses; consistent HAL Collection shape). Parity tests catch unexpected changes.

---

## 8. Operational changes

- Boot-time DDL removed (Q16). Devops runs `alembic upgrade head` per service explicitly during deploys.
- Bootstrap data is a separate alembic data-migration (Q21). New environments need an explicit `alembic upgrade <bootstrap_rev>` to seed admin + master catalogs.
- Per-service alembic version tables: `alembic_version_users`, `alembic_version_project`, `alembic_version_notification`, `alembic_version_masters`.
