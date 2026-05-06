"""
Centralized error definitions and HTTP error mapping.
"""
from typing import Optional, Dict, Any


class DomainError(Exception): # Exception built in class
    """Base class for domain errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(DomainError):
    """Resource not found error."""
    pass


class AlreadyExistsError(DomainError):
    """Resource already exists error."""
    pass


class ValidationError(DomainError):
    """Validation error."""
    pass


class AuthenticationError(DomainError):
    """Authentication error."""
    pass


class AuthorizationError(DomainError):
    """Authorization error."""
    pass


class InvalidCredentialsError(DomainError):
    """Invalid credentials error."""
    pass


class TokenExpiredError(DomainError):
    """Token expired error."""
    pass


class InvalidTokenError(DomainError):
    """Invalid token error."""
    pass


# HTTP status code mapping
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
    """
    Get HTTP status code for an error.

    Args:
        error: Exception instance

    Returns:
        HTTP status code
    """
    return ERROR_HTTP_STATUS.get(type(error), 500)
