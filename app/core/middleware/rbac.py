"""
RBAC middleware: permission-based authorization.

Doc 21 part B reworks this from in-memory ``Role -> Permission`` lookup
to a string-coded, DB-backed check. Routes pass a permission *code*
(e.g. ``"projects:create"``) to ``require_permission(...)``; the
dependency consults ``request.state.user_permissions`` — a Set[str]
populated once per request by ``AuthenticationMiddleware`` after JWT
decode.

Anonymous (no token, revoked token, decode failure) requests have an
empty permissions set → every ``require_permission`` rejects with 401.
"""
from typing import Optional, Set, Union
from fastapi import Depends, Request

from ..errors import AuthenticationError, AuthorizationError


def _user_permissions(request: Request) -> Set[str]:
    return getattr(request.state, "user_permissions", set()) or set()


def _user_id(request: Request) -> Optional[str]:
    """Doc 26: returns the caller's UUID (was int pre-doc-26)."""
    return getattr(request.state, "user_id", None)


def require_permission(permission: Union[str, "object"]):
    """
    Dependency factory: require the caller to hold a specific permission.

    ``permission`` is the canonical string code (recommended). The legacy
    ``Permission`` enum from ``app.core.rbac`` is also accepted to keep
    in-flight route imports working — ``.value`` is read off enum members.
    """
    code = getattr(permission, "value", permission)

    def check_permission(request: Request) -> None:
        if _user_id(request) is None:
            raise AuthenticationError("Authentication required")
        if code not in _user_permissions(request):
            raise AuthorizationError(
                f"Insufficient permissions. Required: {code}"
            )

    return Depends(check_permission)


def require_authenticated():
    """Dependency: require an authenticated (non-anonymous) caller."""

    def check_authenticated(request: Request) -> None:
        if _user_id(request) is None:
            raise AuthenticationError("Authentication required")

    return Depends(check_authenticated)


def require_admin():
    """Dependency: require the caller to be a superuser (admin role)."""

    def check_admin(request: Request) -> None:
        if _user_id(request) is None:
            raise AuthenticationError("Authentication required")
        if not getattr(request.state, "is_admin", False):
            raise AuthorizationError("Admin privileges required")

    return Depends(check_admin)
