"""RBAC dependency factories — CANONICAL declaration site.

Two layers:

  - `require_permission(code)` — global gate. Reads request.state.user_permissions
    (flat union of role-derived + direct grants). admins pass every check.

  - `require_project_permission(code)` / `require_org_permission(code)` —
    Doc-41 scope-aware gates. Resolve project_id / vendor_id from the path
    and consult request.state.scoped_permissions (Dict[(kind, id), Set[str]]).
    Global-scope holders pass every scoped check (super_admin pattern).

Anonymous requests have empty permission sets and `user_id=None` → every
gate emits 401.

WARNING: Duplicated across services per PLAN.md §6.1. Keep in sync.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional, Set, Tuple, Union

from fastapi import Request

from app.core.errors import ForbiddenError, UnauthorizedError


# ---------------------------------------------------------------------------
# request.state helpers
# ---------------------------------------------------------------------------

AUTH_REQUIRED_MESSAGE = "Authentication required"

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


# ---------------------------------------------------------------------------
# Global gates
# ---------------------------------------------------------------------------

def require_authenticated() -> Callable:
    """401 if no user is bound to the request."""

    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="AUTH_REQUIRED")
        return uid

    return _checker


def require_permission(permission_code: Union[str, object]) -> Callable:
    """401 if anonymous, 403 if user lacks `permission_code`.

    `permission_code` can be a string or any object with a `.value` attribute
    (legacy enum compat).
    """
    code: str = getattr(permission_code, "value", permission_code)  # type: ignore[assignment]

    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="AUTH_REQUIRED")
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
    """Caller passes if they hold AT LEAST ONE of the codes."""
    if not permission_codes:
        raise ValueError("require_any_permission needs at least one code")
    codes = tuple(getattr(p, "value", p) for p in permission_codes)

    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="AUTH_REQUIRED")
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
    """403 unless caller holds an admin-tier role (admin or super_admin)."""

    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="AUTH_REQUIRED")
        if not _is_admin(request):
            raise ForbiddenError("Admin role required", code="ADMIN_REQUIRED")
        return uid

    return _checker


# ---------------------------------------------------------------------------
# Doc-41 scope-aware gates
# ---------------------------------------------------------------------------

_PROJECT_PATH_PARAM_KEYS = ("project_uuid", "project_id", "projectId")
_ORG_PATH_PARAM_KEYS = ("vendor_id", "vendor_uuid", "organization_id")


def _resolve_project_id_from_path(request: Request) -> Optional[str]:
    """Pull project_id out of the request path."""
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
    """True iff caller holds `code` at `scope_key` OR globally.

    Admins pass automatically.

    Round-8 scope-bleed fix: the previous flat-`user_permissions` fallback
    let a code scoped to project P satisfy checks on project Q (because
    effective_permissions_for_user unions scoped codes into a flat set).
    Removed. A caller now passes the gate iff they hold the code at the
    requested scope OR at global scope.
    """
    if _is_admin(request):
        return True
    scoped = _scoped_permissions(request)
    if code in scoped.get(("global", None), set()):
        return True
    return code in scoped.get(scope_key, set())


def require_project_permission(permission_code: Union[str, object]) -> Callable:
    """Gate `permission_code` against the project_id in the request path."""
    code: str = getattr(permission_code, "value", permission_code)  # type: ignore[assignment]

    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="AUTH_REQUIRED")
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
    """Gate `permission_code` against the vendor_id (organization) in the path."""
    code: str = getattr(permission_code, "value", permission_code)  # type: ignore[assignment]

    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="AUTH_REQUIRED")
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
# ---------------------------------------------------------------------------

def assert_field_writes_allowed(
    request: Request,
    *,
    field_codes: dict[str, str],
    touched_fields: set[str],
    scope_key: Optional[Tuple[str, Optional[str]]] = None,
) -> None:
    """Raise ForbiddenError if the caller lacks any required field-level code.

    Parameters:
      - request: the FastAPI Request (carries scoped_permissions / is_admin).
      - field_codes: the `{field_name: permission_code}` map for the resource
                     (e.g. `PROJECT_FIELD_CODES` from app.core.permissions).
      - touched_fields: the set of fields the request body is setting
                        (typically `payload.model_dump(exclude_unset=True).keys()`).
      - scope_key: `("project", project_id)` for project-domain resources, or
                   `("global", None)` / None for global resources (users).
                   None means "global-only check".

    Behaviour:
      - Anonymous → UnauthorizedError (consistent with require_* deps).
      - Admin/super_admin → pass (no field-level checks).
      - Otherwise: for each touched field, look up its code in `field_codes`
                   and verify the caller holds it (scoped OR globally).
      - On any miss → 403 with details={"missing": [<code>, ...], "fields": [<field>, ...]}.
      - Fields not present in `field_codes` are ignored (callers should pass
        only persistent-write fields). The service layer is responsible for
        rejecting unknown fields at the pydantic boundary already.
    """
    uid = _user_id(request)
    if not uid:
        raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="AUTH_REQUIRED")
    if _is_admin(request):
        return

    # Round-8 scope-bleed fix: removed the flat-`user_permissions` fallback
    # that previously let a code scoped to project P authorize edits on
    # project Q. Match the tightened `_has_scoped_permission`.
    target_scope = scope_key or ("global", None)
    held_scoped = _scoped_permissions(request).get(target_scope, set())
    held_global = _scoped_permissions(request).get(("global", None), set())

    missing_codes: list[str] = []
    missing_fields: list[str] = []
    for field in touched_fields:
        code = field_codes.get(field)
        if code is None:
            # Field doesn't gate behind a code (likely a sub-resource handled
            # separately or a field we deliberately don't gate). Skip.
            continue
        if code in held_scoped or code in held_global:
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


def assert_action_allowed(
    request: Request,
    *,
    code: str,
    scope_key: Optional[Tuple[str, Optional[str]]] = None,
) -> None:
    """Single-action scoped check (round-8). Used when the route can't
    extract the scope id from the URL (entity-ID-shaped routes like
    ``DELETE /project/milestones/{id}/delete``). The service loads the row,
    then asks this helper whether the caller holds ``code`` at the row's
    parent-project scope. Mirror of ``assert_field_writes_allowed`` but for
    a single action code.
    """
    uid = _user_id(request)
    if not uid:
        raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="AUTH_REQUIRED")
    if _is_admin(request):
        return
    target_scope = scope_key or ("global", None)
    scoped = _scoped_permissions(request)
    if code in scoped.get(target_scope, set()):
        return
    if code in scoped.get(("global", None), set()):
        return
    raise ForbiddenError(
        f"Permission denied: {code} required at "
        f"{target_scope[0]} {target_scope[1] or 'GLOBAL'}",
        code="PERMISSION_DENIED",
        details={
            "required": code,
            "scope": target_scope[0],
            "scope_id": target_scope[1],
        },
    )
