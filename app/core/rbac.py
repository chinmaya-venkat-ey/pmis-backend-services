"""
Role-Based Access Control (RBAC) — permission constants.

Doc 33 (change 2) RBAC artifact cleanup:
- ``Role`` enum DELETED. Doc 21B replaced the in-memory role concept
  with seeded ``roles`` table rows. The enum had no remaining call
  sites — its only consumers were ``ROLE_PERMISSIONS`` (also deleted
  here) and the dead helpers ``has_permission`` / ``get_role_permissions``.
- ``ROLE_PERMISSIONS`` dict DELETED. Per-role permission sets now live
  in the ``role_permissions`` DB table, seeded by
  ``RbacRepository.sync_builtin_permissions`` from the lists in
  ``app/core/permissions.py``.
- ``has_permission()`` / ``get_role_permissions()`` DELETED — never
  called. The runtime check uses ``request.state.user_permissions``,
  populated per-request from the DB by the auth middleware.

The ``Permission`` enum below is kept as a transitional bridge: every
``app/api/v3/*/permissions.py`` re-export shim still imports it. The
canonical form going forward is the string constants in
``app/core/permissions.py``; the enum will be deprecated when those
shims are migrated to direct strings.
"""
from enum import Enum


class Permission(str, Enum):
    """System permissions."""
    # User permissions
    USERS_CREATE = "users:create"
    USERS_READ = "users:read"
    USERS_READ_ALL = "users:read_all"
    USERS_UPDATE = "users:update"
    USERS_UPDATE_ALL = "users:update_all"
    USERS_DELETE = "users:delete"
    USERS_DELETE_ALL = "users:delete_all"
    
    # Project permissions
    PROJECTS_CREATE = "projects:create"
    PROJECTS_READ = "projects:read"
    PROJECTS_READ_ALL = "projects:read_all"
    PROJECTS_UPDATE = "projects:update"
    PROJECTS_UPDATE_ALL = "projects:update_all"
    PROJECTS_DELETE = "projects:delete"
    PROJECTS_DELETE_ALL = "projects:delete_all"
    PROJECTS_PUBLISH = "projects:publish"
    PROJECTS_CLOSE = "projects:close"

    # Vendor catalog (read = anyone authenticated; manage = admin only).
    VENDORS_READ = "vendors:read"
    VENDORS_MANAGE = "vendors:manage"

    # Resource-type catalog (read = anyone authenticated; manage = admin only).
    RESOURCE_TYPES_READ = "resource_types:read"
    RESOURCE_TYPES_MANAGE = "resource_types:manage"

    # Master-data router (doc 20). Single coarse pair that gates the
    # consolidated /api/v3/master/* endpoints across every catalog
    # (divisions, project_status_transitions, resource_types, vendors).
    # The legacy per-catalog permissions above remain in place so the
    # deprecated /vendors, /resource_types, /divisions etc. routes keep
    # working for FE during the migration window.
    MASTER_DATA_VIEW = "master_data:view"
    MASTER_DATA_MANAGE = "master_data:manage"

    # Project Members permissions
    PROJECT_MEMBERS_READ = "project_members:read"
    PROJECT_MEMBERS_ADD = "project_members:add"
    PROJECT_MEMBERS_UPDATE = "project_members:update"
    PROJECT_MEMBERS_DELETE = "project_members:delete"
    
    # Roles permissions
    ROLES_READ = "roles:read"
    ROLES_CREATE = "roles:create"
    ROLES_UPDATE = "roles:update"
    ROLES_DELETE = "roles:delete"
    
    # Work Packages permissions
    WORK_PACKAGES_VIEW = "work_packages:view"
    WORK_PACKAGES_CREATE = "work_packages:create"
    WORK_PACKAGES_UPDATE = "work_packages:update"
    WORK_PACKAGES_DELETE = "work_packages:delete"
    # Work Package Types permissions
    WORK_PACKAGE_TYPES_VIEW = "work_package_types:view"
    WORK_PACKAGE_TYPES_MANAGE = "work_package_types:manage"
    
    # Meetings permissions
    MEETINGS_VIEW = "meetings:view"
    MEETINGS_CREATE = "meetings:create"
    MEETINGS_UPDATE = "meetings:update"
    MEETINGS_DELETE = "meetings:delete"

    # Milestones permissions
    MILESTONES_CREATE = "milestones:create"
    MILESTONES_READ = "milestones:read"
    MILESTONES_UPDATE = "milestones:update"
    MILESTONES_DELETE = "milestones:delete"
    MILESTONES_RESTORE = "milestones:restore"

    # Activities permissions
    ACTIVITIES_CREATE = "activities:create"
    ACTIVITIES_READ = "activities:read"
    ACTIVITIES_UPDATE = "activities:update"
    ACTIVITIES_DELETE = "activities:delete"
    ACTIVITIES_RESTORE = "activities:restore"

    # Tasks permissions
    TASKS_CREATE = "tasks:create"
    TASKS_READ = "tasks:read"
    TASKS_UPDATE = "tasks:update"
    TASKS_DELETE = "tasks:delete"
    TASKS_RESTORE = "tasks:restore"

    # Subtasks permissions
    SUBTASKS_CREATE = "subtasks:create"
    SUBTASKS_READ = "subtasks:read"
    SUBTASKS_UPDATE = "subtasks:update"
    SUBTASKS_DELETE = "subtasks:delete"
    SUBTASKS_RESTORE = "subtasks:restore"

    # Comments permissions (apply to all M/A/T/S targets)
    # Author-vs-admin gating for update/delete is enforced in the service.
    COMMENTS_CREATE = "comments:create"
    COMMENTS_READ = "comments:read"
    COMMENTS_DELETE = "comments:delete"

    # Attachments permissions (file uploads / downloads)
    ATTACHMENTS_CREATE = "attachments:create"
    ATTACHMENTS_DOWNLOAD = "attachments:download"
    ATTACHMENTS_DELETE = "attachments:delete"


