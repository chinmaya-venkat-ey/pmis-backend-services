"""Domain error hierarchy for pmis-masters-management.

Services raise these; the @app.exception_handler in middleware/error_handler.py
translates them to consistent JSON envelopes. No HTTPException in service code.

WARNING: This file is duplicated across services per PLAN.md §6.1 (no shared
package). The currently-canonical version will live in
  services/pmis-user-management/app/core/errors.py
once user-svc is ported. For now (notification-svc + masters-svc ported,
user-svc pending) the duplicates must be kept identical by hand.
The tools/check_canonical_drift.py CI check (Phase 3 follow-up) will enforce.
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


# Masters-svc-specific subclasses (referenced by services/repositories).
class CatalogEntryNotFoundError(NotFoundError):
    default_code = "CATALOG_ENTRY_NOT_FOUND"


class CatalogEntryConflictError(ConflictError):
    """e.g. unique-code clash on create / restore."""

    default_code = "CATALOG_ENTRY_CONFLICT"
