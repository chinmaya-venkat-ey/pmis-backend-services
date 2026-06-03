"""Permission code constants — canonical declaration site for ALL PMIS services.

user-svc owns this file. Other services have their own subset duplicates
(e.g. masters-svc/app/core/permissions.py declares only the catalog codes
it uses for route gates). The bootstrap data-migration in this service
seeds EVERY code below into `users.permissions`.

The catalog is split into:

  - Action codes (verb-coarse) — create / read / delete / restore / publish /
    close, etc. One code per action per resource. Used as a single route gate.

  - Field-level write codes — `<resource>:update:<field>` for each writable
    field on a PATCH endpoint. The service layer's field-walker (see
    app/core/rbac.py:assert_field_writes_allowed) inspects which fields the
    request body sets and requires the caller to hold every matching code
    (scoped to the parent project for project-domain resources).

Why field-level instead of action-verb groupings (per round-7 decision):
  - Permission grain matches reality; no judgment calls about which "verb"
    a new field belongs to.
  - Fail-safe: if a new field lands without a permission code being seeded,
    the gate returns 403 with a clear "missing: [<code>]" detail — surfacing
    the gap immediately rather than letting it silently inherit a verb's
    powers.
  - Adding a field is a 3-line change (constant + aggregate tuple + data
    migration row); no architecture rethink, no rename of existing codes.

Vendor->project projection: an org_admin role bound to a user globally
projects onto every project in the user's vendor's project_vendors mapping.
That projection is performed at hydration time by RbacReadRepository, not
encoded in the catalog. See PLAN.md round-7 §B.
"""
from __future__ import annotations

from typing import Final


# =========================================================================
# USERS — identity & profile
# =========================================================================

# Create / read / delete (action codes, not field codes)
USERS_CREATE: Final[str] = "users:create"
USERS_READ: Final[str] = "users:read"
USERS_READ_ALL: Final[str] = "users:read_all"     # admin-style user directory
USERS_DELETE_ALL: Final[str] = "users:delete_all"  # admin globally
USERS_DELETE_VENDOR: Final[str] = "users:delete_vendor"  # org_admin: delete users in own vendor
USERS_GRANT_SUPERADMIN: Final[str] = "users:grant_superadmin"  # super_admin only

# Field-level writes on PATCH /user/users/{id}/update.
# Per round-7 Doc-44: nobody but self / admin / super_admin gets these.
# org_admin / project_admin manage role-assignments, not user-row fields.
USERS_UPDATE_EMAIL: Final[str] = "users:update:email"
USERS_UPDATE_FIRST_NAME: Final[str] = "users:update:first_name"
USERS_UPDATE_LAST_NAME: Final[str] = "users:update:last_name"
USERS_UPDATE_PHONE_NUMBER: Final[str] = "users:update:phone_number"
USERS_UPDATE_VENDOR_ID: Final[str] = "users:update:vendor_id"          # admin-only
USERS_UPDATE_DIVISION: Final[str] = "users:update:division"            # admin-only
USERS_UPDATE_DIVISION_OTHER: Final[str] = "users:update:division_other"
USERS_UPDATE_ORG_ROLE: Final[str] = "users:update:org_role"            # admin-only
USERS_UPDATE_TWO_FACTOR_ENABLED: Final[str] = "users:update:two_factor_enabled"
USERS_UPDATE_STATUS: Final[str] = "users:update:status"                # admin-only (deactivate)


# =========================================================================
# PERMISSIONS / ROLES — RBAC catalog (action codes only)
# =========================================================================
PERMISSIONS_READ: Final[str] = "permissions:read"
PERMISSIONS_MANAGE: Final[str] = "permissions:manage"

ROLES_READ: Final[str] = "roles:read"
ROLES_CREATE: Final[str] = "roles:create"
ROLES_UPDATE: Final[str] = "roles:update"
ROLES_DELETE: Final[str] = "roles:delete"

RBAC_ASSIGN: Final[str] = "rbac:assign"


# =========================================================================
# PROJECT MEMBERS — superseded by user_role_assignments, kept for legacy
# Note: :add and :delete codes were removed (2026-06-02 audit cleanup) —
# the actual role-assignment endpoints gate on rbac:assign instead, and
# bulk-replace gates on :update. No endpoint ever consulted :add or :delete.
# =========================================================================
PROJECT_MEMBERS_READ: Final[str] = "project_members:read"
PROJECT_MEMBERS_UPDATE: Final[str] = "project_members:update"


