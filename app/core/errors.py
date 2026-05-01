"""Domain errors + HTTP status mapping — ported verbatim from the monolith."""
from typing import Any, Dict, Optional


class DomainError(Exception):
    """Base class for domain errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(DomainError):
    pass


class AlreadyExistsError(DomainError):
    pass


class ValidationError(DomainError):
    pass


class AuthenticationError(DomainError):
    pass


class AuthorizationError(DomainError):
    pass


class InvalidCredentialsError(DomainError):
    pass


class TokenExpiredError(DomainError):
    pass


class InvalidTokenError(DomainError):
    pass


ERROR_HTTP_STATUS = {
    NotFoundError: 404,
    AlreadyExistsError: 409,
    ValidationError: 422,
    AuthenticationError: 401,
    AuthorizationError: 403,
    InvalidCredentialsError: 401,
    TokenExpiredError: 401,
    InvalidTokenError: 401,
}


def get_http_status(error: Exception) -> int:
    return ERROR_HTTP_STATUS.get(type(error), 500)
