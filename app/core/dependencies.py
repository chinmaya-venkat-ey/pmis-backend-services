"""
Core dependencies for dependency injection.
"""
from typing import Optional
from fastapi import Request
from .rbac import Role


def get_current_user_id(request: Request) -> Optional[int]:
    """
    Get the current user ID from request state.

    Args:
        request: FastAPI request

    Returns:
        User ID if authenticated, None otherwise
    """
    return getattr(request.state, "user_id", None)


def get_current_user_role(request: Request) -> Role:
    """
    Get the current user role from request state.

    Args:
        request: FastAPI request

    Returns:
        User role
    """
    return getattr(request.state, "user_role", Role.ANONYMOUS)


def get_current_user_login(request: Request) -> Optional[str]:
    """
    Get the current user login from request state.

    Args:
        request: FastAPI request

    Returns:
        User login if authenticated, None otherwise
    """
    return getattr(request.state, "user_login", None)