# =========================================================================
# PROJECTS — action codes
# =========================================================================
PROJECTS_READ: Final[str] = "projects:read"
PROJECTS_READ_ALL: Final[str] = "projects:read_all"
PROJECTS_CREATE: Final[str] = "projects:create"
PROJECTS_DELETE_ALL: Final[str] = "projects:delete_all"  # admin/super_admin only (Q6)

# FSM transition gates (the masters.project_status_transitions table now
# stores these codes instead of role names — round-7 "switch FSM to
# permission codes" decision).
# Note: PROJECTS_DRAFT removed (2026-06-02 audit cleanup) — no route
# enforced it, the stored FSM permission_code column is not read by any
# gate today, so the constant served no purpose.
PROJECTS_PUBLISH: Final[str] = "projects:publish"
PROJECTS_CLOSE: Final[str] = "projects:close"
PROJECTS_REOPEN: Final[str] = "projects:reopen"

# PROJECTS — field-level writes (PATCH /project/projects/{uuid}/update)
PROJECTS_UPDATE_NAME: Final[str] = "projects:update:name"
PROJECTS_UPDATE_DESCRIPTION: Final[str] = "projects:update:description"
PROJECTS_UPDATE_PUBLIC: Final[str] = "projects:update:public"
PROJECTS_UPDATE_STATUS_EXPLANATION: Final[str] = "projects:update:status_explanation"
PROJECTS_UPDATE_OWNER: Final[str] = "projects:update:owner"
PROJECTS_UPDATE_OWNER_OTHER: Final[str] = "projects:update:owner_other"
PROJECTS_UPDATE_START_DATE: Final[str] = "projects:update:start_date"
PROJECTS_UPDATE_END_DATE: Final[str] = "projects:update:end_date"
PROJECTS_UPDATE_ACTUAL_START_DATE: Final[str] = "projects:update:actual_start_date"
PROJECTS_UPDATE_ACTUAL_END_DATE: Final[str] = "projects:update:actual_end_date"
# Sub-resource writes (separate endpoints, not in the PATCH body)
PROJECTS_UPDATE_VENDORS: Final[str] = "projects:update:vendors"
# Doc-finance: field-level gate for the contract-finance fields
# (totalProjectValueExclTax, taxPercent, ccnCapPercent). Seeded by
# alembic r004; granted to super_admin / admin / org_admin /
# project_admin (admin tiers + the project admin).
PROJECTS_UPDATE_FINANCE: Final[str] = "projects:update:finance"
# §3.8 (2026-06-02 audit): the generic PATCH endpoint previously let
# callers write these columns without holding a code (Pydantic accepted,
# walker missed). Seeded + granted to admin/super_admin via r009.
PROJECTS_UPDATE_ACTIVE: Final[str] = "projects:update:active"
PROJECTS_UPDATE_PARENT_ID: Final[str] = "projects:update:parent_id"
PROJECTS_UPDATE_STATUS: Final[str] = "projects:update:status"


# =========================================================================
# MILESTONES
# =========================================================================
MILESTONES_READ: Final[str] = "milestones:read"
MILESTONES_CREATE: Final[str] = "milestones:create"
MILESTONES_DELETE: Final[str] = "milestones:delete"
MILESTONES_RESTORE: Final[str] = "milestones:restore"

MILESTONES_UPDATE_NAME: Final[str] = "milestones:update:name"
MILESTONES_UPDATE_DESCRIPTION: Final[str] = "milestones:update:description"
MILESTONES_UPDATE_START_DATE: Final[str] = "milestones:update:start_date"
MILESTONES_UPDATE_END_DATE: Final[str] = "milestones:update:end_date"
MILESTONES_UPDATE_ACTUAL_START_DATE: Final[str] = "milestones:update:actual_start_date"
MILESTONES_UPDATE_ACTUAL_END_DATE: Final[str] = "milestones:update:actual_end_date"
MILESTONES_UPDATE_STATUS: Final[str] = "milestones:update:status"
MILESTONES_UPDATE_PRIORITY: Final[str] = "milestones:update:priority"
MILESTONES_UPDATE_POSITION: Final[str] = "milestones:update:position"
# Sub-resource writes
MILESTONES_UPDATE_DEPENDENCIES: Final[str] = "milestones:update:dependencies"
MILESTONES_UPDATE_VENDORS: Final[str] = "milestones:update:vendors"


