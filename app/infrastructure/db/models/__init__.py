"""ORM model package.

Each module (vendors, resource_types, projects, milestones, ...) adds
its model imports here as it gets ported. Importing this package
registers every model on ``Base.metadata``, which Alembic autogenerate
and ``Base.metadata.create_all()`` (used by tests) both rely on.
"""
from .activity import ActivityModel # noqa: F401
from .activity_dependency import ActivityDependencyModel # noqa: F401
from .activity_resource import ActivityResourceModel # noqa: F401
from .attachment import AttachmentModel # noqa: F401
from .comment import CommentModel # noqa: F401
from .division import DivisionModel # noqa: F401
from .milestone import MilestoneModel # noqa: F401
from .milestone_vendor import MilestoneVendorModel # noqa: F401
from .project import ProjectModel # noqa: F401
from .project_audit_log import ProjectAuditLogModel # noqa: F401
from .project_status_transition import ProjectStatusTransitionModel # noqa: F401
from .project_vendor import ProjectVendorModel # noqa: F401
from .project_member import ProjectMemberModel  # noqa: F401
from .resource_type import ResourceTypeModel # noqa: F401
from .revoked_token import RevokedTokenModel  # noqa: F401
from .subtask import SubtaskModel # noqa: F401
from .subtask_dependency import SubtaskDependencyModel # noqa: F401
from .subtask_resource import SubtaskResourceModel # noqa: F401
from .task import TaskModel # noqa: F401
from .task_dependency import TaskDependencyModel # noqa: F401
from .task_resource import TaskResourceModel # noqa: F401
from .user import UserModel  # noqa: F401
from .vendor import VendorModel # noqa: F401

__all__ = [
    "ActivityDependencyModel",
    "ActivityModel",
    "ActivityResourceModel",
    "AttachmentModel",
    "CommentModel",
    "DivisionModel",
    "MilestoneModel",
    "MilestoneVendorModel",
    "ProjectAuditLogModel",
    "ProjectMemberModel",
    "ProjectModel",
    "ProjectStatusTransitionModel",
    "ProjectVendorModel",
    "ResourceTypeModel",
    "RevokedTokenModel",
    "SubtaskDependencyModel",
    "SubtaskModel",
    "SubtaskResourceModel",
    "TaskDependencyModel",
    "TaskModel",
    "TaskResourceModel",
    "UserModel",
    "VendorModel",
    ]
