"""Routes for /users CRUD, permissions, roles, and project listings."""
from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, Depends, Query, Request, status

from app.controllers.user_controller import UserController
from app.core.permissions import (
    PERMISSIONS_MANAGE,
    USERS_CREATE,
    USERS_DELETE_ALL,
    USERS_DELETE_VENDOR,
    USERS_LIST_ALL_ORGS,
    USERS_READ,
    USERS_READ_ALL,
)
from app.core.rbac import require_any_permission, require_authenticated, require_permission
from app.dependencies import (
    get_caller_is_admin,
    get_current_user_id,
    get_user_controller,
)
from app.schemas.permission import EffectivePermissionsResponse
from app.schemas.summaries import UserProjectsResponse
from app.schemas.user import (
    UserCheckLoginResponse,
    UserCreateRequest,
    UserPasswordUpdateRequest,
    UserResponse,
    UserUpdateRequest,
)


router = APIRouter(prefix="/users", tags=["users"])


# ---------------------------------------------------------------------------
# List / collection
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=dict,
    summary="List users",
    dependencies=[Depends(require_any_permission(USERS_READ, USERS_READ_ALL))],
)
def list_users(
    controller: Annotated[UserController, Depends(get_user_controller)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
    offset: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200, alias="pageSize"),
    status: str = Query(None),
    include_deleted: bool = Query(False),
    request: Request = None,
):
    caller_vendor_id = getattr(request.state, "vendor_id", None) if request else None
    held = getattr(request.state, "user_permissions", None) if request else None
    # Bug #213: broad system-wide list view is gated on users:list_all_orgs
    # (r013 grants this only to admin / super_admin). users:read_all retains
    # its individual-record meaning for GET /users/{id} — Org Admin /
    # Project Admin keep that ability but lose the broad list view, falling
    # back to vendor-scoped listings via the #174 vendor_id hydration.
    return controller.list_(
        offset=offset, page_size=page_size,
        status=status, include_deleted=include_deleted,
        caller_vendor_id=caller_vendor_id,
        caller_is_admin=caller_is_admin,
        caller_can_see_all=(USERS_LIST_ALL_ORGS in (held or set())),
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@router.post(
    "/create",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user",
    dependencies=[Depends(require_permission(USERS_CREATE))],
)
def create_user(
    payload: UserCreateRequest,
    controller: Annotated[UserController, Depends(get_user_controller)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
):
    return controller.create(payload, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin)


# ---------------------------------------------------------------------------
# Check-login availability (placed before /{user_id} to avoid path collision)
# ---------------------------------------------------------------------------

@router.get(
    "/check-login",
    response_model=UserCheckLoginResponse,
    summary="Check if a login identifier is available",
    dependencies=[Depends(require_authenticated())],
)
def check_login(
    controller: Annotated[UserController, Depends(get_user_controller)],
    login: str = Query(..., min_length=1, max_length=64),
):
    return controller.check_login(login)


# ---------------------------------------------------------------------------
# Current-user permissions shortcut (must be before /{user_id} routes)
# ---------------------------------------------------------------------------

@router.get(
    "/me/permissions",
    response_model=EffectivePermissionsResponse,
    summary="Current user's effective permissions",
    dependencies=[Depends(require_authenticated())],
)
def my_permissions(
    controller: Annotated[UserController, Depends(get_user_controller)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
):
    return controller.list_permissions(caller_user_id)


# ---------------------------------------------------------------------------
# Single-user CRUD
# ---------------------------------------------------------------------------

@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get a single user by ID",
    dependencies=[Depends(require_any_permission(USERS_READ, USERS_READ_ALL))],
)
def get_user(
    user_id: str,
    controller: Annotated[UserController, Depends(get_user_controller)],
):
    return controller.get_details(user_id)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="Update a user (partial)",
    dependencies=[Depends(require_authenticated())],
)
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    request: Request,
    controller: Annotated[UserController, Depends(get_user_controller)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
):
    return controller.update(
        user_id, payload,
        request=request,
        caller_user_id=caller_user_id,
        caller_is_admin=caller_is_admin,
    )


@router.delete(
    "/{user_id}",
    response_model=UserResponse,
    summary="Soft-delete a user",
    dependencies=[Depends(require_any_permission(USERS_DELETE_ALL, USERS_DELETE_VENDOR))],
)
def delete_user(
    user_id: str,
    request: Request,
    controller: Annotated[UserController, Depends(get_user_controller)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
):
    return controller.delete(
        user_id, request=request,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


@router.patch(
    "/{user_id}/password",
    response_model=UserResponse,
    summary="Change own password (self-only; callers cannot change another user's password)",
    responses={403: {"description": "Caller cannot modify another user's password"}},
)
def update_user_password(
    user_id: str,
    payload: UserPasswordUpdateRequest,
    controller: Annotated[UserController, Depends(get_user_controller)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
):
    return controller.update_password(user_id, payload, caller_user_id=caller_user_id)


@router.post(
    "/{user_id}/restore",
    response_model=UserResponse,
    summary="Restore a soft-deleted user",
    dependencies=[Depends(require_any_permission(USERS_DELETE_ALL, USERS_DELETE_VENDOR))],
)
def restore_user(
    user_id: str,
    request: Request,
    controller: Annotated[UserController, Depends(get_user_controller)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
):
    return controller.restore(
        user_id, request=request,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


# ---------------------------------------------------------------------------
# User permissions (direct grants per-user)
# ---------------------------------------------------------------------------

@router.get(
    "/{user_id}/permissions",
    response_model=EffectivePermissionsResponse,
    summary="Get a specific user's effective permissions",
    dependencies=[Depends(require_any_permission(USERS_READ, USERS_READ_ALL))],
)
def get_user_permissions(
    user_id: str,
    controller: Annotated[UserController, Depends(get_user_controller)],
):
    return controller.list_permissions(user_id)


@router.post(
    "/{user_id}/permissions/{code}",
    response_model=EffectivePermissionsResponse,
    summary="Grant a direct permission to a user",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(PERMISSIONS_MANAGE))],
)
def grant_user_permission(
    user_id: str,
    code: str,
    controller: Annotated[UserController, Depends(get_user_controller)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
):
    return controller.grant_permission(user_id, code, caller_user_id=caller_user_id)


@router.delete(
    "/{user_id}/permissions/{code}",
    response_model=EffectivePermissionsResponse,
    summary="Revoke a direct permission from a user",
    dependencies=[Depends(require_permission(PERMISSIONS_MANAGE))],
)
def revoke_user_permission(
    user_id: str,
    code: str,
    controller: Annotated[UserController, Depends(get_user_controller)],
):
    return controller.revoke_permission(user_id, code)


# ---------------------------------------------------------------------------
# User → projects (read-only cross-schema listing)
# ---------------------------------------------------------------------------
#
# §3.4.2 (2026-06-02 audit): the three legacy ``/{user_id}/roles[/{role_id}]``
# endpoints (list_user_legacy_roles, assign_user_legacy_role,
# unassign_user_legacy_role) were removed. They bypassed
# _assert_caller_can_grant and let any caller holding rbac:assign mint a
# super_admin assignment directly into users.user_roles. Use the scoped
# /users/{id}/role-assignments endpoints instead.
# ---------------------------------------------------------------------------

@router.get(
    "/{user_id}/projects",
    response_model=UserProjectsResponse,
    summary="List projects a user is assigned to",
    dependencies=[Depends(require_any_permission(USERS_READ, USERS_READ_ALL))],
)
def list_user_projects(
    user_id: str,
    controller: Annotated[UserController, Depends(get_user_controller)],
):
    return controller.list_projects(user_id)
