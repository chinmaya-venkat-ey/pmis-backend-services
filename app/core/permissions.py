"""Canonical permission code registry (doc 21 part B).

Each constant is a stable string identifier referenced by route
``Depends(require_permission(CODE))`` decorators and by the seed step
that upserts permission rows into the DB at startup.

Adding a permission:
1. Add the constant here with ``("code", "human name", "description")``.
2. Add ``require_permission(CODE)`` to whichever route should gate on it.
3. Restart the app — the startup sync (``RbacRepository.sync_builtin_permissions``)
   inserts a new row in the ``permissions`` table and grants it to the
   ``admin`` role automatically.

Custom permissions created at runtime via ``POST /api/v3/permissions``
appear in the same DB table but with ``is_builtin=False``; they're
effective only if some route also references them. The decorator does
not error on an unknown code at decoration time — it just rejects
requests whose user does not hold the code.
"""
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class PermissionDef:
    code: str
    name: str
    description: str


# ---------------------------------------------------------------------------
# Built-in permissions
# ---------------------------------------------------------------------------

# Users
USERS_CREATE = "users:create"
USERS_READ = "users:read"
USERS_READ_ALL = "users:read_all"
USERS_UPDATE = "users:update"
USERS_UPDATE_ALL = "users:update_all"
USERS_DELETE = "users:delete"
USERS_DELETE_ALL = "users:delete_all"

# Projects
PROJECTS_CREATE = "projects:create"
PROJECTS_READ = "projects:read"
PROJECTS_READ_ALL = "projects:read_all"
PROJECTS_UPDATE = "projects:update"
PROJECTS_UPDATE_ALL = "projects:update_all"
PROJECTS_DELETE = "projects:delete"
PROJECTS_DELETE_ALL = "projects:delete_all"
PROJECTS_PUBLISH = "projects:publish"
PROJECTS_CLOSE = "projects:close"

# Catalogs (legacy per-catalog permissions; superseded by master_data:* but
# kept live so the deprecated routes keep working during the migration window).
VENDORS_READ = "vendors:read"
VENDORS_MANAGE = "vendors:manage"
RESOURCE_TYPES_READ = "resource_types:read"
RESOURCE_TYPES_MANAGE = "resource_types:manage"

# Master-data router (consolidated catalog CRUD)
MASTER_DATA_VIEW = "master_data:view"
MASTER_DATA_MANAGE = "master_data:manage"

# Project members
PROJECT_MEMBERS_READ = "project_members:read"
PROJECT_MEMBERS_ADD = "project_members:add"
PROJECT_MEMBERS_UPDATE = "project_members:update"
PROJECT_MEMBERS_DELETE = "project_members:delete"

# Roles
ROLES_READ = "roles:read"
ROLES_CREATE = "roles:create"
ROLES_UPDATE = "roles:update"
ROLES_DELETE = "roles:delete"

# Permissions (RBAC management surface — new in doc 21)
PERMISSIONS_READ = "permissions:read"
PERMISSIONS_MANAGE = "permissions:manage"

# RBAC assignment (user-role and user-permission grants)
RBAC_ASSIGN = "rbac:assign"

# Work packages
WORK_PACKAGES_VIEW = "work_packages:view"
WORK_PACKAGES_CREATE = "work_packages:create"
WORK_PACKAGES_UPDATE = "work_packages:update"
WORK_PACKAGES_DELETE = "work_packages:delete"
WORK_PACKAGE_TYPES_VIEW = "work_package_types:view"
WORK_PACKAGE_TYPES_MANAGE = "work_package_types:manage"

# Meetings
MEETINGS_VIEW = "meetings:view"
MEETINGS_CREATE = "meetings:create"
MEETINGS_UPDATE = "meetings:update"
MEETINGS_DELETE = "meetings:delete"

# Milestones
MILESTONES_CREATE = "milestones:create"
MILESTONES_READ = "milestones:read"
MILESTONES_UPDATE = "milestones:update"
MILESTONES_DELETE = "milestones:delete"
MILESTONES_RESTORE = "milestones:restore"

# Activities
ACTIVITIES_CREATE = "activities:create"
ACTIVITIES_READ = "activities:read"
ACTIVITIES_UPDATE = "activities:update"
ACTIVITIES_DELETE = "activities:delete"
ACTIVITIES_RESTORE = "activities:restore"

# Tasks
TASKS_CREATE = "tasks:create"
TASKS_READ = "tasks:read"
TASKS_UPDATE = "tasks:update"
TASKS_DELETE = "tasks:delete"
TASKS_RESTORE = "tasks:restore"

