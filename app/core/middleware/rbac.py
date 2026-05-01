"""
RBAC middleware for permission-based authorization.
"""
from typing import Callable
from fastapi import Request, Depends
from ..rbac import Permission, Role, has_permission
from ..dependencies import get_current_user_role
from ..errors import AuthenticationError, AuthorizationError


def require_permission(permission: Permission):
    """
    Dependency factory to require a specific permission.

    Args:
        permission: Required permission

    Returns:
        Dependency function that validates permission
    """
    def check_permission(request: Request) -> None:
        """
        Check if current user has required permission.

        Args:
            request: FastAPI request

        Raises:
            AuthenticationError: If user is not authenticated
            AuthorizationError: If user lacks required permission
        """
        user_role = get_current_user_role(request)

        # Check if user is authenticated (not anonymous)
        if user_role == Role.ANONYMOUS:
            raise AuthenticationError("Authentication required")

        # Check if user has required permission
        if not has_permission(user_role, permission):
            raise AuthorizationError(
                f"Insufficient permissions. Required: {permission.value}"
            )

    return Depends(check_permission)


def require_authenticated():
    """
    Dependency to require authenticated user.

    Returns:
        Dependency function that validates authentication
    """
    def check_authenticated(request: Request) -> None:
        """
        Check if user is authenticated.

        Args:
            request: FastAPI request

        Raises:
            AuthenticationError: If user is not authenticated
        """
        user_role = get_current_user_role(request)

        if user_role == Role.ANONYMOUS:
            raise AuthenticationError("Authentication required")

    return Depends(check_authenticated)


def require_admin():
    """
    Dependency to require admin user.

    Returns:
        Dependency function that validates admin status
    """
    def check_admin(request: Request) -> None:
        """
        Check if user is admin.

        Args:
            request: FastAPI request

        Raises:
            AuthenticationError: If user is not authenticated
            AuthorizationError: If user is not admin
        """
        user_role = get_current_user_role(request)

        if user_role == Role.ANONYMOUS:
            raise AuthenticationError("Authentication required")

        is_admin = getattr(request.state, "is_admin", False)
        if not is_admin:
            raise AuthorizationError("Admin privileges required")

    return Depends(check_admin)
