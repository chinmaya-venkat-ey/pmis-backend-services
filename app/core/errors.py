"""Domain error hierarchy for pmis-file-store.

Base hierarchy duplicated from project-management for microservice isolation.
Keep base classes in sync across services.
"""
from __future__ import annotations

from typing import Optional


class DomainError(Exception):
    status_code: int = 500
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
# file-store specific
# ---------------------------------------------------------------------------

class FileNotFoundError(NotFoundError):
    default_code = "not_found"


class FileTooLargeError(ValidationError):
    default_code = "validation_error"


class FileExtensionNotAllowedError(ValidationError):
    default_code = "validation_error"


class StorageError(DomainError):
    """Raised when the S3 backend is unreachable or refuses the operation."""
    status_code = 503
    default_code = "storage_unavailable"


class S3UploadError(StorageError):
    default_code = "s3_upload_failed"


class S3DeleteError(StorageError):
    default_code = "s3_delete_failed"


class S3PresignError(StorageError):
    default_code = "s3_presign_failed"