# =========================================================================
# ACTIVITIES
# =========================================================================
ACTIVITIES_READ: Final[str] = "activities:read"
ACTIVITIES_CREATE: Final[str] = "activities:create"
ACTIVITIES_DELETE: Final[str] = "activities:delete"
ACTIVITIES_RESTORE: Final[str] = "activities:restore"

ACTIVITIES_UPDATE_NAME: Final[str] = "activities:update:name"
ACTIVITIES_UPDATE_DESCRIPTION: Final[str] = "activities:update:description"
ACTIVITIES_UPDATE_START_DATE: Final[str] = "activities:update:start_date"
ACTIVITIES_UPDATE_END_DATE: Final[str] = "activities:update:end_date"
ACTIVITIES_UPDATE_ACTUAL_START_DATE: Final[str] = "activities:update:actual_start_date"
ACTIVITIES_UPDATE_ACTUAL_END_DATE: Final[str] = "activities:update:actual_end_date"
ACTIVITIES_UPDATE_STATUS: Final[str] = "activities:update:status"
ACTIVITIES_UPDATE_PRIORITY: Final[str] = "activities:update:priority"
ACTIVITIES_UPDATE_POSITION: Final[str] = "activities:update:position"
ACTIVITIES_UPDATE_OWNER_DIVISION: Final[str] = "activities:update:owner_division"
ACTIVITIES_UPDATE_CONCERNED_DIVISIONS: Final[str] = "activities:update:concerned_divisions"
ACTIVITIES_UPDATE_VENDOR_ID: Final[str] = "activities:update:vendor_id"
ACTIVITIES_UPDATE_ACTIVITY_STARTED: Final[str] = "activities:update:activity_started"
# §3.8 (2026-06-02 audit): activity columns accepted by the schema but
# previously ungated. Seeded + granted to admin/super_admin via r009.
ACTIVITIES_UPDATE_CATEGORY: Final[str] = "activities:update:category"
ACTIVITIES_UPDATE_CCN_VALUE: Final[str] = "activities:update:ccn_value"
ACTIVITIES_UPDATE_OWNER_DIVISION_OTHER: Final[str] = "activities:update:owner_division_other"
ACTIVITIES_UPDATE_CONCERNED_DIVISION_OTHER: Final[str] = "activities:update:concerned_division_other"
# Sidecar / sub-resource
ACTIVITIES_UPDATE_RESOURCE: Final[str] = "activities:update:resource"
ACTIVITIES_UPDATE_DEPENDENCIES: Final[str] = "activities:update:dependencies"


# =========================================================================
# TASKS
# =========================================================================
TASKS_READ: Final[str] = "tasks:read"
TASKS_CREATE: Final[str] = "tasks:create"
TASKS_DELETE: Final[str] = "tasks:delete"
TASKS_RESTORE: Final[str] = "tasks:restore"

TASKS_UPDATE_NAME: Final[str] = "tasks:update:name"
TASKS_UPDATE_DESCRIPTION: Final[str] = "tasks:update:description"
TASKS_UPDATE_START_DATE: Final[str] = "tasks:update:start_date"
TASKS_UPDATE_END_DATE: Final[str] = "tasks:update:end_date"
TASKS_UPDATE_ACTUAL_START_DATE: Final[str] = "tasks:update:actual_start_date"
TASKS_UPDATE_ACTUAL_END_DATE: Final[str] = "tasks:update:actual_end_date"
TASKS_UPDATE_STATUS: Final[str] = "tasks:update:status"
TASKS_UPDATE_PRIORITY: Final[str] = "tasks:update:priority"
TASKS_UPDATE_POSITION: Final[str] = "tasks:update:position"
TASKS_UPDATE_ASSIGNED_TO: Final[str] = "tasks:update:assigned_to"
TASKS_UPDATE_RESOURCE: Final[str] = "tasks:update:resource"
TASKS_UPDATE_DEPENDENCIES: Final[str] = "tasks:update:dependencies"