# ----------------------------------------------------------------------
# Role enum + ROLE_PERMISSIONS map.
#
# The monolith's doc-21B normalized permission tables don't exist in
# user-service's schema, so project-service uses a simpler in-code mapping
# from the role name minted into the JWT (`role` claim from user-service)
# to the set of permissions that role grants. The auth middleware reads
# this map to populate ``request.state.user_permissions``.
#
# Role names match user-service's ``app/core/rbac.py`` exactly so a JWT
# minted there resolves cleanly here.
# ----------------------------------------------------------------------


class Role(str, Enum):
    """Logical roles minted by user-service into the JWT."""
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"
    ANONYMOUS = "anonymous"


# Build out the role → permission set. Admins in practice get
# the full registry via the auth middleware's ``is_admin`` short-circuit;
# the explicit set below is kept for parity with user-service patterns.
_ALL_PERMISSIONS = set(Permission)

_VIEWER_PERMISSIONS = {
    Permission.PROJECTS_READ,
    Permission.MILESTONES_READ,
    Permission.ACTIVITIES_READ,
    Permission.TASKS_READ,
    Permission.SUBTASKS_READ,
    Permission.COMMENTS_READ,
    Permission.VENDORS_READ,
    Permission.RESOURCE_TYPES_READ,
    Permission.MASTER_DATA_VIEW,
}

_MEMBER_PERMISSIONS = _VIEWER_PERMISSIONS | {
    Permission.PROJECTS_CREATE,
    Permission.PROJECTS_UPDATE,
    Permission.PROJECTS_DELETE,
    Permission.PROJECTS_PUBLISH,
    Permission.PROJECTS_CLOSE,
    Permission.MILESTONES_CREATE,
    Permission.MILESTONES_UPDATE,
    Permission.MILESTONES_DELETE,
    Permission.MILESTONES_RESTORE,
    Permission.ACTIVITIES_CREATE,
    Permission.ACTIVITIES_UPDATE,
    Permission.ACTIVITIES_DELETE,
    Permission.ACTIVITIES_RESTORE,
    Permission.TASKS_CREATE,
    Permission.TASKS_UPDATE,
    Permission.TASKS_DELETE,
    Permission.TASKS_RESTORE,
    Permission.SUBTASKS_CREATE,
    Permission.SUBTASKS_UPDATE,
    Permission.SUBTASKS_DELETE,
    Permission.SUBTASKS_RESTORE,
    Permission.COMMENTS_CREATE,
    Permission.COMMENTS_DELETE,
    Permission.ATTACHMENTS_CREATE,
    Permission.ATTACHMENTS_DOWNLOAD,
    Permission.ATTACHMENTS_DELETE,
}

ROLE_PERMISSIONS = {
    Role.ADMIN: _ALL_PERMISSIONS,
    Role.MEMBER: _MEMBER_PERMISSIONS,
    Role.VIEWER: _VIEWER_PERMISSIONS,
    Role.ANONYMOUS: set(),
}
