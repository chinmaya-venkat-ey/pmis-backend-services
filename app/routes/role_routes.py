"""Routes for /user/roles/* (role CRUD + role-permission management)."""
from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query, status

from app.controllers.role_controller import RoleController
from app.core.permissions import (
    PERMISSIONS_READ,
    ROLES_CREATE,
    ROLES_DELETE,
    ROLES_READ,
    ROLES_UPDATE,
)
from app.core.rbac import require_permission
from app.dependencies import get_current_user_id, get_role_controller
from app.schemas.role import (
    RoleCreateRequest,
    RolePermissionsReplaceRequest,
    RolePermissionsResponse,
    RoleResponse,
    RoleUpdateRequest,
)


router = APIRouter(prefix="/roles", tags=["roles"])


@router.get(
    "",
    summary="List all roles",
    dependencies=[Depends(require_permission(ROLES_READ))],
)
def list_roles(
    controller: Annotated[RoleController, Depends(get_role_controller)],
    offset: int = Query(1, ge=1),
    page_size: Optional[int] = Query(None, ge=1, alias="pageSize"),
):
    all_roles = controller.list_()
    total = len(all_roles)
    if page_size is None:
        page = all_roles  # no cap -> return every role
    else:
        zero_based = max(0, offset - 1)
        page = all_roles[zero_based * page_size : zero_based * page_size + page_size]
    return {"items": page, "total": total, "offset": offset,
            "pageSize": page_size if page_size is not None else total}


@router.post(
    "/create",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a role",
    dependencies=[Depends(require_permission(ROLES_CREATE))],
    responses={409: {"description": "Role name already exists"}},
)
def create_role(
    payload: RoleCreateRequest,
    controller: Annotated[RoleController, Depends(get_role_controller)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
):
    return controller.create(payload, caller_user_id=caller_user_id)


@router.get(
    "/{role_id}",
    response_model=RoleResponse,
    summary="Get role details",
    dependencies=[Depends(require_permission(ROLES_READ))],
    responses={404: {"description": "Role not found"}},
)
def get_role(
    role_id: int,
    controller: Annotated[RoleController, Depends(get_role_controller)],
):
    return controller.get_details(role_id)


@router.patch(
    "/{role_id}",
    response_model=RoleResponse,
    summary="Update a role",
    dependencies=[Depends(require_permission(ROLES_UPDATE))],
)
def update_role(
    role_id: int,
    payload: RoleUpdateRequest,
    controller: Annotated[RoleController, Depends(get_role_controller)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
):
    return controller.update(role_id, payload, caller_user_id=caller_user_id)


@router.delete(
    "/{role_id}",
    response_model=RoleResponse,
    summary="Delete a role",
    dependencies=[Depends(require_permission(ROLES_DELETE))],
    responses={
        403: {"description": "Role is locked/builtin and cannot be deleted"},
        409: {"description": "Cannot delete a builtin role"},
    },
)
def delete_role(
    role_id: int,
    controller: Annotated[RoleController, Depends(get_role_controller)],
):
    return controller.delete(role_id)


# ---------------------------------------------------------------------------
# Role-permission grants
# ---------------------------------------------------------------------------

@router.get(
    "/{role_id}/permissions",
    response_model=RolePermissionsResponse,
    summary="List the permission codes a role holds",
    dependencies=[Depends(require_permission(PERMISSIONS_READ))],
)
def list_role_permissions(
    role_id: int,
    controller: Annotated[RoleController, Depends(get_role_controller)],
):
    return controller.list_role_permissions(role_id)


@router.put(
    "/{role_id}/permissions",
    response_model=RolePermissionsResponse,
    summary="Replace the entire permission set on a role",
    dependencies=[Depends(require_permission(ROLES_UPDATE))],
    responses={409: {"description": "Cannot grant users:grant_superadmin to non-super_admin role"}},
)
def replace_role_permissions(
    role_id: int,
    payload: RolePermissionsReplaceRequest,
    controller: Annotated[RoleController, Depends(get_role_controller)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
):
    return controller.replace_role_permissions(
        role_id, payload, caller_user_id=caller_user_id,
    )


@router.post(
    "/{role_id}/permissions/{code}",
    response_model=RolePermissionsResponse,
    summary="Grant a permission code to a role",
    dependencies=[Depends(require_permission(ROLES_UPDATE))],
)
def grant_role_permission(
    role_id: int,
    code: str,
    controller: Annotated[RoleController, Depends(get_role_controller)],
    caller_user_id: Annotated[str, Depends(get_current_user_id)],
):
    return controller.grant_permission(role_id, code, caller_user_id=caller_user_id)


@router.delete(
    "/{role_id}/permissions/{code}",
    response_model=RolePermissionsResponse,
    summary="Revoke a permission code from a role",
    dependencies=[Depends(require_permission(ROLES_UPDATE))],
)
def revoke_role_permission(
    role_id: int,
    code: str,
    controller: Annotated[RoleController, Depends(get_role_controller)],
):
    return controller.revoke_permission(role_id, code)