# =========================================================================
# SUBTASKS
# =========================================================================
SUBTASKS_READ: Final[str] = "subtasks:read"
SUBTASKS_CREATE: Final[str] = "subtasks:create"
SUBTASKS_DELETE: Final[str] = "subtasks:delete"
SUBTASKS_RESTORE: Final[str] = "subtasks:restore"

SUBTASKS_UPDATE_NAME: Final[str] = "subtasks:update:name"
SUBTASKS_UPDATE_DESCRIPTION: Final[str] = "subtasks:update:description"
SUBTASKS_UPDATE_START_DATE: Final[str] = "subtasks:update:start_date"
SUBTASKS_UPDATE_END_DATE: Final[str] = "subtasks:update:end_date"
SUBTASKS_UPDATE_ACTUAL_START_DATE: Final[str] = "subtasks:update:actual_start_date"
SUBTASKS_UPDATE_ACTUAL_END_DATE: Final[str] = "subtasks:update:actual_end_date"
SUBTASKS_UPDATE_STATUS: Final[str] = "subtasks:update:status"
SUBTASKS_UPDATE_PRIORITY: Final[str] = "subtasks:update:priority"
SUBTASKS_UPDATE_POSITION: Final[str] = "subtasks:update:position"
SUBTASKS_UPDATE_ASSIGNED_TO: Final[str] = "subtasks:update:assigned_to"
SUBTASKS_UPDATE_RESOURCE: Final[str] = "subtasks:update:resource"
SUBTASKS_UPDATE_DEPENDENCIES: Final[str] = "subtasks:update:dependencies"


# =========================================================================
# COMMENTS — action codes (no field-level updates; comments are immutable
# except via moderation tombstone delete)
# Note: ATTACHMENTS_DOWNLOAD + ATTACHMENTS_DELETE removed (2026-06-02
# audit cleanup) — download proxies to fileservice's files:read; delete
# is gated by an "uploader or admin" in-controller check. Neither was
# enforced.
# Note: COMMENTS_MODERATE retained pending team decision (B3 in
# permissions_decisions.md) on the comments authorization model.
# =========================================================================
COMMENTS_READ: Final[str] = "comments:read"
COMMENTS_CREATE: Final[str] = "comments:create"
COMMENTS_MODERATE: Final[str] = "comments:moderate"   # admin/super_admin only (Q8)

ATTACHMENTS_CREATE: Final[str] = "attachments:create"

# §3.1 (2026-06-02 audit) item 4: replaces the ``ctx.is_admin`` short-
# circuit in approval_inbox_service for detail, SUBMIT, and APPROVE/REJECT
# transitions. Grant to admin/super_admin via the r008 migration.
APPROVALS_MODERATE: Final[str] = "approvals:moderate"


# =========================================================================
# MASTERS (Option C — granular per-catalog)
# =========================================================================
DIVISIONS_READ: Final[str] = "divisions:read"
DIVISIONS_MANAGE: Final[str] = "divisions:manage"
VENDORS_READ: Final[str] = "vendors:read"
VENDORS_MANAGE: Final[str] = "vendors:manage"
RESOURCE_TYPES_READ: Final[str] = "resource_types:read"
RESOURCE_TYPES_MANAGE: Final[str] = "resource_types:manage"
PRIORITIES_READ: Final[str] = "priorities:read"
PRIORITIES_MANAGE: Final[str] = "priorities:manage"
PROJECT_CATEGORIES_READ: Final[str] = "project_categories:read"
PROJECT_CATEGORIES_MANAGE: Final[str] = "project_categories:manage"
ACTIVITY_TYPES_READ: Final[str] = "activity_types:read"
ACTIVITY_TYPES_MANAGE: Final[str] = "activity_types:manage"
ACTIVITY_STATUSES_READ: Final[str] = "activity_statuses:read"
ACTIVITY_STATUSES_MANAGE: Final[str] = "activity_statuses:manage"
MILESTONE_STATUSES_READ: Final[str] = "milestone_statuses:read"
MILESTONE_STATUSES_MANAGE: Final[str] = "milestone_statuses:manage"
PROJECT_STATUS_TRANSITIONS_READ: Final[str] = "project_status_transitions:read"
PROJECT_STATUS_TRANSITIONS_MANAGE: Final[str] = "project_status_transitions:manage"
NOTIFICATION_TEMPLATES_READ: Final[str] = "notification_templates:read"
NOTIFICATION_TEMPLATES_MANAGE: Final[str] = "notification_templates:manage"
COST_TYPES_READ: Final[str] = "cost_types:read"
COST_TYPES_MANAGE: Final[str] = "cost_types:manage"
FREQUENCIES_READ: Final[str] = "frequencies:read"
FREQUENCIES_MANAGE: Final[str] = "frequencies:manage"


