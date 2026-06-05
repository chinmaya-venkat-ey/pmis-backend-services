"""Permission code constants used by pmis-project-management.

Subset of the canonical declaration in:
  services/pmis-user-management/app/core/permissions.py

This file holds ONLY the codes referenced by this service's route gates
and field-level enforcement. The canonical list is what gets seeded into
`users.permissions` by user-svc's bootstrap data-migration.

WARNING: keep these string literals byte-identical with the canonical file.
"""
from __future__ import annotations

from typing import Final


# =========================================================================
# Project-domain action codes
# =========================================================================
PROJECTS_READ: Final[str] = "projects:read"
PROJECTS_READ_ALL: Final[str] = "projects:read_all"
PROJECTS_CREATE: Final[str] = "projects:create"
PROJECTS_DELETE_ALL: Final[str] = "projects:delete_all"

# Project lifecycle transitions — explicit codes, one per verb.
PROJECTS_PUBLISH: Final[str] = "projects:publish"
PROJECTS_CLOSE: Final[str] = "projects:close"
PROJECTS_REOPEN: Final[str] = "projects:reopen"

# Platform-admin override capability — replaces the old `is_admin` flag at
# the genuine "only a platform admin may do this" sites (edit finance after
# the publish-lock; see new/draft projects). Held by admin / super_admin only
# (seeded by user-svc migration r016); NOT in any project bundle, so
# project_admin does not get it. get_caller_is_admin() checks it against the
# caller's GLOBAL flat permission set.
PROJECTS_ADMIN_OVERRIDE: Final[str] = "projects:admin_override"

MILESTONES_READ: Final[str] = "milestones:read"
MILESTONES_CREATE: Final[str] = "milestones:create"
MILESTONES_DELETE: Final[str] = "milestones:delete"
MILESTONES_RESTORE: Final[str] = "milestones:restore"

ACTIVITIES_READ: Final[str] = "activities:read"
ACTIVITIES_CREATE: Final[str] = "activities:create"
ACTIVITIES_DELETE: Final[str] = "activities:delete"
ACTIVITIES_RESTORE: Final[str] = "activities:restore"

TASKS_READ: Final[str] = "tasks:read"
TASKS_CREATE: Final[str] = "tasks:create"
TASKS_DELETE: Final[str] = "tasks:delete"
TASKS_RESTORE: Final[str] = "tasks:restore"

SUBTASKS_READ: Final[str] = "subtasks:read"
SUBTASKS_CREATE: Final[str] = "subtasks:create"
SUBTASKS_DELETE: Final[str] = "subtasks:delete"
SUBTASKS_RESTORE: Final[str] = "subtasks:restore"

COMMENTS_READ: Final[str] = "comments:read"
COMMENTS_CREATE: Final[str] = "comments:create"
# §3.1 (2026-06-02 audit) item 3 + B3: DELETE /comments/{id} is gated on
# author-or-COMMENTS_MODERATE. Admins/super_admin hold this via r005.
COMMENTS_MODERATE: Final[str] = "comments:moderate"
# §3.1 (2026-06-02 audit) item 4: approval inbox detail/SUBMIT/transition
# routes consult this code in lieu of the removed caller_is_admin bypass.
APPROVALS_MODERATE: Final[str] = "approvals:moderate"

ATTACHMENTS_CREATE: Final[str] = "attachments:create"

PROJECT_MEMBERS_READ: Final[str] = "project_members:read"
PROJECT_MEMBERS_UPDATE: Final[str] = "project_members:update"


# =========================================================================
# Field-level write codes (project domain only — user-domain codes live in
# user-svc and aren't referenced here)
# =========================================================================

# --- projects ---
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
PROJECTS_UPDATE_VENDORS: Final[str] = "projects:update:vendors"
# Doc-finance: field-level gate for the contract-finance fields
# (totalProjectValueExclTax, taxPercent, ccnCapPercent). Applies on the
# dedicated PATCH /projects/{uuid}/finance route and to any finance-field
# updates that arrive via the generic PATCH /projects/{uuid}/update path.
PROJECTS_UPDATE_FINANCE: Final[str] = "projects:update:finance"
# §3.8 (2026-06-02 audit): generic-PATCH gates for previously ungated
# columns. Mirror of canonical; seeded + granted via r009.
PROJECTS_UPDATE_ACTIVE: Final[str] = "projects:update:active"
PROJECTS_UPDATE_PARENT_ID: Final[str] = "projects:update:parent_id"
PROJECTS_UPDATE_STATUS: Final[str] = "projects:update:status"

