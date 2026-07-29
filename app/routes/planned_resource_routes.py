"""Planned-resources routes — the resource-type phase "Planned Resources" tab.

Rows plan a headcount of a (per-org) designation over a deployment window; the
BE snapshots the per-hour rate from the designation master and derives billable
hours from the project leaveConfig, then rolls the SUM into the phase's
``resource_cost`` cost item. Same RBAC as the rest of the finance module:
  - reads  → ``projects:read`` (PAYMENT_READ)
  - writes → ``projects:update:finance`` (PROJECTS_UPDATE_FINANCE); publish-lock
    + admin bypass applied in the service.
"""
from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, status

from app.controllers.planned_resource_controller import PlannedResourceController
from app.core.permissions import PAYMENT_READ, PROJECTS_UPDATE_FINANCE
from app.core.rbac import require_permission, require_project_permission
from app.dependencies import (
    get_caller_is_admin,
    get_optional_current_user_id,
    get_planned_resource_controller,
)
from app.schemas.planned_resource import (
    PlannedResourceCreateRequest,
    PlannedResourceResponse,
    PlannedResourceUpdateRequest,
)


# ===================================================== planned resources (scoped)
planned_resource_project_scoped_router = APIRouter(prefix="/projects", tags=["planned-resources"])


@planned_resource_project_scoped_router.get(
    "/{project_uuid}/planned-resources",
    summary="List a project's planned resources",
    dependencies=[Depends(require_project_permission(PAYMENT_READ))],
)
def list_planned_resources(
    project_uuid: str,
    controller: Annotated[PlannedResourceController, Depends(get_planned_resource_controller)],
) -> List[PlannedResourceResponse]:
    return controller.list_for_project(project_uuid)


@planned_resource_project_scoped_router.post(
    "/{project_uuid}/planned-resources",
    response_model=PlannedResourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a planned resource to a resource-cost row",
    dependencies=[Depends(require_project_permission(PROJECTS_UPDATE_FINANCE))],
)
def create_planned_resource(
    project_uuid: str,
    payload: PlannedResourceCreateRequest,
    controller: Annotated[PlannedResourceController, Depends(get_planned_resource_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
):
    return controller.create(
        project_uuid, payload, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


# ========================================================= planned resources (id)
planned_resource_router = APIRouter(prefix="/planned-resources", tags=["planned-resources"])


@planned_resource_router.get(
    "/{planned_resource_id}",
    response_model=PlannedResourceResponse,
    summary="Get a planned resource by id",
    dependencies=[Depends(require_permission(PAYMENT_READ))],
)
def get_planned_resource(
    planned_resource_id: str,
    controller: Annotated[PlannedResourceController, Depends(get_planned_resource_controller)],
):
    return controller.get(planned_resource_id)


@planned_resource_router.patch(
    "/{planned_resource_id}",
    response_model=PlannedResourceResponse,
    summary="Update a planned resource",
    dependencies=[Depends(require_permission(PROJECTS_UPDATE_FINANCE))],
)
def update_planned_resource(
    planned_resource_id: str,
    payload: PlannedResourceUpdateRequest,
    controller: Annotated[PlannedResourceController, Depends(get_planned_resource_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
):
    return controller.update(
        planned_resource_id, payload, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


@planned_resource_router.delete(
    "/{planned_resource_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a planned resource",
    dependencies=[Depends(require_permission(PROJECTS_UPDATE_FINANCE))],
)
def delete_planned_resource(
    planned_resource_id: str,
    controller: Annotated[PlannedResourceController, Depends(get_planned_resource_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
):
    controller.delete(planned_resource_id, caller_user_id=caller_user_id, caller_is_admin=caller_is_admin)