# =========================================================================
# Field-level write code maps — used by the field-walker helper in
# core/rbac.py:assert_field_writes_allowed. The helper takes a resource
# tag + a touched-field set and emits the required code names.
#
# The dict shape is intentionally simple: {resource_tag: {field: code}}.
# New field → add one line per dict. The aggregate tuples below are
# what role-grants reference.
# =========================================================================

USER_FIELD_CODES: Final[dict[str, str]] = {
    "email": USERS_UPDATE_EMAIL,
    "first_name": USERS_UPDATE_FIRST_NAME,
    "last_name": USERS_UPDATE_LAST_NAME,
    "phone_number": USERS_UPDATE_PHONE_NUMBER,
    "vendor_id": USERS_UPDATE_VENDOR_ID,
    "division": USERS_UPDATE_DIVISION,
    "division_other": USERS_UPDATE_DIVISION_OTHER,
    "org_role": USERS_UPDATE_ORG_ROLE,
    "two_factor_enabled": USERS_UPDATE_TWO_FACTOR_ENABLED,
    "status": USERS_UPDATE_STATUS,
}

PROJECT_FIELD_CODES: Final[dict[str, str]] = {
    "name": PROJECTS_UPDATE_NAME,
    "description": PROJECTS_UPDATE_DESCRIPTION,
    "public": PROJECTS_UPDATE_PUBLIC,
    "status_explanation": PROJECTS_UPDATE_STATUS_EXPLANATION,
    "owner": PROJECTS_UPDATE_OWNER,
    "owner_other": PROJECTS_UPDATE_OWNER_OTHER,
    "start_date": PROJECTS_UPDATE_START_DATE,
    "end_date": PROJECTS_UPDATE_END_DATE,
    "actual_start_date": PROJECTS_UPDATE_ACTUAL_START_DATE,
    "actual_end_date": PROJECTS_UPDATE_ACTUAL_END_DATE,
    # Doc-finance: all three finance fields share the same gate.
    "total_project_value_excl_tax": PROJECTS_UPDATE_FINANCE,
    "tax_percent": PROJECTS_UPDATE_FINANCE,
    "ccn_cap_percent": PROJECTS_UPDATE_FINANCE,
    # Sub-resource fields handled separately in the service layer but still
    # gated via the field walker — must be present in the PATCH body's
    # touched-set computation BEFORE the service pops them.
    "vendor_ids": PROJECTS_UPDATE_VENDORS,
    # §3.8 (2026-06-02 audit): generic-PATCH gates for the lifecycle-
    # adjacent columns. ``status`` here gates raw writes — the formal
    # lifecycle transitions still go through PROJECTS_PUBLISH/CLOSE/REOPEN.
    "active": PROJECTS_UPDATE_ACTIVE,
    "parent_id": PROJECTS_UPDATE_PARENT_ID,
    "status": PROJECTS_UPDATE_STATUS,
}

MILESTONE_FIELD_CODES: Final[dict[str, str]] = {
    "name": MILESTONES_UPDATE_NAME,
    "description": MILESTONES_UPDATE_DESCRIPTION,
    "start_date": MILESTONES_UPDATE_START_DATE,
    "end_date": MILESTONES_UPDATE_END_DATE,
    "actual_start_date": MILESTONES_UPDATE_ACTUAL_START_DATE,
    "actual_end_date": MILESTONES_UPDATE_ACTUAL_END_DATE,
    "status": MILESTONES_UPDATE_STATUS,
    "priority": MILESTONES_UPDATE_PRIORITY,
    "position": MILESTONES_UPDATE_POSITION,
    "depends_on": MILESTONES_UPDATE_DEPENDENCIES,
    "vendor_ids": MILESTONES_UPDATE_VENDORS,
}

