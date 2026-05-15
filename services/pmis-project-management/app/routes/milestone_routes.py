"""Routes for /project/projects/{uuid}/milestones/* and /project/milestones/{id}/*."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status

from app.controllers.milestone_controller import MilestoneController
from app.core.permissions import (
    MILESTONES_CREATE,
    MILESTONES_DELETE,
    MILESTONES_READ,
    MILESTONES_RESTORE,
    MILESTONES_UPDATE_DEPENDENCIES,
    MILESTONES_UPDATE_VENDORS,
)
from app.core.rbac import (
    require_authenticated,
    require_permission,
    require_project_permission,
)
from app.dependencies import get_milestone_controller, get_optional_current_user_id
from app.schemas.common import DependsListRequest, VendorIdsListRequest
from app.schemas.milestone import (
    MilestoneCreateRequest,
    MilestoneResponse,
    MilestoneUpdateRequest,
)


# /project/projects/{uuid}/milestones/* — project-scoped reads/creates
project_scoped_router = APIRouter(prefix="/projects", tags=["milestones"])


@project_scoped_router.get(
    "/{project_uuid}/milestones/list",
    summary="List milestones under a project",
    dependencies=[Depends(require_project_permission(MILESTONES_READ))],
)
def list_project_milestones(
    project_uuid: str,
    offset: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    include_deleted: bool = Query(False),
    controller: MilestoneController = Depends(get_milestone_controller),
):
    return controller.list_for_project(
        project_uuid, offset=offset, page_size=page_size, include_deleted=include_deleted,
    )


@project_scoped_router.post(
    "/{project_uuid}/milestones/create",
    response_model=MilestoneResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a milestone under a project",
    dependencies=[Depends(require_project_permission(MILESTONES_CREATE))],
)
def create_milestone(
    project_uuid: str,
    payload: MilestoneCreateRequest,
    controller: MilestoneController = Depends(get_milestone_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.create(project_uuid, payload, caller_user_id=caller_user_id)


# /project/milestones/{id}/* — single-milestone operations (no project_uuid in path)
router = APIRouter(prefix="/milestones", tags=["milestones"])


@router.get(
    "/{milestone_id}/details",
    response_model=MilestoneResponse,
    summary="Get milestone details",
    dependencies=[Depends(require_permission(MILESTONES_READ))],
    responses={404: {"description": "Milestone not found"}},
)
def get_milestone(
    milestone_id: str,
    controller: MilestoneController = Depends(get_milestone_controller),
):
    return controller.get(milestone_id)


@router.patch(
    "/{milestone_id}/update",
    response_model=MilestoneResponse,
    summary="Update a milestone (field-level RBAC)",
    description="Each touched field requires its `milestones:update:<field>` code scoped to the parent project.",
    dependencies=[Depends(require_authenticated())],
)
def update_milestone(
    milestone_id: str,
    payload: MilestoneUpdateRequest,
    request: Request,
    controller: MilestoneController = Depends(get_milestone_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.update(milestone_id, payload, request=request, caller_user_id=caller_user_id)


@router.delete(
    "/{milestone_id}/delete",
    response_model=MilestoneResponse,
    summary="Soft-delete a milestone",
    dependencies=[Depends(require_permission(MILESTONES_DELETE))],
)
def delete_milestone(
    milestone_id: str,
    controller: MilestoneController = Depends(get_milestone_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.delete(milestone_id, caller_user_id=caller_user_id)


@router.post(
    "/{milestone_id}/restore",
    response_model=MilestoneResponse,
    summary="Restore a milestone",
    dependencies=[Depends(require_permission(MILESTONES_RESTORE))],
)
def restore_milestone(
    milestone_id: str,
    controller: MilestoneController = Depends(get_milestone_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.restore(milestone_id, caller_user_id=caller_user_id)


@router.put(
    "/{milestone_id}/dependencies/replace",
    response_model=MilestoneResponse,
    summary="Replace milestone dependsOn list",
    dependencies=[Depends(require_permission(MILESTONES_UPDATE_DEPENDENCIES))],
)
def replace_milestone_dependencies(
    milestone_id: str,
    payload: DependsListRequest,
    controller: MilestoneController = Depends(get_milestone_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.replace_dependencies(milestone_id, payload.depends_on, caller_user_id=caller_user_id)


@router.put(
    "/{milestone_id}/vendors/replace",
    response_model=MilestoneResponse,
    summary="Replace the milestone<->vendor mapping",
    dependencies=[Depends(require_permission(MILESTONES_UPDATE_VENDORS))],
)
def replace_milestone_vendors(
    milestone_id: str,
    payload: VendorIdsListRequest,
    controller: MilestoneController = Depends(get_milestone_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.set_vendors(milestone_id, payload.vendor_ids, caller_user_id=caller_user_id)