# Subtasks
SUBTASKS_CREATE = "subtasks:create"
SUBTASKS_READ = "subtasks:read"
SUBTASKS_UPDATE = "subtasks:update"
SUBTASKS_DELETE = "subtasks:delete"
SUBTASKS_RESTORE = "subtasks:restore"

# Comments / Attachments
COMMENTS_CREATE = "comments:create"
COMMENTS_READ = "comments:read"
COMMENTS_DELETE = "comments:delete"
ATTACHMENTS_CREATE = "attachments:create"
ATTACHMENTS_DOWNLOAD = "attachments:download"
ATTACHMENTS_DELETE = "attachments:delete"


BUILTIN_PERMISSIONS: List[PermissionDef] = [
    PermissionDef(USERS_CREATE, "Create user", "Create a new user account."),
    PermissionDef(USERS_READ, "View own user", "View own user record."),
    PermissionDef(USERS_READ_ALL, "View any user", "View any user record."),
    PermissionDef(USERS_UPDATE, "Update own user", "Edit own user record."),
    PermissionDef(USERS_UPDATE_ALL, "Update any user", "Edit any user record."),
    PermissionDef(USERS_DELETE, "Delete own user", "Soft-delete own user record."),
    PermissionDef(USERS_DELETE_ALL, "Delete any user", "Soft-delete any user record."),

    PermissionDef(PROJECTS_CREATE, "Create project", "Create a new project."),
    PermissionDef(PROJECTS_READ, "View own project", "View projects the user is a member of."),
    PermissionDef(PROJECTS_READ_ALL, "View any project", "View any project."),
    PermissionDef(PROJECTS_UPDATE, "Update own project", "Edit projects the user is a member of."),
    PermissionDef(PROJECTS_UPDATE_ALL, "Update any project", "Edit any project."),
    PermissionDef(PROJECTS_DELETE, "Delete own project", "Soft-delete projects the user is a member of."),
    PermissionDef(PROJECTS_DELETE_ALL, "Delete any project", "Soft-delete any project."),
    PermissionDef(PROJECTS_PUBLISH, "Publish project", "Move a project to published status."),
    PermissionDef(PROJECTS_CLOSE, "Close project", "Move a project to closed status."),

    PermissionDef(VENDORS_READ, "View vendors", "Read the vendor catalog (deprecated, use master_data:view)."),
    PermissionDef(VENDORS_MANAGE, "Manage vendors", "CRUD vendor catalog (deprecated, use master_data:manage)."),
    PermissionDef(RESOURCE_TYPES_READ, "View resource types", "Read the resource-type catalog (deprecated)."),
    PermissionDef(RESOURCE_TYPES_MANAGE, "Manage resource types", "CRUD resource-type catalog (deprecated)."),

    PermissionDef(MASTER_DATA_VIEW, "View master data", "Read divisions, status transitions, resource types, vendors via /master."),
    PermissionDef(MASTER_DATA_MANAGE, "Manage master data", "CRUD all master-data catalogs."),

    PermissionDef(PROJECT_MEMBERS_READ, "View project members", "List members of a project."),
    PermissionDef(PROJECT_MEMBERS_ADD, "Add project members", "Add members to a project."),
    PermissionDef(PROJECT_MEMBERS_UPDATE, "Update project members", "Edit member roles within a project."),
    PermissionDef(PROJECT_MEMBERS_DELETE, "Remove project members", "Remove members from a project."),

    PermissionDef(ROLES_READ, "View roles", "List roles and their permissions."),
    PermissionDef(ROLES_CREATE, "Create role", "Create a new role."),
    PermissionDef(ROLES_UPDATE, "Update role", "Edit a role's permissions or metadata."),
    PermissionDef(ROLES_DELETE, "Delete role", "Delete a role (built-in admin role is protected)."),

    PermissionDef(PERMISSIONS_READ, "View permissions", "List the permission catalog."),
    PermissionDef(PERMISSIONS_MANAGE, "Manage permissions", "Create / edit / delete permission rows."),
    PermissionDef(RBAC_ASSIGN, "Assign roles & permissions", "Grant or revoke roles and direct permissions on users."),

    PermissionDef(WORK_PACKAGES_VIEW, "View work packages", "Read work packages."),
    PermissionDef(WORK_PACKAGES_CREATE, "Create work package", "Create a work package."),
    PermissionDef(WORK_PACKAGES_UPDATE, "Update work package", "Edit a work package."),
    PermissionDef(WORK_PACKAGES_DELETE, "Delete work package", "Delete a work package."),
    PermissionDef(WORK_PACKAGE_TYPES_VIEW, "View WP types", "Read work-package types."),
    PermissionDef(WORK_PACKAGE_TYPES_MANAGE, "Manage WP types", "CRUD work-package types."),

    PermissionDef(MEETINGS_VIEW, "View meetings", "Read meetings."),
    PermissionDef(MEETINGS_CREATE, "Create meeting", "Create a meeting."),
    PermissionDef(MEETINGS_UPDATE, "Update meeting", "Edit a meeting."),
    PermissionDef(MEETINGS_DELETE, "Delete meeting", "Delete a meeting."),

    PermissionDef(MILESTONES_CREATE, "Create milestone", "Create a milestone under a project."),
    PermissionDef(MILESTONES_READ, "View milestones", "Read milestones."),
    PermissionDef(MILESTONES_UPDATE, "Update milestone", "Edit a milestone."),
    PermissionDef(MILESTONES_DELETE, "Delete milestone", "Soft-delete a milestone."),
    PermissionDef(MILESTONES_RESTORE, "Restore milestone", "Restore a soft-deleted milestone."),

    PermissionDef(ACTIVITIES_CREATE, "Create activity", "Create an activity under a milestone."),
    PermissionDef(ACTIVITIES_READ, "View activities", "Read activities."),
    PermissionDef(ACTIVITIES_UPDATE, "Update activity", "Edit an activity."),
    PermissionDef(ACTIVITIES_DELETE, "Delete activity", "Soft-delete an activity."),
    PermissionDef(ACTIVITIES_RESTORE, "Restore activity", "Restore a soft-deleted activity."),

    PermissionDef(TASKS_CREATE, "Create task", "Create a task under an activity."),
    PermissionDef(TASKS_READ, "View tasks", "Read tasks."),
    PermissionDef(TASKS_UPDATE, "Update task", "Edit a task."),
    PermissionDef(TASKS_DELETE, "Delete task", "Soft-delete a task."),
    PermissionDef(TASKS_RESTORE, "Restore task", "Restore a soft-deleted task."),

    PermissionDef(SUBTASKS_CREATE, "Create subtask", "Create a subtask under a task."),
    PermissionDef(SUBTASKS_READ, "View subtasks", "Read subtasks."),
    PermissionDef(SUBTASKS_UPDATE, "Update subtask", "Edit a subtask."),
    PermissionDef(SUBTASKS_DELETE, "Delete subtask", "Soft-delete a subtask."),
    PermissionDef(SUBTASKS_RESTORE, "Restore subtask", "Restore a soft-deleted subtask."),

    PermissionDef(COMMENTS_CREATE, "Create comment", "Add a comment on M/A/T/S."),
    PermissionDef(COMMENTS_READ, "View comments", "Read comments on M/A/T/S."),
    PermissionDef(COMMENTS_DELETE, "Delete comment", "Delete a comment (author or admin)."),
    PermissionDef(ATTACHMENTS_CREATE, "Upload attachment", "Upload a file attachment."),
    PermissionDef(ATTACHMENTS_DOWNLOAD, "Download attachment", "Download an attachment."),
    PermissionDef(ATTACHMENTS_DELETE, "Delete attachment", "Delete an attachment (author or admin)."),
]


