"""RBAC — Permission enum + ROLE_PERMISSIONS mapping.

Ported verbatim from the monolith. Lives here (not in the shared
package) because the user-service is the service that stamps role
claims into JWTs; the monolith and any future service reads those
claims but does not own them.

The monolith still has its own copy in Phase 1. When we swap the
monolith over in Phase 4, it imports from here instead.
"""
from enum import Enum
from typing import Dict, Set


class Role(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"
    ANONYMOUS = "anonymous"


class Permission(str, Enum):
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

    VENDORS_READ = "vendors:read"
    VENDORS_MANAGE = "vendors:manage"

    RESOURCE_TYPES_READ = "resource_types:read"
    RESOURCE_TYPES_MANAGE = "resource_types:manage"

    PROJECT_MEMBERS_READ = "project_members:read"
    PROJECT_MEMBERS_ADD = "project_members:add"
    PROJECT_MEMBERS_UPDATE = "project_members:update"
    PROJECT_MEMBERS_DELETE = "project_members:delete"

    ROLES_READ = "roles:read"
    ROLES_CREATE = "roles:create"
    ROLES_UPDATE = "roles:update"
    ROLES_DELETE = "roles:delete"

    WORK_PACKAGES_VIEW = "work_packages:view"
    WORK_PACKAGES_CREATE = "work_packages:create"
    WORK_PACKAGES_UPDATE = "work_packages:update"
    WORK_PACKAGES_DELETE = "work_packages:delete"
    WORK_PACKAGE_TYPES_VIEW = "work_package_types:view"
    WORK_PACKAGE_TYPES_MANAGE = "work_package_types:manage"

    MEETINGS_VIEW = "meetings:view"
    MEETINGS_CREATE = "meetings:create"
    MEETINGS_UPDATE = "meetings:update"
    MEETINGS_DELETE = "meetings:delete"

    MILESTONES_CREATE = "milestones:create"
    MILESTONES_READ = "milestones:read"
    MILESTONES_UPDATE = "milestones:update"
    MILESTONES_DELETE = "milestones:delete"
    MILESTONES_RESTORE = "milestones:restore"

    ACTIVITIES_CREATE = "activities:create"
    ACTIVITIES_READ = "activities:read"
    ACTIVITIES_UPDATE = "activities:update"
    ACTIVITIES_DELETE = "activities:delete"
    ACTIVITIES_RESTORE = "activities:restore"

    TASKS_CREATE = "tasks:create"
    TASKS_READ = "tasks:read"
    TASKS_UPDATE = "tasks:update"
    TASKS_DELETE = "tasks:delete"
    TASKS_RESTORE = "tasks:restore"

    SUBTASKS_CREATE = "subtasks:create"
    SUBTASKS_READ = "subtasks:read"
    SUBTASKS_UPDATE = "subtasks:update"
    SUBTASKS_DELETE = "subtasks:delete"
    SUBTASKS_RESTORE = "subtasks:restore"


ROLE_PERMISSIONS: Dict[Role, Set[Permission]] = {
    Role.ADMIN: {p for p in Permission},
    Role.MEMBER: {
        Permission.USERS_READ,
        Permission.USERS_UPDATE,
        Permission.PROJECTS_READ,
        Permission.PROJECTS_CREATE,
        Permission.PROJECTS_UPDATE,
        Permission.VENDORS_READ,
        Permission.RESOURCE_TYPES_READ,
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
    },
    Role.VIEWER: {
        Permission.USERS_READ,
        Permission.PROJECTS_READ,
        Permission.VENDORS_READ,
        Permission.RESOURCE_TYPES_READ,
        Permission.PROJECT_MEMBERS_READ,
        Permission.WORK_PACKAGES_VIEW,
        Permission.MEETINGS_VIEW,
        Permission.MILESTONES_READ,
        Permission.ACTIVITIES_READ,
        Permission.TASKS_READ,
        Permission.SUBTASKS_READ,
    },
    Role.ANONYMOUS: set(),
}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())


def get_role_permissions(role: Role) -> Set[Permission]:
    return ROLE_PERMISSIONS.get(role, set())
