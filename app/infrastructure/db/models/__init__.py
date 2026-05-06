"""ORM model package — project-service in-use modules only.

Excluded vs monolith (per backport plan):
- users / roles / permissions / role_permission / user_role / user_permission
  are owned by user-service.
- meetings (+ participants + agenda items), work_packages, work_package_types,
  project_members are dormant in the current product flow.
- AttachmentModel was retired in doc 35 — file metadata now lives as a JSON
  column on CommentModel.
- notification_log / otp_code / password_reset_token / notification_template
  live on user-service.

UserModel and RevokedTokenModel are kept as read-only references because they
are FK targets used by queries here. project-service never writes them.
"""
from .activity import ActivityModel  # noqa: F401
from .activity_dependency import ActivityDependencyModel  # noqa: F401
from .activity_resource import ActivityResourceModel  # noqa: F401
from .activity_status import ActivityStatusModel  # noqa: F401
from .activity_type import ActivityTypeModel  # noqa: F401
from .comment import CommentModel  # noqa: F401
# Doc-21B RBAC tables — owned by user-service. project-service registers
# these as read-only models so the auth middleware can query effective
# permissions on each authenticated request.
from .permission import PermissionModel  # noqa: F401
from .role import RoleModel  # noqa: F401
from .role_permission import RolePermissionModel  # noqa: F401
from .user_role import UserRoleModel  # noqa: F401
from .user_permission import UserPermissionModel  # noqa: F401
from .division import DivisionModel  # noqa: F401
from .milestone import MilestoneModel  # noqa: F401
from .milestone_dependency import MilestoneDependencyModel  # noqa: F401
from .milestone_status import MilestoneStatusModel  # noqa: F401
from .milestone_vendor import MilestoneVendorModel  # noqa: F401
from .project import ProjectModel  # noqa: F401
from .project_audit_log import ProjectAuditLogModel  # noqa: F401
from .project_category import ProjectCategoryModel  # noqa: F401
from .project_member import ProjectMemberModel  # noqa: F401
from .project_status_transition import ProjectStatusTransitionModel  # noqa: F401
from .project_vendor import ProjectVendorModel  # noqa: F401
from .resource_type import ResourceTypeModel  # noqa: F401
from .revoked_token import RevokedTokenModel  # noqa: F401
from .subtask import SubtaskModel  # noqa: F401
from .subtask_dependency import SubtaskDependencyModel  # noqa: F401
from .subtask_resource import SubtaskResourceModel  # noqa: F401
from .task import TaskModel  # noqa: F401
from .task_dependency import TaskDependencyModel  # noqa: F401
from .task_resource import TaskResourceModel  # noqa: F401
from .user import UserModel  # noqa: F401
from .vendor import VendorModel  # noqa: F401

__all__ = [
    "ActivityDependencyModel",
    "ActivityModel",
    "ActivityResourceModel",
    "ActivityStatusModel",
    "ActivityTypeModel",
    "CommentModel",
    "DivisionModel",
    "MilestoneDependencyModel",
    "MilestoneModel",
    "MilestoneStatusModel",
    "MilestoneVendorModel",
    "PermissionModel",
    "ProjectAuditLogModel",
    "ProjectCategoryModel",
    "ProjectMemberModel",
    "ProjectModel",
    "ProjectStatusTransitionModel",
    "ProjectVendorModel",
    "ResourceTypeModel",
    "RevokedTokenModel",
    "RoleModel",
    "RolePermissionModel",
    "SubtaskDependencyModel",
    "SubtaskModel",
    "SubtaskResourceModel",
    "TaskDependencyModel",
    "TaskModel",
    "TaskResourceModel",
    "UserModel",
    "UserPermissionModel",
    "UserRoleModel",
    "VendorModel",
]