# --- milestones ---
MILESTONES_UPDATE_NAME: Final[str] = "milestones:update:name"
MILESTONES_UPDATE_DESCRIPTION: Final[str] = "milestones:update:description"
MILESTONES_UPDATE_START_DATE: Final[str] = "milestones:update:start_date"
MILESTONES_UPDATE_END_DATE: Final[str] = "milestones:update:end_date"
MILESTONES_UPDATE_ACTUAL_START_DATE: Final[str] = "milestones:update:actual_start_date"
MILESTONES_UPDATE_ACTUAL_END_DATE: Final[str] = "milestones:update:actual_end_date"
MILESTONES_UPDATE_STATUS: Final[str] = "milestones:update:status"
MILESTONES_UPDATE_PRIORITY: Final[str] = "milestones:update:priority"
MILESTONES_UPDATE_POSITION: Final[str] = "milestones:update:position"
MILESTONES_UPDATE_DEPENDENCIES: Final[str] = "milestones:update:dependencies"
MILESTONES_UPDATE_VENDORS: Final[str] = "milestones:update:vendors"

# --- activities ---
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
# §3.8 (2026-06-02 audit): mirror of canonical; seeded + granted via r009.
ACTIVITIES_UPDATE_CATEGORY: Final[str] = "activities:update:category"
ACTIVITIES_UPDATE_CCN_VALUE: Final[str] = "activities:update:ccn_value"
ACTIVITIES_UPDATE_OWNER_DIVISION_OTHER: Final[str] = "activities:update:owner_division_other"
ACTIVITIES_UPDATE_CONCERNED_DIVISION_OTHER: Final[str] = "activities:update:concerned_division_other"
ACTIVITIES_UPDATE_RESOURCE: Final[str] = "activities:update:resource"
ACTIVITIES_UPDATE_DEPENDENCIES: Final[str] = "activities:update:dependencies"

# --- tasks ---
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

# --- subtasks ---
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
# Field-level write code maps for the field-walker helper.
# =========================================================================

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
    # Doc-finance — all three finance fields gate on the same code.
    "total_project_value_excl_tax": PROJECTS_UPDATE_FINANCE,
    "tax_percent": PROJECTS_UPDATE_FINANCE,
    "ccn_cap_percent": PROJECTS_UPDATE_FINANCE,
    # Sub-resource handled separately in service; still gated via field walker.
    "vendor_ids": PROJECTS_UPDATE_VENDORS,
    # §3.8 (2026-06-02 audit): generic-PATCH gates for lifecycle-adjacent
    # columns. ``status`` here gates raw writes — formal lifecycle goes
    # through PROJECTS_PUBLISH/CLOSE/REOPEN endpoints.
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
    # §3.8 (2026-06-02 audit): close schema-accepted-but-ungated gap.
    "category": ACTIVITIES_UPDATE_CATEGORY,
    "ccn_value": ACTIVITIES_UPDATE_CCN_VALUE,
    "owner_division_other": ACTIVITIES_UPDATE_OWNER_DIVISION_OTHER,
    "concerned_division_other": ACTIVITIES_UPDATE_CONCERNED_DIVISION_OTHER,
    # §3.14 (2026-06-02 audit): "resource" key removed (UpdateRequest
    # schema rejects the field). Constant kept but inert.
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
    # §3.14 (2026-06-02 audit): "resource" key removed (schema rejects it).
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
    # §3.14 (2026-06-02 audit): "resource" key removed (schema rejects it).
    "depends_on": SUBTASKS_UPDATE_DEPENDENCIES,
}


# =========================================================================
# Masters reads that project-svc may need
# =========================================================================
PRIORITIES_READ: Final[str] = "priorities:read"
PROJECT_CATEGORIES_READ: Final[str] = "project_categories:read"
ACTIVITY_TYPES_READ: Final[str] = "activity_types:read"
ACTIVITY_STATUSES_READ: Final[str] = "activity_statuses:read"
MILESTONE_STATUSES_READ: Final[str] = "milestone_statuses:read"
VENDORS_READ: Final[str] = "vendors:read"
VENDORS_MANAGE: Final[str] = "vendors:manage"
RESOURCE_TYPES_READ: Final[str] = "resource_types:read"


# =========================================================================
# Role-tier name constants — used by admin-tier filters
# =========================================================================
SUPER_ADMIN_ROLE: Final[str] = "super_admin"
ADMIN_ROLE: Final[str] = "admin"
ORG_ADMIN_ROLE: Final[str] = "org_admin"
PROJECT_ADMIN_ROLE: Final[str] = "project_admin"
PROJECT_MEMBER_ROLE: Final[str] = "project_member"
DIVISION_MEMBER_ROLE: Final[str] = "division_member"