ACTIVITY_FIELD_CODES: Final[dict[str, str]] = {
    "name": ACTIVITIES_UPDATE_NAME,
    "description": ACTIVITIES_UPDATE_DESCRIPTION,
    "start_date": ACTIVITIES_UPDATE_START_DATE,
    "end_date": ACTIVITIES_UPDATE_END_DATE,
    "actual_start_date": ACTIVITIES_UPDATE_ACTUAL_START_DATE,
    "actual_end_date": ACTIVITIES_UPDATE_ACTUAL_END_DATE,
    "status": ACTIVITIES_UPDATE_STATUS,
    "priority": ACTIVITIES_UPDATE_PRIORITY,
    "position": ACTIVITIES_UPDATE_POSITION,
    "owner_division": ACTIVITIES_UPDATE_OWNER_DIVISION,
    "concerned_divisions": ACTIVITIES_UPDATE_CONCERNED_DIVISIONS,
    "vendor_id": ACTIVITIES_UPDATE_VENDOR_ID,
    "activity_started": ACTIVITIES_UPDATE_ACTIVITY_STARTED,
    # §3.8 (2026-06-02 audit): close the schema-accepted-but-ungated gap.
    "category": ACTIVITIES_UPDATE_CATEGORY,
    "ccn_value": ACTIVITIES_UPDATE_CCN_VALUE,
    "owner_division_other": ACTIVITIES_UPDATE_OWNER_DIVISION_OTHER,
    "concerned_division_other": ACTIVITIES_UPDATE_CONCERNED_DIVISION_OTHER,
    # §3.14 (2026-06-02 audit): "resource" key removed — ActivityUpdateRequest
    # rejects the field. Constant ACTIVITIES_UPDATE_RESOURCE retained but
    # inert (catalog row kept; no enforcement site).
    "depends_on": ACTIVITIES_UPDATE_DEPENDENCIES,
}

TASK_FIELD_CODES: Final[dict[str, str]] = {
    "name": TASKS_UPDATE_NAME,
    "description": TASKS_UPDATE_DESCRIPTION,
    "start_date": TASKS_UPDATE_START_DATE,
    "end_date": TASKS_UPDATE_END_DATE,
    "actual_start_date": TASKS_UPDATE_ACTUAL_START_DATE,
    "actual_end_date": TASKS_UPDATE_ACTUAL_END_DATE,
    "status": TASKS_UPDATE_STATUS,
    "priority": TASKS_UPDATE_PRIORITY,
    "position": TASKS_UPDATE_POSITION,
    "assigned_to": TASKS_UPDATE_ASSIGNED_TO,
    # §3.14 (2026-06-02 audit): "resource" key removed (TaskUpdateRequest
    # rejects the field). TASKS_UPDATE_RESOURCE constant kept but inert.
    "depends_on": TASKS_UPDATE_DEPENDENCIES,
}

SUBTASK_FIELD_CODES: Final[dict[str, str]] = {
    "name": SUBTASKS_UPDATE_NAME,
    "description": SUBTASKS_UPDATE_DESCRIPTION,
    "start_date": SUBTASKS_UPDATE_START_DATE,
    "end_date": SUBTASKS_UPDATE_END_DATE,
    "actual_start_date": SUBTASKS_UPDATE_ACTUAL_START_DATE,
    "actual_end_date": SUBTASKS_UPDATE_ACTUAL_END_DATE,
    "status": SUBTASKS_UPDATE_STATUS,
    "priority": SUBTASKS_UPDATE_PRIORITY,
    "position": SUBTASKS_UPDATE_POSITION,
    "assigned_to": SUBTASKS_UPDATE_ASSIGNED_TO,
    # §3.14 (2026-06-02 audit): "resource" key removed (SubtaskUpdateRequest
    # rejects the field). SUBTASKS_UPDATE_RESOURCE constant kept but inert.
    "depends_on": SUBTASKS_UPDATE_DEPENDENCIES,
}