# ---------------------------------------------------------------------------
# Seed roles (replicate the legacy in-code ROLE_PERMISSIONS map so users
# can opt in to the same coarse buckets).
# ---------------------------------------------------------------------------

ADMIN_ROLE_NAME = "admin"
MEMBER_ROLE_NAME = "member"
VIEWER_ROLE_NAME = "viewer"
# Doc 33: ``vendor`` is a new seeded role — vendors edit M/A/T/S
# directly on the project (versioning was removed) but cannot create
# new projects, change status, or touch RBAC / master data.
VENDOR_ROLE_NAME = "vendor"

# Doc 41 / doc 44 scoped-RBAC tier role names. Reference-only constants
# (read-side mirror — user-service is the canonical seed owner, see
# pmis-user-service/app/core/permissions.py). Used by vendor PATCH
# tier-aware allowlist gating and the GET /projects/{id}/assignable-
# users endpoint to query user_role_assignments by role name.
SUPER_ADMIN_ROLE_NAME = "super_admin"
ORG_ADMIN_ROLE_NAME = "org_admin"
PROJECT_ADMIN_ROLE_NAME = "project_admin"
PROJECT_MEMBER_ROLE_NAME = "project_member"
DIVISION_MEMBER_ROLE_NAME = "division_member"

# The admin role holds EVERY permission in BUILTIN_PERMISSIONS — synced on
# startup. Listed here for clarity / tests.
ADMIN_ROLE_PERMISSIONS: List[str] = [p.code for p in BUILTIN_PERMISSIONS]

