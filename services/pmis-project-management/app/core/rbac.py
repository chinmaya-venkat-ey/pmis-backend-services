"""RBAC dependency factories for pmis-project-management.

Duplicates the canonical declaration in
services/pmis-user-management/app/core/rbac.py. Keep in sync.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional, Set, Tuple, Union

from fastapi import Request

from app.core.errors import ForbiddenError, UnauthorizedError


def _user_id(request: Request) -> Optional[str]:
    return getattr(request.state, "user_id", None)


def _user_permissions(request: Request) -> Set[str]:
    perms = getattr(request.state, "user_permissions", None)
    return perms if isinstance(perms, set) else set()


def _scoped_permissions(
    request: Request,
) -> Dict[Tuple[str, Optional[str]], Set[str]]:
    scoped = getattr(request.state, "scoped_permissions", None)
    return scoped if isinstance(scoped, dict) else {}


def _is_admin(request: Request) -> bool:
    return bool(getattr(request.state, "is_admin", False))


def require_authenticated() -> Callable:
    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError("Authentication required", code="AUTH_REQUIRED")
        return uid

    return _checker


def require_permission(permission_code: Union[str, object]) -> Callable:
    code: str = getattr(permission_code, "value", permission_code)  # type: ignore[assignment]

    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError("Authentication required", code="AUTH_REQUIRED")
        if _is_admin(request):
            return uid
        if code not in _user_permissions(request):
            raise ForbiddenError(
                f"Permission denied: {code} required",
                code="PERMISSION_DENIED",
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
            raise UnauthorizedError("Authentication required", code="AUTH_REQUIRED")
        if _is_admin(request):
            return uid
        held = _user_permissions(request)
        if not any(c in held for c in codes):
            raise ForbiddenError(
                "Permission denied: caller lacks all of the required codes",
                code="PERMISSION_DENIED",
                details={"required_any": list(codes)},
            )
        return uid

    return _checker


def require_admin() -> Callable:
    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError("Authentication required", code="AUTH_REQUIRED")
        if not _is_admin(request):
            raise ForbiddenError("Admin role required", code="ADMIN_REQUIRED")
        return uid

    return _checker


_PROJECT_PATH_PARAM_KEYS = ("project_uuid", "project_id", "projectId")
_ORG_PATH_PARAM_KEYS = ("vendor_id", "vendor_uuid", "organization_id")


def _resolve_project_id_from_path(request: Request) -> Optional[str]:
    path_params = getattr(request, "path_params", {}) or {}
    for key in _PROJECT_PATH_PARAM_KEYS:
        v = path_params.get(key)
        if v:
            return v
    return None


def _resolve_org_id_from_path(request: Request) -> Optional[str]:
    path_params = getattr(request, "path_params", {}) or {}
    for key in _ORG_PATH_PARAM_KEYS:
        v = path_params.get(key)
        if v:
            return v
    return None


def _has_scoped_permission(
    request: Request, code: str, scope_key: Tuple[str, Optional[str]],
) -> bool:
    if _is_admin(request):
        return True
    scoped = _scoped_permissions(request)
    if code in scoped.get(("global", None), set()):
        return True
    if code in scoped.get(scope_key, set()):
        return True
    return code in _user_permissions(request)


def require_project_permission(permission_code: Union[str, object]) -> Callable:
    code: str = getattr(permission_code, "value", permission_code)  # type: ignore[assignment]

    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError("Authentication required", code="AUTH_REQUIRED")
        project_id = _resolve_project_id_from_path(request)
        if project_id is None:
            raise ForbiddenError(
                f"require_project_permission({code}) used on a route "
                f"without a project_uuid path param",
                code="ROUTE_MISCONFIGURED",
            )
        if not _has_scoped_permission(request, code, ("project", project_id)):
            raise ForbiddenError(
                f"Permission denied: {code} required on project {project_id}",
                code="PERMISSION_DENIED",
                details={"required": code, "scope": "project", "scope_id": project_id},
            )
        return uid

    return _checker


def require_org_permission(permission_code: Union[str, object]) -> Callable:
    code: str = getattr(permission_code, "value", permission_code)  # type: ignore[assignment]

    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError("Authentication required", code="AUTH_REQUIRED")
        org_id = _resolve_org_id_from_path(request)
        if org_id is None:
            raise ForbiddenError(
                f"require_org_permission({code}) used on a route "
                f"without a vendor_id / organization_id path param",
                code="ROUTE_MISCONFIGURED",
            )
        if not _has_scoped_permission(request, code, ("org", org_id)):
            raise ForbiddenError(
                f"Permission denied: {code} required on organization {org_id}",
                code="PERMISSION_DENIED",
                details={"required": code, "scope": "org", "scope_id": org_id},
            )
        return uid

    return _checker


# ---------------------------------------------------------------------------
# Field-level write enforcement (round-7 field-level permission model)
#
# Duplicated from services/pmis-user-management/app/core/rbac.py. Keep in sync.
# ---------------------------------------------------------------------------

def assert_field_writes_allowed(
    request: Request,
    *,
    field_codes: dict[str, str],
    touched_fields: set[str],
    scope_key: Optional[Tuple[str, Optional[str]]] = None,
) -> None:
    """Raise ForbiddenError if the caller lacks any required field-level code.

    See user-svc canonical declaration for full docstring.
    """
    uid = _user_id(request)
    if not uid:
        raise UnauthorizedError("Authentication required", code="AUTH_REQUIRED")
    if _is_admin(request):
        return

    target_scope = scope_key or ("global", None)
    held_scoped = _scoped_permissions(request).get(target_scope, set())
    held_global = _scoped_permissions(request).get(("global", None), set())
    held_flat = _user_permissions(request)

    missing_codes: list[str] = []
    missing_fields: list[str] = []
    for field in touched_fields:
        code = field_codes.get(field)
        if code is None:
            continue
        if code in held_scoped or code in held_global or code in held_flat:
            continue
        missing_codes.append(code)
        missing_fields.append(field)

    if missing_codes:
        raise ForbiddenError(
            f"Permission denied: missing {len(missing_codes)} field-level "
            f"permission(s) for this update",
            code="PERMISSION_DENIED",
            details={
                "missing": sorted(set(missing_codes)),
                "fields": sorted(set(missing_fields)),
                "scope": target_scope[0],
                "scope_id": target_scope[1],
            },
        )
