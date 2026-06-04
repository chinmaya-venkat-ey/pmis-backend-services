"""RBAC dependency factories for pmis-project-management.

Duplicates the canonical declaration in
services/pmis-user-management/app/core/rbac.py. Keep in sync.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional, Set, Tuple, Union

from fastapi import Request

from app.core.errors import ForbiddenError, UnauthorizedError


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


def require_authenticated() -> Callable:
    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="auth_required")
        return uid  # NOSONAR(S3516): FastAPI DI — uid is consumed by downstream handlers

    return _checker


def require_permission(permission_code: Union[str, object]) -> Callable:
    code: str = getattr(permission_code, "value", permission_code)  # type: ignore[assignment]

    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="auth_required")
        # A1 (2026-06-02 audit): admin/super_admin no longer short-circuit
        # here. They must explicitly hold the code via r005's grant migration.
        if code not in _user_permissions(request):
            raise ForbiddenError(
                f"Permission denied: {code} required",
                code="permission_denied",
                details={"required": code},
            )
        return uid  # NOSONAR(S3516): FastAPI DI — uid is consumed by downstream handlers

    return _checker


def require_any_permission(*permission_codes: Union[str, object]) -> Callable:
    if not permission_codes:
        raise ValueError("require_any_permission needs at least one code")
    codes = tuple(getattr(p, "value", p) for p in permission_codes)

    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="auth_required")
        # A1: no admin bypass.
        held = _user_permissions(request)
        if not any(c in held for c in codes):
            raise ForbiddenError(
                "Permission denied: caller lacks all of the required codes",
                code="permission_denied",
                details={"required_any": list(codes)},
            )
        return uid  # NOSONAR(S3516): FastAPI DI — uid is consumed by downstream handlers

    return _checker


def require_admin() -> Callable:
    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="auth_required")
        if not _is_admin(request):
            raise ForbiddenError("Admin role required", code="admin_required")
        return uid  # NOSONAR(S3516): FastAPI DI — uid is consumed by downstream handlers

    return _checker


_PROJECT_PATH_PARAM_KEYS = ("project_uuid", "project_id", "projectId")
_ORG_PATH_PARAM_KEYS = ("vendor_id", "vendor_uuid", "organization_id")

# M/A/T/S ancestor-resolver keys. When the path carries only one of
# these (e.g. ``/milestones/{milestone_id}``), join back to the owning
# project_id via SQL. Mirrors the monolith's ancestor walk so the
# id-scoped routes pass ``require_project_permission`` checks.
_ANCESTOR_PATH_PARAM_KEYS = (
    "milestone_id", "milestoneId",
    "activity_id", "activityId",
    "task_id", "taskId",
    "subtask_id", "subtaskId",
    # nested-subtask create routes use parent_subtask_id; resolution is
    # the same as subtask_id (subtasks.task_id always points at the ROOT
    # task — see app/models/subtask.py).
    "parent_subtask_id", "parentSubtaskId",
)


def _resolve_project_id_from_path(request: Request) -> Optional[str]:
    """Pull the project_id from the URL.

    Resolution order (cached on request.state so repeated checks pay once):
      1. Direct project param (``project_uuid`` / ``project_id``).
      2. Ancestor lookup via DB: ``milestone_id`` / ``activity_id`` /
         ``task_id`` / ``subtask_id`` / ``parent_subtask_id``.
    """
    cached = getattr(request.state, "_resolved_project_id", None)
    if cached is not None:
        return cached or None  # cached "" means "no resolution"

    path_params = getattr(request, "path_params", {}) or {}

    # Direct.
    for key in _PROJECT_PATH_PARAM_KEYS:
        v = path_params.get(key)
        if v:
            request.state._resolved_project_id = v
            return v

    # Ancestor lookup.
    for key in _ANCESTOR_PATH_PARAM_KEYS:
        v = path_params.get(key)
        if not v:
            continue
        project_id = _ancestor_project_id(key, v)
        if project_id:
            request.state._resolved_project_id = project_id
            return project_id

    request.state._resolved_project_id = ""
    return None


def _ancestor_project_id(param_key: str, value: str) -> Optional[str]:
    """Walk M/A/T/S → project via the DB.

      milestone_id → milestones.project_id
      activity_id  → activities.project_id  (denormalised on the row)
      task_id      → tasks.project_id        (denormalised)
      subtask_id   → subtasks.project_id     (denormalised)

    parent_subtask_id resolves identically to subtask_id (subtasks
    carry project_id directly).
    """
    from sqlalchemy import text

    from app.db import SessionLocal

    base = param_key.replace("Id", "_id")  # camelCase variants → snake
    if base == "parent_subtask_id":
        base = "subtask_id"

    sql_by_key = {
        "milestone_id": "SELECT project_id FROM project.milestones WHERE id = :id",
        "activity_id":  "SELECT project_id FROM project.activities WHERE id = :id",
        "task_id":      "SELECT project_id FROM project.tasks      WHERE id = :id",
        "subtask_id":   "SELECT project_id FROM project.subtasks   WHERE id = :id",
    }
    stmt = sql_by_key.get(base)
    if stmt is None:
        return None

    db = SessionLocal()
    try:
        row = db.execute(text(stmt), {"id": value}).first()
        return row[0] if row else None
    finally:
        db.close()


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
    """A1 (2026-06-02 audit): admins no longer pass automatically. They must
    explicitly hold the code at the requested scope OR at global scope, same
    as any other caller. r005's grant migration ensures admin/super_admin
    do hold every catalog code globally.

    Round-8: removed the flat-set fallback that let a perm scoped to
    project P satisfy checks on project Q. A caller passes the gate iff
    they hold the code at the requested scope OR globally."""
    scoped = _scoped_permissions(request)
    if code in scoped.get(("global", None), set()):
        return True
    return code in scoped.get(scope_key, set())


def require_project_permission(permission_code: Union[str, object]) -> Callable:
    code: str = getattr(permission_code, "value", permission_code)  # type: ignore[assignment]

    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="auth_required")
        # A1 (2026-06-02 audit): no admin short-circuit. Project-id
        # resolution always runs; admin/super_admin must explicitly hold
        # the code at the resolved project scope or globally.
        project_id = _resolve_project_id_from_path(request)
        if project_id is None:
            raise ForbiddenError(
                f"require_project_permission({code}) used on a route "
                f"without a resolvable project_id",
                code="route_misconfigured",
            )
        if not _has_scoped_permission(request, code, ("project", project_id)):
            raise ForbiddenError(
                f"Permission denied: {code} required on project {project_id}",
                code="permission_denied",
                details={"required": code, "scope": "project", "scope_id": project_id},
            )
        return uid  # NOSONAR(S3516): FastAPI DI — uid is consumed by downstream handlers

    return _checker


def require_org_permission(permission_code: Union[str, object]) -> Callable:
    code: str = getattr(permission_code, "value", permission_code)  # type: ignore[assignment]

    def _checker(request: Request) -> str:
        uid = _user_id(request)
        if not uid:
            raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="auth_required")
        org_id = _resolve_org_id_from_path(request)
        if org_id is None:
            raise ForbiddenError(
                f"require_org_permission({code}) used on a route "
                f"without a vendor_id / organization_id path param",
                code="route_misconfigured",
            )
        if not _has_scoped_permission(request, code, ("org", org_id)):
            raise ForbiddenError(
                f"Permission denied: {code} required on organization {org_id}",
                code="permission_denied",
                details={"required": code, "scope": "org", "scope_id": org_id},
            )
        return uid  # NOSONAR(S3516): FastAPI DI — uid is consumed by downstream handlers

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

    Round-8 scope-bleed fix: the previous `held_flat` fallback let scoped
    perms from project P satisfy field-writes on project Q (because
    effective_permissions_for_user unions scoped codes into a flat set).
    Removed. A caller now passes the field gate iff they hold the code at
    the requested scope OR at global scope. A1 (2026-06-02 audit) removed
    the blanket admin bypass; admins now pass only because r005 grants
    them every catalog code explicitly.

    See user-svc canonical declaration for full docstring.
    """
    uid = _user_id(request)
    if not uid:
        raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="auth_required")
    # A1 (2026-06-02 audit): admins must hold each field code explicitly
    # (granted by r005). No short-circuit here.

    target_scope = scope_key or ("global", None)
    held_scoped = _scoped_permissions(request).get(target_scope, set())
    held_global = _scoped_permissions(request).get(("global", None), set())

    missing_codes: list[str] = []
    missing_fields: list[str] = []
    for field in touched_fields:
        code = field_codes.get(field)
        if code is None:
            continue
        if code in held_scoped or code in held_global:
            continue
        missing_codes.append(code)
        missing_fields.append(field)

    if missing_codes:
        raise ForbiddenError(
            f"Permission denied: missing {len(missing_codes)} field-level "
            f"permission(s) for this update",
            code="permission_denied",
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
    """Single-action scoped check (round-8).

    Used when the route can't extract the scope id from the URL (entity-ID-
    shaped routes like ``DELETE /project/milestones/{id}/delete``). The
    service loads the row, then asks this helper whether the caller holds
    ``code`` at the row's parent-project scope (or globally). Mirror of
    ``assert_field_writes_allowed`` but for a single action code.

    Anonymous -> 401. Otherwise the caller must hold ``code`` at
    ``scope_key`` OR at ``("global", None)``. Admins pass only via the
    explicit r005 grant of every catalog code — A1 (2026-06-02) removed
    the blanket bypass. Scoped codes from OTHER scopes (the previous
    flat-set bleed) do NOT authorize.
    """
    uid = _user_id(request)
    if not uid:
        raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="auth_required")
    # A1 (2026-06-02 audit): no admin short-circuit; admins hold codes explicitly.
    target_scope = scope_key or ("global", None)
    scoped = _scoped_permissions(request)
    if code in scoped.get(target_scope, set()):
        return
    if code in scoped.get(("global", None), set()):
        return
    raise ForbiddenError(
        f"Permission denied: {code} required at "
        f"{target_scope[0]} {target_scope[1] or 'GLOBAL'}",
        code="permission_denied",
        details={
            "required": code,
            "scope": target_scope[0],
            "scope_id": target_scope[1],
        },
    )
