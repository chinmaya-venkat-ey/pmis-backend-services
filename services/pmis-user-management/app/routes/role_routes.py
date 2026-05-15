"""Routes for /user/roles/* (role CRUD + role-permission management)."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status

from app.controllers.role_controller import RoleController
from app.core.permissions import (
    PERMISSIONS_READ,
    ROLES_CREATE,
    ROLES_DELETE,
    ROLES_READ,
    ROLES_UPDATE,
)
from app.core.rbac import require_permission
from app.dependencies import get_role_controller
from app.schemas.role import (
    RoleCreateRequest,
    RolePermissionsReplaceRequest,
    RolePermissionsResponse,
    RoleResponse,
    RoleUpdateRequest,
)


router = APIRouter(prefix="/roles", tags=["roles"])


@router.get(
    "/list",
    response_model=List[RoleResponse],
    summary="List all roles",
    dependencies=[Depends(require_permission(ROLES_READ))],
)
def list_roles(controller: RoleController = Depends(get_role_controller)):
    return controller.list_()


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
    controller: RoleController = Depends(get_role_controller),
):
    return controller.create(payload)


@router.get(
    "/{role_id}/details",
    response_model=RoleResponse,
    summary="Get role details",
    dependencies=[Depends(require_permission(ROLES_READ))],
    responses={404: {"description": "Role not found"}},
)
def get_role(
    role_id: int,
    controller: RoleController = Depends(get_role_controller),
):
    return controller.get_details(role_id)


@router.patch(
    "/{role_id}/update",
    response_model=RoleResponse,
    summary="Update a role",
    dependencies=[Depends(require_permission(ROLES_UPDATE))],
)
def update_role(
    role_id: int,
    payload: RoleUpdateRequest,
    controller: RoleController = Depends(get_role_controller),
):
    return controller.update(role_id, payload)


@router.delete(
    "/{role_id}/delete",
    response_model=RoleResponse,
    summary="Delete a role",
    dependencies=[Depends(require_permission(ROLES_DELETE))],
    responses={409: {"description": "Cannot delete a builtin role"}},
)
def delete_role(
    role_id: int,
    controller: RoleController = Depends(get_role_controller),
):
    return controller.delete(role_id)


# ---------------------------------------------------------------------------
# Role-permission grants
# ---------------------------------------------------------------------------

@router.get(
    "/{role_id}/permissions/list",
    response_model=RolePermissionsResponse,
    summary="List the permission codes a role holds",
    dependencies=[Depends(require_permission(PERMISSIONS_READ))],
)
def list_role_permissions(
    role_id: int,
    controller: RoleController = Depends(get_role_controller),
):
    return controller.list_role_permissions(role_id)


@router.put(
    "/{role_id}/permissions/replace",
    response_model=RolePermissionsResponse,
    summary="Replace the entire permission set on a role",
    dependencies=[Depends(require_permission(ROLES_UPDATE))],
    responses={409: {"description": "Cannot grant users:grant_superadmin to non-super_admin role"}},
)
def replace_role_permissions(
    role_id: int,
    payload: RolePermissionsReplaceRequest,
    controller: RoleController = Depends(get_role_controller),
):
    return controller.replace_role_permissions(role_id, payload)


@router.post(
    "/{role_id}/permissions/{code}/grant",
    response_model=RolePermissionsResponse,
    summary="Grant a permission code to a role",
    dependencies=[Depends(require_permission(ROLES_UPDATE))],
)
def grant_role_permission(
    role_id: int,
    code: str,
    controller: RoleController = Depends(get_role_controller),
):
    return controller.grant_permission(role_id, code)


@router.delete(
    "/{role_id}/permissions/{code}/revoke",
    response_model=RolePermissionsResponse,
    summary="Revoke a permission code from a role",
    dependencies=[Depends(require_permission(ROLES_UPDATE))],
)
def revoke_role_permission(
    role_id: int,
    code: str,
    controller: RoleController = Depends(get_role_controller),
):
    return controller.revoke_permission(role_id, code)
