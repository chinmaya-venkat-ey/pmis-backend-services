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

class ProjectLdConfigNotFoundError(NotFoundError):
    default_code = "not_found"

class SlaNotFoundError(NotFoundError):
    default_code = "not_found"

class FormulaNotFoundError(NotFoundError):
    default_code = "not_found"

class ObservationNotFoundError(NotFoundError):
    default_code = "not_found"

class EvaluationNotFoundError(NotFoundError):
    default_code = "not_found"

class DslParseError(ValidationError):
    default_code = "dsl_parse_error"

class AslValidationError(ValidationError):
    default_code = "asl_validation_error"

class DuplicateObservationError(ConflictError):
    default_code = "duplicate_observation"
