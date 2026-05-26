"""Routes for the resource_types catalog."""
from __future__ import annotations

from typing import Annotated, List

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


router = APIRouter(prefix="/resource_types", tags=["resource_types"])


@router.get(
    "",
    summary="List resource types",
    description="Returns active resource types (e.g. used by activity-resource picker). Requires resource_types:read.",
    dependencies=[Depends(require_permission(RESOURCE_TYPES_READ))],
)
def list_resource_types(
    controller: Annotated[ResourceTypeController, Depends(get_resource_type_controller)],
    include_inactive: bool = Query(False, description="Include deactivated rows"),
) -> List[ResourceTypeResponse]:
    return controller.list_(include_inactive=include_inactive)


@router.get(
    "/{rt_id}",
    summary="Get resource type details",
    dependencies=[Depends(require_permission(RESOURCE_TYPES_READ))],
    responses={404: {"description": "ResourceType not found"}},
)
def get_resource_type_details(
    rt_id: str,
    controller: Annotated[ResourceTypeController, Depends(get_resource_type_controller)],
) -> ResourceTypeResponse:
    return controller.get_details(rt_id)


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    summary="Create a resource type",
    description="Creates a resource type. `code` must be unique. Requires resource_types:manage.",
    dependencies=[Depends(require_permission(RESOURCE_TYPES_MANAGE))],
    responses={409: {"description": "ResourceType code already exists"}},
)
def create_resource_type(
    payload: ResourceTypeCreateRequest,
    controller: Annotated[ResourceTypeController, Depends(get_resource_type_controller)],
) -> ResourceTypeResponse:
    return controller.create(payload)


@router.patch(
    "/{rt_id}",
    summary="Update a resource type",
    dependencies=[Depends(require_permission(RESOURCE_TYPES_MANAGE))],
    responses={404: {"description": "ResourceType not found"}},
)
def update_resource_type(
    rt_id: str,
    payload: ResourceTypeUpdateRequest,
    controller: Annotated[ResourceTypeController, Depends(get_resource_type_controller)],
) -> ResourceTypeResponse:
    return controller.update(rt_id, payload)


@router.delete(
    "/{rt_id}",
    summary="Delete (deactivate) a resource type",
    dependencies=[Depends(require_permission(RESOURCE_TYPES_MANAGE))],
    responses={404: {"description": "ResourceType not found"}},
)
def delete_resource_type(
    rt_id: str,
    controller: Annotated[ResourceTypeController, Depends(get_resource_type_controller)],
) -> ResourceTypeResponse:
    return controller.delete(rt_id)


@router.post(
    "/{rt_id}/restore",
    summary="Restore (reactivate) a resource type",
    dependencies=[Depends(require_permission(RESOURCE_TYPES_MANAGE))],
    responses={404: {"description": "ResourceType not found"}},
)
def restore_resource_type(
    rt_id: str,
    controller: Annotated[ResourceTypeController, Depends(get_resource_type_controller)],
) -> ResourceTypeResponse:
    return controller.restore(rt_id)