# =========================================================================
# Aggregate tuples — referenced by the bootstrap data-migration when
# seeding role->permission grants. Adding a field code to one of these
# tuples + writing the seed row is the entire "extend permissions" change.
# =========================================================================

ALL_USER_FIELD_WRITES: Final[tuple[str, ...]] = tuple(USER_FIELD_CODES.values())

ALL_PROJECT_FIELD_WRITES: Final[tuple[str, ...]] = tuple(dict.fromkeys((
    *PROJECT_FIELD_CODES.values(),
    PROJECTS_UPDATE_VENDORS,
)))

ALL_MILESTONE_FIELD_WRITES: Final[tuple[str, ...]] = (
    *MILESTONE_FIELD_CODES.values(),
    MILESTONES_UPDATE_DEPENDENCIES, MILESTONES_UPDATE_VENDORS,
)

ALL_ACTIVITY_FIELD_WRITES: Final[tuple[str, ...]] = (
    *ACTIVITY_FIELD_CODES.values(),
    ACTIVITIES_UPDATE_DEPENDENCIES,
)

ALL_TASK_FIELD_WRITES: Final[tuple[str, ...]] = (
    *TASK_FIELD_CODES.values(),
    TASKS_UPDATE_DEPENDENCIES,
)

ALL_SUBTASK_FIELD_WRITES: Final[tuple[str, ...]] = (
    *SUBTASK_FIELD_CODES.values(),
    SUBTASKS_UPDATE_DEPENDENCIES,
)

# Codes that a project_member is expected to hold (self-driven work
# updates within scope). Per round-7: status/priority on tasks/subtasks
# + self-assignment.
PROJECT_MEMBER_WRITES: Final[tuple[str, ...]] = (
    ACTIVITIES_UPDATE_ACTIVITY_STARTED,
    TASKS_UPDATE_STATUS, TASKS_UPDATE_PRIORITY, TASKS_UPDATE_ASSIGNED_TO,
    SUBTASKS_UPDATE_STATUS, SUBTASKS_UPDATE_PRIORITY, SUBTASKS_UPDATE_ASSIGNED_TO,
    COMMENTS_CREATE, COMMENTS_READ,
    ATTACHMENTS_CREATE,
)

# Codes for a division_member (read-only observer tier).
DIVISION_MEMBER_WRITES: Final[tuple[str, ...]] = ()


# =========================================================================
# Domain bundles — used by the seed migration to grant per-tier.
# =========================================================================

ALL_PROJECT_ACTION_CODES: Final[tuple[str, ...]] = (
    PROJECTS_READ, PROJECTS_READ_ALL, PROJECTS_CREATE, PROJECTS_DELETE_ALL,
    PROJECTS_PUBLISH, PROJECTS_CLOSE, PROJECTS_REOPEN,
    MILESTONES_READ, MILESTONES_CREATE, MILESTONES_DELETE, MILESTONES_RESTORE,
    ACTIVITIES_READ, ACTIVITIES_CREATE, ACTIVITIES_DELETE, ACTIVITIES_RESTORE,
    TASKS_READ, TASKS_CREATE, TASKS_DELETE, TASKS_RESTORE,
    SUBTASKS_READ, SUBTASKS_CREATE, SUBTASKS_DELETE, SUBTASKS_RESTORE,
    COMMENTS_READ, COMMENTS_CREATE, COMMENTS_MODERATE,
    ATTACHMENTS_CREATE,
    APPROVALS_MODERATE,
    PROJECT_MEMBERS_READ, PROJECT_MEMBERS_UPDATE,
)

ALL_PROJECT_DOMAIN_PERMISSIONS: Final[tuple[str, ...]] = (
    *ALL_PROJECT_ACTION_CODES,
    *ALL_PROJECT_FIELD_WRITES,
    *ALL_MILESTONE_FIELD_WRITES,
    *ALL_ACTIVITY_FIELD_WRITES,
    *ALL_TASK_FIELD_WRITES,
    *ALL_SUBTASK_FIELD_WRITES,
)

ALL_USER_DOMAIN_PERMISSIONS: Final[tuple[str, ...]] = (
    USERS_CREATE, USERS_READ, USERS_READ_ALL,
    USERS_DELETE_ALL, USERS_DELETE_VENDOR, USERS_GRANT_SUPERADMIN,
    PERMISSIONS_READ, PERMISSIONS_MANAGE,
    ROLES_READ, ROLES_CREATE, ROLES_UPDATE, ROLES_DELETE,
    RBAC_ASSIGN,
    *ALL_USER_FIELD_WRITES,
)

