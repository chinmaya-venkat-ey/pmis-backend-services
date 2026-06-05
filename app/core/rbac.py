"""RBAC dependency factories for pmis-file-store.

Duplicated from project-management. Keep in sync across PMIS services.
"""
from __future__ import annotations

from typing import Callable, Optional, Set, Union

from fastapi import Request

from app.core.errors import ForbiddenError, UnauthorizedError


def _user_id(request: Request) -> Optional[str]:
    return getattr(request.state, "user_id", None)


def _user_permissions(request: Request) -> Set[str]:
    perms = getattr(request.state, "user_permissions", None)
    return perms if isinstance(perms, set) else set()


def _is_admin(request: Request) -> bool:
    return bool(getattr(request.state, "is_admin", False))


def require_authenticated() -> Callable:
    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError("Authentication required", code="auth_required")
        return uid
    return _checker


def require_permission(permission_code: Union[str, object]) -> Callable:
    code: str = getattr(permission_code, "value", permission_code)  # type: ignore[assignment]

    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError("Authentication required", code="auth_required")
        # A1 (2026-06-02 audit): no admin short-circuit.
        if code not in _user_permissions(request):
            raise ForbiddenError(
                f"Permission denied: {code} required",
                code="permission_denied",
                details={"required": code},
            )
        return uid
    return _checker


def require_any_permission(*permission_codes: Union[str, object]) -> Callable:
    if not permission_codes:
        raise ValueError("require_any_permission needs at least one code")
    codes = tuple(getattr(p, "value", p) for p in permission_codes)

    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError("Authentication required", code="auth_required")
        # A1: no admin short-circuit.
        held = _user_permissions(request)
        if not any(c in held for c in codes):
            raise ForbiddenError(
                "Permission denied: caller lacks the required permission",
                code="permission_denied",
                details={"required": list(codes)},
            )
        return uid
    return _checker


def require_admin() -> Callable:
    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError("Authentication required", code="auth_required")
        if not _is_admin(request):
            raise ForbiddenError("Admin access required", code="admin_required")
        return uid
    return _checker
