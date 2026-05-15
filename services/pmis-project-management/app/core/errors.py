"""Domain error hierarchy for pmis-project-management.

Duplicates the user-svc canonical DomainError hierarchy and adds project-svc
specific subclasses (project / milestone / activity / task / subtask / comment
NotFound + a few status-transition errors).

WARNING: Keep base classes in sync with services/pmis-user-management/app/core/errors.py.
"""
from __future__ import annotations

from typing import Optional


class DomainError(Exception):
    status_code: int = 500
    default_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str = "",
        *,
        code: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.details = details or {}


class NotFoundError(DomainError):
    status_code = 404
    default_code = "NOT_FOUND"


class ConflictError(DomainError):
    status_code = 409
    default_code = "CONFLICT"


class ForbiddenError(DomainError):
    status_code = 403
    default_code = "FORBIDDEN"


class UnauthorizedError(DomainError):
    status_code = 401
    default_code = "UNAUTHORIZED"


class ValidationError(DomainError):
    status_code = 422
    default_code = "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# project-svc specific
# ---------------------------------------------------------------------------

class ProjectNotFoundError(NotFoundError):
    default_code = "PROJECT_NOT_FOUND"


class ProjectCodeConflictError(ConflictError):
    default_code = "PROJECT_CODE_CONFLICT"


class MilestoneNotFoundError(NotFoundError):
    default_code = "MILESTONE_NOT_FOUND"


class ActivityNotFoundError(NotFoundError):
    default_code = "ACTIVITY_NOT_FOUND"


class TaskNotFoundError(NotFoundError):
    default_code = "TASK_NOT_FOUND"


class SubtaskNotFoundError(NotFoundError):
    default_code = "SUBTASK_NOT_FOUND"


class CommentNotFoundError(NotFoundError):
    default_code = "COMMENT_NOT_FOUND"


class InvalidStatusTransitionError(ConflictError):
    """Project status transition not allowed by the masters.project_status_transitions
    catalog."""

    default_code = "INVALID_STATUS_TRANSITION"


class SubtaskNestingDepthExceededError(ConflictError):
    """Subtask parent chain exceeds settings.subtask_max_nesting_depth."""

    default_code = "SUBTASK_NESTING_DEPTH_EXCEEDED"


class AttachmentTooLargeError(ConflictError):
    default_code = "ATTACHMENT_TOO_LARGE"


class AttachmentDisallowedExtensionError(ConflictError):
    default_code = "ATTACHMENT_DISALLOWED_EXTENSION"


class StorageUnavailableError(DomainError):
    """Raised when the attachment storage backend (NFS mount / file server)
    is unreachable or refuses writes. Maps to HTTP 503."""

    status_code = 503
    default_code = "STORAGE_UNAVAILABLE"


class CommentBodyOrAttachmentRequiredError(ValidationError):
    """Doc-35 send-event invariant: comment must carry body OR attachments."""

    default_code = "COMMENT_BODY_OR_ATTACHMENT_REQUIRED"


class DependencyCycleError(ConflictError):
    """milestone/activity/task/subtask dependency would introduce a cycle."""

    default_code = "DEPENDENCY_CYCLE"


class CallerCannotModifyTargetError(ForbiddenError):
    default_code = "CALLER_CANNOT_MODIFY_TARGET"