ALL_MASTERS_READ_PERMISSIONS: Final[tuple[str, ...]] = (
    DIVISIONS_READ, VENDORS_READ, RESOURCE_TYPES_READ, PRIORITIES_READ,
    PROJECT_CATEGORIES_READ, ACTIVITY_TYPES_READ, ACTIVITY_STATUSES_READ,
    MILESTONE_STATUSES_READ, PROJECT_STATUS_TRANSITIONS_READ,
    NOTIFICATION_TEMPLATES_READ,
    COST_TYPES_READ, FREQUENCIES_READ,
)

ALL_MASTERS_MANAGE_PERMISSIONS: Final[tuple[str, ...]] = (
    DIVISIONS_MANAGE, VENDORS_MANAGE, RESOURCE_TYPES_MANAGE, PRIORITIES_MANAGE,
    PROJECT_CATEGORIES_MANAGE, ACTIVITY_TYPES_MANAGE, ACTIVITY_STATUSES_MANAGE,
    MILESTONE_STATUSES_MANAGE, PROJECT_STATUS_TRANSITIONS_MANAGE,
    NOTIFICATION_TEMPLATES_MANAGE,
    COST_TYPES_MANAGE, FREQUENCIES_MANAGE,
)


ALL_PERMISSIONS: Final[tuple[str, ...]] = (
    *ALL_USER_DOMAIN_PERMISSIONS,
    *ALL_PROJECT_DOMAIN_PERMISSIONS,
    *ALL_MASTERS_READ_PERMISSIONS,
    *ALL_MASTERS_MANAGE_PERMISSIONS,
)


# =========================================================================
# Role-tier names (seeded by bootstrap data-migration)
# =========================================================================
SUPER_ADMIN_ROLE: Final[str] = "super_admin"
ADMIN_ROLE: Final[str] = "admin"
ORG_ADMIN_ROLE: Final[str] = "org_admin"
PROJECT_ADMIN_ROLE: Final[str] = "project_admin"
PROJECT_MEMBER_ROLE: Final[str] = "project_member"
DIVISION_MEMBER_ROLE: Final[str] = "division_member"
# Master_Data.xlsx (2026-06-02): three UIDAI-tier roles added via r010.
# Naming normalized to full words per team decision.
DIRECTOR_ADMIN_ROLE: Final[str] = "director_admin"
DIVISION_OWNER_ROLE: Final[str] = "division_owner"
DIVISION_APPROVER_ROLE: Final[str] = "division_approver"


# =========================================================================
# Round-8 hardening: reserved codes that may NEVER be granted via the
# permission-grant API (direct user grant or role-permission grant on any
# non-super_admin role). These are seeded only by the bootstrap migration
# onto the `super_admin` role row; the runtime API must refuse to move them
# anywhere else.
#
# Monolith parity: F2 reserved-permission guard documented in
# C:\Programming\PMIS\PMIS-OpenProject\consolidated_docs\RBAC_GUIDE.md:150,319.
# =========================================================================
RESERVED_DIRECT_GRANT_CODES: Final[frozenset[str]] = frozenset({
    USERS_GRANT_SUPERADMIN,
})


# Built-in role rows whose `name` / permission-set are immutable at runtime.
# Monolith parity: L1/L2 role-row lock from RBAC_GUIDE.md:151. Editable only
# via a fresh bootstrap migration; the runtime API must reject mutations.
LOCKED_ROLE_NAMES: Final[frozenset[str]] = frozenset({
    SUPER_ADMIN_ROLE,
    ADMIN_ROLE,
})


# 2026-06-02: ORG_TIER_ROLES tuple removed. Validation of valid org_role
# names is now DB-driven: `_sync_org_role_assignment` checks the target
# value against `SELECT name FROM users.roles WHERE builtin = TRUE` so
# new builtin roles added via migration are auto-recognized — no Python
# edit needed. `_derive_org_roles` returns the full list of builtin role
# names the user holds (alphabetically sorted, no priority bias).
