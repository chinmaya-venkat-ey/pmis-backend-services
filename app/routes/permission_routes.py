"""Routes for /user/permissions/* (permission catalog CRUD + grouping)."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status

from app.controllers.permission_controller import PermissionController
from app.core.permissions import PERMISSIONS_MANAGE, PERMISSIONS_READ
from app.core.rbac import require_permission
from app.dependencies import get_permission_controller
from app.schemas.permission import (
    PermissionCreateRequest,
    PermissionResponse,
    PermissionUpdateRequest,
    PermissionsByModuleResponse,
)


router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get(
    "",
    response_model=List[PermissionResponse],
    summary="List all permission codes",
    dependencies=[Depends(require_permission(PERMISSIONS_READ))],
)
def list_permissions(
    controller: PermissionController = Depends(get_permission_controller),
):
    return controller.list_()


@router.get(
    "/by-module",
    response_model=PermissionsByModuleResponse,
    summary="Permissions grouped by domain prefix",
    description="Returns codes grouped by 'users', 'projects', 'masters', etc.",
    dependencies=[Depends(require_permission(PERMISSIONS_READ))],
)
def list_permissions_by_module(
    controller: PermissionController = Depends(get_permission_controller),
):
    return controller.by_module()


@router.get(
    "/{code}",
    response_model=PermissionResponse,
    summary="Get a permission code's details",
    dependencies=[Depends(require_permission(PERMISSIONS_READ))],
    responses={404: {"description": "Permission not found"}},
)
def get_permission(
    code: str,
    controller: PermissionController = Depends(get_permission_controller),
):
    return controller.get_details(code)


@router.post(
    "",
    response_model=PermissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom permission (DEPRECATED — use POST /api/v3/master/permissions/create)",
    dependencies=[Depends(require_permission(PERMISSIONS_MANAGE))],
    responses={409: {"description": "Permission code already exists"}},
)
def create_permission_restful(
    payload: PermissionCreateRequest,
    controller: PermissionController = Depends(get_permission_controller),
):
    return controller.create(payload)


@router.post(
    "/create",
    response_model=PermissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new permission code",
    dependencies=[Depends(require_permission(PERMISSIONS_MANAGE))],
    responses={409: {"description": "Permission code already exists"}},
)
def create_permission(
    payload: PermissionCreateRequest,
    controller: PermissionController = Depends(get_permission_controller),
):
    return controller.create(payload)


@router.patch(
    "/{code}",
    response_model=PermissionResponse,
    summary="Update a permission's name / description",
    dependencies=[Depends(require_permission(PERMISSIONS_MANAGE))],
)
def update_permission(
    code: str,
    payload: PermissionUpdateRequest,
    controller: PermissionController = Depends(get_permission_controller),
):
    return controller.update(code, payload)


@router.delete(
    "/{code}",
    response_model=PermissionResponse,
    summary="Delete a permission code",
    dependencies=[Depends(require_permission(PERMISSIONS_MANAGE))],
    responses={409: {"description": "Cannot delete a builtin permission"}},
)
def delete_permission(
    code: str,
    controller: PermissionController = Depends(get_permission_controller),
):
    return controller.delete(code)
