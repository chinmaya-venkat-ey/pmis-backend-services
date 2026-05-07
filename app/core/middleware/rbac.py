"""
RBAC middleware: permission-based authorization (doc 21B + doc 41 scope).

Two layers:

  * ``require_permission(code)`` — global gate. Reads
    ``request.state.user_permissions`` (the flat union populated by
    ``AuthenticationMiddleware``). Backwards-compatible with every
    pre-doc-41 route.

  * ``require_project_permission(code)`` /
    ``require_org_permission(code)`` — scope-aware gates (doc 41).
    Resolve the project_id / org_id from the request path, then
    consult ``request.state.scoped_permissions`` (Dict[(kind, id),
    Set[str]]). A user passes if they hold the code at the matching
    scope **OR** at global scope (global always wins, mirroring how
    super_admin works in any RBAC system).

Anonymous calls have empty permission sets → every gate rejects 401.
"""
from typing import Dict, Optional, Set, Tuple, Union
from fastapi import Depends, Request

from ..errors import AuthenticationError, AuthorizationError


def _user_permissions(request: Request) -> Set[str]:
    return getattr(request.state, "user_permissions", set()) or set()


def _scoped_permissions(
    request: Request,
) -> Dict[Tuple[str, Optional[str]], Set[str]]:
    return getattr(request.state, "scoped_permissions", {}) or {}


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


# ---------------------------------------------------------------------------
# Doc 41 — scope-aware helpers
# ---------------------------------------------------------------------------

# Project-id resolver path-param keys, in priority order. The first one
# matching ``request.path_params`` wins. ``project_uuid`` is the modern
# convention (doc 26+); the older variants stay listed for legacy routes.
_PROJECT_PATH_PARAM_KEYS = ("project_uuid", "project_id", "projectId")


def _resolve_project_id_from_path(request: Request) -> Optional[str]:
    """Pull the project_id out of the URL.

    Returns the first matching path-param value, or ``None`` if none
    of the known keys are present in ``request.path_params``. The
    helper deliberately does NOT do ancestor lookups (milestone →
    project, etc.) — that responsibility belongs in monolith where
    the M-A-T-S models live. User-mgmt only owns the assignment +
    view endpoints, all of which carry project_id directly in their
    path.
    """
    path_params = getattr(request, "path_params", {}) or {}
    for key in _PROJECT_PATH_PARAM_KEYS:
        v = path_params.get(key)
        if v:
            return v
    return None


def _has_scoped_permission(
    request: Request, code: str, scope_key: Tuple[str, Optional[str]],
) -> bool:
    """True iff the user holds ``code`` at ``scope_key`` OR globally.

    Global wins by design: a global super_admin / admin pass every
    scoped check (otherwise super_admin would have to be assigned per
    project, which defeats the purpose). The per-scope bucket layered
    on top of global never *removes* permissions — assignments are
    purely additive in this model.
    """
    scoped = _scoped_permissions(request)
    if code in scoped.get(("global", None), set()):
        return True
    if code in scoped.get(scope_key, set()):
        return True
    # Backwards-compat: legacy ``user_permissions`` flat set may still
    # carry the perm via paths the scope view didn't include.
    return code in _user_permissions(request)


def require_project_permission(permission: Union[str, "object"]):
    """Doc 41 — gate ``permission`` on the project_id in the URL.

    The dependency:
      1. Extracts ``project_uuid`` (or ``project_id``) from the path.
         If the route has no project param, raises 500-style error
         (programmer mistake — caller should have used
         ``require_permission`` instead).
      2. Checks the user holds the code at scope
         ``("project", <project_id>)`` OR at global scope.
      3. 401 if anonymous, 403 if authenticated but unauthorized.
    """
    code = getattr(permission, "value", permission)

    def check(request: Request) -> None:
        if _user_id(request) is None:
            raise AuthenticationError("Authentication required")
        project_id = _resolve_project_id_from_path(request)
        if project_id is None:
            # The route doesn't have a project_id segment — caller
            # shouldn't be using this helper. Surface a 500 so the
            # bug is loud during dev.
            raise AuthorizationError(
                f"require_project_permission({code}) was used on a "
                f"route without a project_uuid path param."
            )
        if not _has_scoped_permission(request, code, ("project", project_id)):
            raise AuthorizationError(
                f"Insufficient permissions. Required: {code} on project {project_id}"
            )

    return Depends(check)


def require_org_permission(permission: Union[str, "object"]):
    """Doc 41 — gate ``permission`` on the vendor_id (= organization)
    in the URL.

    Looks for ``vendor_id`` / ``vendor_uuid`` / ``organization_id`` in
    the path. The user passes if they hold the code at scope
    ``("org", <vendor_id>)`` OR at global scope.
    """
    code = getattr(permission, "value", permission)

    def check(request: Request) -> None:
        if _user_id(request) is None:
            raise AuthenticationError("Authentication required")
        path_params = getattr(request, "path_params", {}) or {}
        org_id = (
            path_params.get("vendor_id")
            or path_params.get("vendor_uuid")
            or path_params.get("organization_id")
        )
        if org_id is None:
            raise AuthorizationError(
                f"require_org_permission({code}) was used on a route "
                f"without a vendor_id / organization_id path param."
            )
        if not _has_scoped_permission(request, code, ("org", org_id)):
            raise AuthorizationError(
                f"Insufficient permissions. Required: {code} on organization {org_id}"
            )

    return Depends(check)
