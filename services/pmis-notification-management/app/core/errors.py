"""Domain error hierarchy.

Services raise these; the @app.exception_handler in app/middleware/error_handler.py
translates them to consistent JSON envelopes. No HTTPException in service code.

Pattern: every error has:
  - status_code  — HTTP status for the response
  - code         — machine-readable identifier (e.g. "NOT_FOUND", "TEMPLATE_MISSING")
  - message      — human-readable
  - details      — optional dict for structured context
"""
from __future__ import annotations

from typing import Optional


class DomainError(Exception):
    """Base for all expected errors. Subclass to set status_code + code."""

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


class ProviderError(DomainError):
    """External provider failure (SMTP refusal, SMS gateway error, etc.)."""

    status_code = 502
    default_code = "PROVIDER_ERROR"


class CronUnauthorizedError(UnauthorizedError):
    """X-Cron-Secret missing or mismatched."""

    default_code = "CRON_UNAUTHORIZED"


class TemplateMissingError(NotFoundError):
    """Notification template lookup returned no row."""

    default_code = "TEMPLATE_MISSING"
