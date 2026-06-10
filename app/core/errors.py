"""Domain error hierarchy for pmis-contract-management."""
from __future__ import annotations

from typing import Optional


class DomainError(Exception):
    status_code: int = 500
    default_code: str = "internal_error"

    def __init__(self, message: str = "", *, code=None, details=None):
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

class ServiceUnavailableError(DomainError):
    # Raised when a downstream service (e.g. pmis-file-store) is down,
    # mis-configured, or returns 5xx. The error handler maps this to 503.
    status_code = 503
    default_code = "service_unavailable"
