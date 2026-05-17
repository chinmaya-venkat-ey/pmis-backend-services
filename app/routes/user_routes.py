"""Routes for /user/users/* (CRUD + check-login + per-user permissions + projects).

Round-7 changes (field-level + Doc-44 tightening):
  - PATCH /update: gated by `require_authenticated()`; service-layer field-walker
    enforces `users:update:<field>` per touched field for non-self callers.
  - PATCH /password/update: SELF-ONLY (round-7 Q2). The dedicated admin-driven
    reset path is gone — admins assist users via the self-service forgot-password
    flow when needed.
  - DELETE /delete + POST /restore: `USERS_DELETE_ALL` (admin) OR
    `USERS_DELETE_VENDOR` (org_admin scoped to target's vendor).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status

from app.controllers.user_controller import UserController
from app.core.permissions import (
    PERMISSIONS_READ,
    RBAC_ASSIGN,
    USERS_CREATE,
    USERS_DELETE_ALL,
    USERS_DELETE_VENDOR,
    USERS_READ,
    USERS_READ_ALL,
)
from app.core.rbac import (
    require_any_permission,
    require_authenticated,
    require_permission,
)
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


@router.post(
    "/create",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user",
    dependencies=[Depends(require_permission(USERS_CREATE))],
    responses={409: {"description": "Login or email already in use"}},
)
def create_user(
    payload: UserCreateRequest,
    controller: UserController = Depends(get_user_controller),
    caller_user_id: str = Depends(get_current_user_id),
    caller_is_admin: bool = Depends(get_caller_is_admin),
):
    return controller.create(
        payload, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


@router.get(
    "/list",
    summary="List users",
    description=(
        "Doc-46: non-admin callers see ONLY users in their own vendor, and the "
        "admin-tier (admin/super_admin) is excluded from results."
    ),
    dependencies=[Depends(require_permission(USERS_READ_ALL))],
)
def list_users(
    request: Request,
    offset: int = Query(1, ge=1, description="1-based page offset"),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, max_length=16),
    include_deleted: bool = Query(False),
    controller: UserController = Depends(get_user_controller),
    caller_is_admin: bool = Depends(get_caller_is_admin),
):
    caller_user = controller.user_service.repo.get_by_id(
        getattr(request.state, "user_id", "") or ""
    )
    caller_vendor_id = caller_user.vendor_id if caller_user else None
    return controller.list_(
        offset=offset, page_size=page_size,
        status=status, include_deleted=include_deleted,
        caller_vendor_id=caller_vendor_id, caller_is_admin=caller_is_admin,
    )


@router.get(
    "/check-login",
    response_model=UserCheckLoginResponse,
    summary="Check if a login is available",
    dependencies=[Depends(require_authenticated())],
)
def check_login(
    login: str = Query(..., min_length=1, max_length=64),
    controller: UserController = Depends(get_user_controller),
):
    return controller.check_login(login)


@router.get(
    "/{user_id}/details",
    response_model=UserResponse,
    summary="Get user details",
    dependencies=[Depends(require_permission(USERS_READ))],
    responses={404: {"description": "User not found"}},
)
def get_user(
    user_id: str,
    controller: UserController = Depends(get_user_controller),
):
    return controller.get_details(user_id)


@router.patch(
    "/{user_id}/update",
    response_model=UserResponse,
    summary="Update a user (field-level RBAC; self-edit or admin/super_admin)",
    description=(
        "Doc-44 Flow 1 + round-7 field-level model. Non-admin callers must hold "
        "`users:update:<field>` for every field they're editing. Self-edits always "
        "pass the per-field gate."
    ),
    dependencies=[Depends(require_authenticated())],
    responses={
        403: {"description": "Caller cannot modify this target or lacks field permissions"},
        404: {"description": "User not found"},
        409: {"description": "Email already in use"},
    },
)
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    request: Request,
    controller: UserController = Depends(get_user_controller),
    caller_user_id: str = Depends(get_current_user_id),
    caller_is_admin: bool = Depends(get_caller_is_admin),
):
    return controller.update(
        user_id, payload, request=request,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


@router.patch(
    "/{user_id}/password/update",
    response_model=UserResponse,
    summary="Change YOUR OWN password (self-only)",
    description=(
        "Doc-44 Flow 2 + round-7 Q2. Only the account owner can change their "
        "password here. Forgotten / locked-out users use POST /user/users/forgot-password "
        "to receive a single-use reset token via email/SMS."
    ),
    dependencies=[Depends(require_authenticated())],
    responses={403: {"description": "Another user's password cannot be changed"}},
)
def update_user_password(
    user_id: str,
    payload: UserPasswordUpdateRequest,
    controller: UserController = Depends(get_user_controller),
    caller_user_id: str = Depends(get_current_user_id),
):
    return controller.update_password(
        user_id, payload, caller_user_id=caller_user_id,
    )


@router.delete(
    "/{user_id}/delete",
    response_model=UserResponse,
    summary="Delete (soft-delete) a user",
    description=(
        "Doc-44 Flow 3: admin/super_admin globally, OR org_admin holding "
        "`users:delete_vendor` scoped to the target's vendor."
    ),
    dependencies=[Depends(require_any_permission(USERS_DELETE_ALL, USERS_DELETE_VENDOR))],
    responses={409: {"description": "Cannot delete the only remaining super_admin"}},
)
def delete_user(
    user_id: str,
    request: Request,
    controller: UserController = Depends(get_user_controller),
    caller_user_id: str = Depends(get_current_user_id),
    caller_is_admin: bool = Depends(get_caller_is_admin),
):
    return controller.delete(
        user_id, request=request,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


@router.post(
    "/{user_id}/restore",
    response_model=UserResponse,
    summary="Restore a soft-deleted user",
    dependencies=[Depends(require_any_permission(USERS_DELETE_ALL, USERS_DELETE_VENDOR))],
)
def restore_user(
    user_id: str,
    request: Request,
    controller: UserController = Depends(get_user_controller),
    caller_user_id: str = Depends(get_current_user_id),
    caller_is_admin: bool = Depends(get_caller_is_admin),
):
    return controller.restore(
        user_id, request=request,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


# ---------------------------------------------------------------------------
# Per-user effective permissions
# ---------------------------------------------------------------------------

@router.get(
    "/me/permissions/list",
    response_model=EffectivePermissionsResponse,
    summary="Current user's effective permissions",
    dependencies=[Depends(require_authenticated())],
)
def my_permissions(
    controller: UserController = Depends(get_user_controller),
    caller_user_id: str = Depends(get_current_user_id),
):
    return controller.list_permissions(caller_user_id)


@router.get(
    "/{user_id}/permissions/list",
    response_model=EffectivePermissionsResponse,
    summary="Get a user's effective permissions",
    dependencies=[Depends(require_permission(PERMISSIONS_READ))],
)
def user_permissions(
    user_id: str,
    controller: UserController = Depends(get_user_controller),
):
    return controller.list_permissions(user_id)


@router.post(
    "/{user_id}/permissions/{code}/grant",
    response_model=EffectivePermissionsResponse,
    summary="Grant a direct permission to a user (additive)",
    dependencies=[Depends(require_permission(RBAC_ASSIGN))],
)
def grant_user_permission(
    user_id: str,
    code: str,
    controller: UserController = Depends(get_user_controller),
    caller_user_id: str = Depends(get_current_user_id),
):
    return controller.grant_permission(user_id, code, caller_user_id=caller_user_id)


@router.delete(
    "/{user_id}/permissions/{code}/revoke",
    response_model=EffectivePermissionsResponse,
    summary="Revoke a direct permission from a user",
    dependencies=[Depends(require_permission(RBAC_ASSIGN))],
)
def revoke_user_permission(
    user_id: str,
    code: str,
    controller: UserController = Depends(get_user_controller),
):
    return controller.revoke_permission(user_id, code)


# ---------------------------------------------------------------------------
# user -> projects sub-listing
# ---------------------------------------------------------------------------

@router.get(
    "/{user_id}/projects/list",
    response_model=UserProjectsResponse,
    summary="List projects a user is assigned to",
    dependencies=[Depends(require_permission(USERS_READ))],
)
def list_user_projects(
    user_id: str,
    controller: UserController = Depends(get_user_controller),
):
    return controller.list_projects(user_id)
