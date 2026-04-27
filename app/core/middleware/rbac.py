"""RBAC dependencies — ported from the monolith."""
from fastapi import Depends, Request

from ..dependencies import get_current_user_role
from ..errors import AuthenticationError, AuthorizationError
from ..rbac import Permission, Role, has_permission


def require_permission(permission: Permission):
    def check(request: Request) -> None:
        role = get_current_user_role(request)
        if role == Role.ANONYMOUS:
            raise AuthenticationError("Authentication required")
        if not has_permission(role, permission):
            raise AuthorizationError(
                f"Insufficient permissions. Required: {permission.value}"
            )
    return Depends(check)


def require_authenticated():
    def check(request: Request) -> None:
        if get_current_user_role(request) == Role.ANONYMOUS:
            raise AuthenticationError("Authentication required")
    return Depends(check)


def require_admin():
    def check(request: Request) -> None:
        if get_current_user_role(request) == Role.ANONYMOUS:
            raise AuthenticationError("Authentication required")
        if not getattr(request.state, "is_admin", False):
            raise AuthorizationError("Admin privileges required")
    return Depends(check)