MEMBER_ROLE_PERMISSIONS: List[str] = [
    USERS_READ, USERS_UPDATE,
    PROJECTS_READ, PROJECTS_CREATE, PROJECTS_UPDATE,
    VENDORS_READ, RESOURCE_TYPES_READ, MASTER_DATA_VIEW,
    PROJECT_MEMBERS_READ, PROJECT_MEMBERS_ADD, PROJECT_MEMBERS_UPDATE,
    WORK_PACKAGES_VIEW, WORK_PACKAGES_CREATE, WORK_PACKAGES_UPDATE, WORK_PACKAGES_DELETE,
    WORK_PACKAGE_TYPES_VIEW,
    MEETINGS_VIEW, MEETINGS_CREATE, MEETINGS_UPDATE, MEETINGS_DELETE,
    MILESTONES_CREATE, MILESTONES_READ, MILESTONES_UPDATE, MILESTONES_DELETE,
    ACTIVITIES_CREATE, ACTIVITIES_READ, ACTIVITIES_UPDATE, ACTIVITIES_DELETE,
    TASKS_CREATE, TASKS_READ, TASKS_UPDATE, TASKS_DELETE,
    SUBTASKS_CREATE, SUBTASKS_READ, SUBTASKS_UPDATE, SUBTASKS_DELETE,
    COMMENTS_CREATE, COMMENTS_READ, COMMENTS_DELETE,
    ATTACHMENTS_CREATE, ATTACHMENTS_DOWNLOAD, ATTACHMENTS_DELETE,
]

VIEWER_ROLE_PERMISSIONS: List[str] = [
    USERS_READ, PROJECTS_READ, VENDORS_READ, RESOURCE_TYPES_READ,
    MASTER_DATA_VIEW,
    PROJECT_MEMBERS_READ, WORK_PACKAGES_VIEW, MEETINGS_VIEW,
    MILESTONES_READ, ACTIVITIES_READ, TASKS_READ, SUBTASKS_READ,
    COMMENTS_READ, ATTACHMENTS_DOWNLOAD,
]

# Doc 33: vendor role.
#
# Vendors interact with the project content (M/A/T/S, comments, files)
# but not with project lifecycle (create / publish / close / delete) or
# RBAC / master data.
#
# Excluded relative to MEMBER_ROLE_PERMISSIONS:
#   - PROJECTS_CREATE       (cannot create new projects)
#   - PROJECTS_PUBLISH/CLOSE (lifecycle is admin-only)
#   - PROJECTS_DELETE/_ALL   (no destructive project actions)
#   - WORK_PACKAGES_*        (admin-tier module)
#   - MEETINGS_CREATE/UPDATE/DELETE (admin/member-driven)
#
# Included:
#   - own-user read/update (so vendors can edit their profile)
#   - read-only on master data + vendor catalog + project-members
#   - full M/A/T/S CRUD on assigned projects
#   - comments + attachments full
#   - meetings view-only
VENDOR_ROLE_PERMISSIONS: List[str] = [
    USERS_READ, USERS_UPDATE,
    PROJECTS_READ, PROJECTS_UPDATE,
    VENDORS_READ, RESOURCE_TYPES_READ, MASTER_DATA_VIEW,
    PROJECT_MEMBERS_READ,
    MEETINGS_VIEW,
    MILESTONES_CREATE, MILESTONES_READ, MILESTONES_UPDATE, MILESTONES_DELETE,
    ACTIVITIES_CREATE, ACTIVITIES_READ, ACTIVITIES_UPDATE, ACTIVITIES_DELETE,
    TASKS_CREATE, TASKS_READ, TASKS_UPDATE, TASKS_DELETE,
    SUBTASKS_CREATE, SUBTASKS_READ, SUBTASKS_UPDATE, SUBTASKS_DELETE,
    COMMENTS_CREATE, COMMENTS_READ, COMMENTS_DELETE,
    ATTACHMENTS_CREATE, ATTACHMENTS_DOWNLOAD, ATTACHMENTS_DELETE,
]
