"""Routes for the project_status_transitions catalog.

Defines the legal state-machine edges for project status. `from_status=NULL`
represents the initial-status seed (status accepted on a fresh create).
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query, status

from app.controllers.project_status_transition_controller import (
    ProjectStatusTransitionController,
)
from app.core.permissions import (
    PROJECT_STATUS_TRANSITIONS_MANAGE,
    PROJECT_STATUS_TRANSITIONS_READ,
)
from app.core.rbac import require_permission
from app.dependencies import get_project_status_transition_controller
from app.schemas.project_status_transition import (
    ProjectStatusTransitionCreateRequest,
    ProjectStatusTransitionResponse,
    ProjectStatusTransitionUpdateRequest,
)


router = APIRouter(
    prefix="/project-status-transitions", tags=["project_status_transitions"]
)


@router.get(
    "/list",
    response_model=List[ProjectStatusTransitionResponse],
    summary="List project status transitions",
    description=(
        "Returns the legal state-machine edges. project-svc reads these to "
        "validate PATCH /project/projects/{uuid}/update status changes."
    ),
    dependencies=[Depends(require_permission(PROJECT_STATUS_TRANSITIONS_READ))],
)
def list_project_status_transitions(
    include_inactive: bool = Query(False, description="Include deactivated rows"),
    controller: ProjectStatusTransitionController = Depends(
        get_project_status_transition_controller
    ),
) -> List[ProjectStatusTransitionResponse]:
    return controller.list_(include_inactive=include_inactive)


@router.get(
    "/{row_id}/details",
    response_model=ProjectStatusTransitionResponse,
    summary="Get project status transition details",
    dependencies=[Depends(require_permission(PROJECT_STATUS_TRANSITIONS_READ))],
    responses={404: {"description": "ProjectStatusTransition not found"}},
)
def get_project_status_transition_details(
    row_id: int,
    controller: ProjectStatusTransitionController = Depends(
        get_project_status_transition_controller
    ),
) -> ProjectStatusTransitionResponse:
    return controller.get_details(row_id)


@router.post(
    "/create",
    response_model=ProjectStatusTransitionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project status transition edge",
    description="`from_status=null` for the initial-status seed; otherwise both required.",
    dependencies=[Depends(require_permission(PROJECT_STATUS_TRANSITIONS_MANAGE))],
    responses={409: {"description": "Transition edge already exists"}},
)
def create_project_status_transition(
    payload: ProjectStatusTransitionCreateRequest,
    controller: ProjectStatusTransitionController = Depends(
        get_project_status_transition_controller
    ),
) -> ProjectStatusTransitionResponse:
    return controller.create(payload)


@router.patch(
    "/{row_id}/update",
    response_model=ProjectStatusTransitionResponse,
    summary="Update a project status transition",
    description="`from_status` and `to_status` are immutable.",
    dependencies=[Depends(require_permission(PROJECT_STATUS_TRANSITIONS_MANAGE))],
    responses={404: {"description": "ProjectStatusTransition not found"}},
)
def update_project_status_transition(
    row_id: int,
    payload: ProjectStatusTransitionUpdateRequest,
    controller: ProjectStatusTransitionController = Depends(
        get_project_status_transition_controller
    ),
) -> ProjectStatusTransitionResponse:
    return controller.update(row_id, payload)


@router.delete(
    "/{row_id}/delete",
    response_model=ProjectStatusTransitionResponse,
    summary="Delete (deactivate) a project status transition",
    dependencies=[Depends(require_permission(PROJECT_STATUS_TRANSITIONS_MANAGE))],
    responses={404: {"description": "ProjectStatusTransition not found"}},
)
def delete_project_status_transition(
    row_id: int,
    controller: ProjectStatusTransitionController = Depends(
        get_project_status_transition_controller
    ),
) -> ProjectStatusTransitionResponse:
    return controller.delete(row_id)


@router.post(
    "/{row_id}/restore",
    response_model=ProjectStatusTransitionResponse,
    summary="Restore (reactivate) a project status transition",
    dependencies=[Depends(require_permission(PROJECT_STATUS_TRANSITIONS_MANAGE))],
    responses={404: {"description": "ProjectStatusTransition not found"}},
)
def restore_project_status_transition(
    row_id: int,
    controller: ProjectStatusTransitionController = Depends(
        get_project_status_transition_controller
    ),
) -> ProjectStatusTransitionResponse:
    return controller.restore(row_id)
