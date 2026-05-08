"""Repository package — project-service in-use modules only.

AttachmentRepository removed in doc 35 (attachment metadata now lives
inline on CommentModel.attachments JSON column).
"""
from .activity_repository import ActivityRepository  # noqa: F401
from .comment_repository import CommentRepository  # noqa: F401
from .dependency_repository import DependencyRepository  # noqa: F401
from .division_repository import DivisionRepository  # noqa: F401
from .milestone_repository import MilestoneRepository  # noqa: F401
from .project_audit_log_repository import ProjectAuditLogRepository  # noqa: F401
from .project_repository import ProjectRepository  # noqa: F401
from .project_status_transition_repository import (  # noqa: F401
    ProjectStatusTransitionRepository,
)
from .rbac_repository import RbacRepository  # noqa: F401
from .resource_type_repository import ResourceTypeRepository  # noqa: F401
from .revoked_token_repository import RevokedTokenRepository  # noqa: F401
from .subtask_repository import SubtaskRepository  # noqa: F401
from .task_repository import TaskRepository  # noqa: F401
from .vendor_repository import VendorRepository  # noqa: F401

__all__ = [
    "ActivityRepository",
    "CommentRepository",
    "DependencyRepository",
    "DivisionRepository",
    "MilestoneRepository",
    "ProjectAuditLogRepository",
    "ProjectRepository",
    "ProjectStatusTransitionRepository",
    "RbacRepository",
    "ResourceTypeRepository",
    "RevokedTokenRepository",
    "SubtaskRepository",
    "TaskRepository",
    "VendorRepository",
]
