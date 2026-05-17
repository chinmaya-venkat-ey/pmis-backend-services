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
    # Monolith parity: errorIdentifier is lowercase snake_case on the wire.
    default_code: str = "internal_error"

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
    default_code = "not_found"


class ConflictError(DomainError):
    status_code = 409
    default_code = "conflict"


class ForbiddenError(DomainError):
    status_code = 403
    default_code = "forbidden"


class UnauthorizedError(DomainError):
    status_code = 401
    default_code = "unauthorized"


class ValidationError(DomainError):
    status_code = 422
    default_code = "validation_error"


# ---------------------------------------------------------------------------
# project-svc specific
# ---------------------------------------------------------------------------

class ProjectNotFoundError(NotFoundError):
    # Monolith parity: every NotFound* error uses the generic ``not_found``
    # identifier on the wire (matches monolith ``app/core/errors.py``).
    # The specific entity (project / milestone / …) is conveyed via the
    # ``message`` text only.
    default_code = "not_found"


class ProjectCodeConflictError(ConflictError):
    default_code = "project_code_conflict"


class MilestoneNotFoundError(NotFoundError):
    default_code = "not_found"


class ActivityNotFoundError(NotFoundError):
    default_code = "not_found"


class TaskNotFoundError(NotFoundError):
    default_code = "not_found"


class SubtaskNotFoundError(NotFoundError):
    default_code = "not_found"


class CommentNotFoundError(NotFoundError):
    default_code = "not_found"


class InvalidStatusTransitionError(ConflictError):
    """Project status transition not allowed by the masters.project_status_transitions
    catalog."""

    default_code = "invalid_status_transition"


class AttachmentTooLargeError(ValidationError):
    """Monolith parity: surfaces as 422 with the generic
    ``validation_error`` identifier — NOT 409 / a specific code."""


class AttachmentDisallowedExtensionError(ValidationError):
    """Monolith parity: surfaces as 422 with the generic
    ``validation_error`` identifier — NOT 409 / a specific code."""


class StorageUnavailableError(DomainError):
    """Raised when the attachment storage backend (NFS mount / file server)
    is unreachable or refuses writes. Maps to HTTP 503."""

    status_code = 503
    default_code = "storage_unavailable"


class CommentBodyOrAttachmentRequiredError(ValidationError):
    """Doc-35 send-event invariant: comment must carry body OR attachments."""

    default_code = "comment_body_or_attachment_required"


class DependencyCycleError(ConflictError):
    """milestone/activity/task/subtask dependency would introduce a cycle."""

    default_code = "dependency_cycle"


class CallerCannotModifyTargetError(ForbiddenError):
    default_code = "caller_cannot_modify_target"
