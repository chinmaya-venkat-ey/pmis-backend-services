"""
Role-Based Access Control (RBAC) system.
"""
from enum import Enum
from typing import Set, Dict


class Role(str, Enum):
    """User roles in the system."""
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"
    ANONYMOUS = "anonymous"


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


# Role -> Permissions mapping
ROLE_PERMISSIONS: Dict[Role, Set[Permission]] = {
    Role.ADMIN: {
        Permission.USERS_CREATE,
        Permission.USERS_READ,
        Permission.USERS_READ_ALL,
        Permission.USERS_UPDATE,
        Permission.USERS_UPDATE_ALL,
        Permission.USERS_DELETE,
        Permission.USERS_DELETE_ALL,
        Permission.PROJECTS_CREATE,
        Permission.PROJECTS_READ,
        Permission.PROJECTS_READ_ALL,
        Permission.PROJECTS_UPDATE,
        Permission.PROJECTS_UPDATE_ALL,
        Permission.PROJECTS_DELETE,
        Permission.PROJECTS_DELETE_ALL,
        Permission.PROJECTS_PUBLISH,
        Permission.PROJECTS_CLOSE,
        Permission.VENDORS_READ,
        Permission.VENDORS_MANAGE,
        Permission.RESOURCE_TYPES_READ,
        Permission.RESOURCE_TYPES_MANAGE,
        Permission.MASTER_DATA_VIEW,
        Permission.MASTER_DATA_MANAGE,
        Permission.PROJECT_MEMBERS_READ,
        Permission.PROJECT_MEMBERS_ADD,
        Permission.PROJECT_MEMBERS_UPDATE,
        Permission.PROJECT_MEMBERS_DELETE,
        Permission.ROLES_READ,
        Permission.ROLES_CREATE,
        Permission.ROLES_UPDATE,
        Permission.ROLES_DELETE,
        Permission.WORK_PACKAGES_VIEW,
        Permission.WORK_PACKAGES_CREATE,
        Permission.WORK_PACKAGES_UPDATE,
        Permission.WORK_PACKAGES_DELETE,
        Permission.WORK_PACKAGE_TYPES_VIEW,
        Permission.WORK_PACKAGE_TYPES_MANAGE,
        Permission.MEETINGS_VIEW,
        Permission.MEETINGS_CREATE,
        Permission.MEETINGS_UPDATE,
        Permission.MEETINGS_DELETE,
        Permission.MILESTONES_CREATE,
        Permission.MILESTONES_READ,
        Permission.MILESTONES_UPDATE,
        Permission.MILESTONES_DELETE,
        Permission.MILESTONES_RESTORE,
        Permission.ACTIVITIES_CREATE,
        Permission.ACTIVITIES_READ,
        Permission.ACTIVITIES_UPDATE,
        Permission.ACTIVITIES_DELETE,
        Permission.ACTIVITIES_RESTORE,
        Permission.TASKS_CREATE,
        Permission.TASKS_READ,
        Permission.TASKS_UPDATE,
        Permission.TASKS_DELETE,
        Permission.TASKS_RESTORE,
        Permission.SUBTASKS_CREATE,
        Permission.SUBTASKS_READ,
        Permission.SUBTASKS_UPDATE,
        Permission.SUBTASKS_DELETE,
        Permission.SUBTASKS_RESTORE,
        Permission.COMMENTS_CREATE,
        Permission.COMMENTS_READ,
        Permission.COMMENTS_DELETE,
        Permission.ATTACHMENTS_CREATE,
        Permission.ATTACHMENTS_DOWNLOAD,
        Permission.ATTACHMENTS_DELETE,
    },
    Role.MEMBER: {
        Permission.USERS_READ,
        Permission.USERS_UPDATE,
        Permission.PROJECTS_READ,
        Permission.PROJECTS_CREATE,
        Permission.PROJECTS_UPDATE,
        Permission.VENDORS_READ,
        Permission.RESOURCE_TYPES_READ,
        Permission.MASTER_DATA_VIEW,
        Permission.PROJECT_MEMBERS_READ,
        Permission.PROJECT_MEMBERS_ADD,
        Permission.PROJECT_MEMBERS_UPDATE,
        Permission.WORK_PACKAGES_VIEW,
        Permission.WORK_PACKAGES_CREATE,
        Permission.WORK_PACKAGES_UPDATE,
        Permission.WORK_PACKAGES_DELETE,
        Permission.WORK_PACKAGE_TYPES_VIEW,
        Permission.MEETINGS_VIEW,
        Permission.MEETINGS_CREATE,
        Permission.MEETINGS_UPDATE,
        Permission.MEETINGS_DELETE,
        Permission.MILESTONES_CREATE,
        Permission.MILESTONES_READ,
        Permission.MILESTONES_UPDATE,
        Permission.MILESTONES_DELETE,
        Permission.ACTIVITIES_CREATE,
        Permission.ACTIVITIES_READ,
        Permission.ACTIVITIES_UPDATE,
        Permission.ACTIVITIES_DELETE,
        Permission.TASKS_CREATE,
        Permission.TASKS_READ,
        Permission.TASKS_UPDATE,
        Permission.TASKS_DELETE,
        Permission.SUBTASKS_CREATE,
        Permission.SUBTASKS_READ,
        Permission.SUBTASKS_UPDATE,
        Permission.SUBTASKS_DELETE,
        Permission.COMMENTS_CREATE,
        Permission.COMMENTS_READ,
        Permission.COMMENTS_DELETE,
        Permission.ATTACHMENTS_CREATE,
        Permission.ATTACHMENTS_DOWNLOAD,
        Permission.ATTACHMENTS_DELETE,
    },
    Role.VIEWER: {
        Permission.USERS_READ,
        Permission.PROJECTS_READ,
        Permission.VENDORS_READ,
        Permission.RESOURCE_TYPES_READ,
        Permission.MASTER_DATA_VIEW,
        Permission.PROJECT_MEMBERS_READ,
        Permission.WORK_PACKAGES_VIEW,
        Permission.MEETINGS_VIEW,
        Permission.MILESTONES_READ,
        Permission.ACTIVITIES_READ,
        Permission.TASKS_READ,
        Permission.SUBTASKS_READ,
        Permission.COMMENTS_READ,
        Permission.ATTACHMENTS_DOWNLOAD,
    },
    Role.ANONYMOUS: set(),
}


def has_permission(role: Role, permission: Permission) -> bool:
    """
    Check if a role has a specific permission.

    Args:
        role: User role
        permission: Required permission

    Returns:
        True if role has permission, False otherwise
    """
    return permission in ROLE_PERMISSIONS.get(role, set())


def get_role_permissions(role: Role) -> Set[Permission]:
    """
    Get all permissions for a role.

    Args:
        role: User role

    Returns:
        Set of permissions for the role
    """
    return ROLE_PERMISSIONS.get(role, set())
