"""FastAPI dependency factories for RBAC enforcement.

Pattern (PLAN.md §2.6):
  @router.get(
      "/divisions/list",
      dependencies=[Depends(require_permission(DIVISIONS_READ))],
  )
  async def list_divisions(...):
      ...

The actual permission check reads `request.state.user_permissions`, which
is hydrated by middleware/auth_middleware.py from the JWT + cross-schema
RBAC tables on every authed request.

WARNING: Duplicated across services per PLAN.md §6.1. Canonical version
will live in services/pmis-user-management/app/core/rbac.py once user-svc
is ported. Keep in sync by hand.
"""
from __future__ import annotations

from typing import Callable, Set

from fastapi import Request

from app.core.errors import ForbiddenError, UnauthorizedError


def _user_id_from_state(request: Request) -> str | None:
    return getattr(request.state, "user_id", None)


def _user_permissions_from_state(request: Request) -> Set[str]:
    perms = getattr(request.state, "user_permissions", None)
    return perms if isinstance(perms, set) else set()


def _is_admin_from_state(request: Request) -> bool:
    return bool(getattr(request.state, "is_admin", False))


def require_authenticated() -> Callable:
    """Dependency factory: 401 if no user is bound to the request."""

    def _checker(request: Request) -> str:
        user_id = _user_id_from_state(request)
        if not user_id:
            raise UnauthorizedError("Authentication required", code="AUTH_REQUIRED")
        return user_id

    return _checker


def require_permission(permission_code: str) -> Callable:
    """Dependency factory: 401 if anonymous, 403 if user lacks `permission_code`.

    Admin users (request.state.is_admin) pass every check — this matches
    the monolith pattern where `admin` role holds every permission code.
    """

    def _checker(request: Request) -> str:
        user_id = _user_id_from_state(request)
        if not user_id:
            raise UnauthorizedError("Authentication required", code="AUTH_REQUIRED")
        if _is_admin_from_state(request):
            return user_id
        if permission_code not in _user_permissions_from_state(request):
            raise ForbiddenError(
                f"Permission denied: {permission_code} required",
                code="PERMISSION_DENIED",
                details={"required": permission_code},
            )
        return user_id

    return _checker


def require_any_permission(*permission_codes: str) -> Callable:
    """Dependency factory: caller needs at least ONE of the codes."""

    if not permission_codes:
        raise ValueError("require_any_permission needs at least one code")

    def _checker(request: Request) -> str:
        user_id = _user_id_from_state(request)
        if not user_id:
            raise UnauthorizedError("Authentication required", code="AUTH_REQUIRED")
        if _is_admin_from_state(request):
            return user_id
        held = _user_permissions_from_state(request)
        if not any(code in held for code in permission_codes):
            raise ForbiddenError(
                "Permission denied: caller lacks all of the required codes",
                code="PERMISSION_DENIED",
                details={"required_any": list(permission_codes)},
            )
        return user_id

    return _checker


def require_admin() -> Callable:
    """Dependency factory: 403 unless the user holds an admin-tier role."""

    def _checker(request: Request) -> str:
        user_id = _user_id_from_state(request)
        if not user_id:
            raise UnauthorizedError("Authentication required", code="AUTH_REQUIRED")
        if not _is_admin_from_state(request):
            raise ForbiddenError(
                "Admin role required",
                code="ADMIN_REQUIRED",
            )
        return user_id

    return _checker
