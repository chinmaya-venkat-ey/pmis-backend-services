"""Routes for the resource_types catalog."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query, status

from app.controllers.resource_type_controller import ResourceTypeController
from app.core.permissions import RESOURCE_TYPES_MANAGE, RESOURCE_TYPES_READ
from app.core.rbac import require_permission
from app.dependencies import get_resource_type_controller
from app.schemas.resource_type import (
    ResourceTypeCreateRequest,
    ResourceTypeResponse,
    ResourceTypeUpdateRequest,
)


router = APIRouter(prefix="/resource-types", tags=["resource_types"])


@router.get(
    "/list",
    response_model=List[ResourceTypeResponse],
    summary="List resource types",
    description="Returns active resource types (e.g. used by activity-resource picker). Requires resource_types:read.",
    dependencies=[Depends(require_permission(RESOURCE_TYPES_READ))],
)
def list_resource_types(
    include_inactive: bool = Query(False, description="Include deactivated rows"),
    controller: ResourceTypeController = Depends(get_resource_type_controller),
) -> List[ResourceTypeResponse]:
    return controller.list_(include_inactive=include_inactive)


@router.get(
    "/{rt_id}/details",
    response_model=ResourceTypeResponse,
    summary="Get resource type details",
    dependencies=[Depends(require_permission(RESOURCE_TYPES_READ))],
    responses={404: {"description": "ResourceType not found"}},
)
def get_resource_type_details(
    rt_id: str,
    controller: ResourceTypeController = Depends(get_resource_type_controller),
) -> ResourceTypeResponse:
    return controller.get_details(rt_id)


@router.post(
    "/create",
    response_model=ResourceTypeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a resource type",
    description="Creates a resource type. `code` must be unique. Requires resource_types:manage.",
    dependencies=[Depends(require_permission(RESOURCE_TYPES_MANAGE))],
    responses={409: {"description": "ResourceType code already exists"}},
)
def create_resource_type(
    payload: ResourceTypeCreateRequest,
    controller: ResourceTypeController = Depends(get_resource_type_controller),
) -> ResourceTypeResponse:
    return controller.create(payload)


@router.patch(
    "/{rt_id}/update",
    response_model=ResourceTypeResponse,
    summary="Update a resource type",
    dependencies=[Depends(require_permission(RESOURCE_TYPES_MANAGE))],
    responses={404: {"description": "ResourceType not found"}},
)
def update_resource_type(
    rt_id: str,
    payload: ResourceTypeUpdateRequest,
    controller: ResourceTypeController = Depends(get_resource_type_controller),
) -> ResourceTypeResponse:
    return controller.update(rt_id, payload)


@router.delete(
    "/{rt_id}/delete",
    response_model=ResourceTypeResponse,
    summary="Delete (deactivate) a resource type",
    dependencies=[Depends(require_permission(RESOURCE_TYPES_MANAGE))],
    responses={404: {"description": "ResourceType not found"}},
)
def delete_resource_type(
    rt_id: str,
    controller: ResourceTypeController = Depends(get_resource_type_controller),
) -> ResourceTypeResponse:
    return controller.delete(rt_id)


@router.post(
    "/{rt_id}/restore",
    response_model=ResourceTypeResponse,
    summary="Restore (reactivate) a resource type",
    dependencies=[Depends(require_permission(RESOURCE_TYPES_MANAGE))],
    responses={404: {"description": "ResourceType not found"}},
)
def restore_resource_type(
    rt_id: str,
    controller: ResourceTypeController = Depends(get_resource_type_controller),
) -> ResourceTypeResponse:
    return controller.restore(rt_id)
