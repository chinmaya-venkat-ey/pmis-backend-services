"""Routes for the milestone_statuses catalog (doc 37)."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query, status

from app.controllers.milestone_status_controller import MilestoneStatusController
from app.core.permissions import MILESTONE_STATUSES_MANAGE, MILESTONE_STATUSES_READ
from app.core.rbac import require_permission
from app.dependencies import get_milestone_status_controller
from app.schemas.milestone_status import (
    MilestoneStatusCreateRequest,
    MilestoneStatusResponse,
    MilestoneStatusUpdateRequest,
)


router = APIRouter(prefix="/milestone_statuses", tags=["milestone_statuses"])


@router.get(
    "",
    summary="List milestone statuses",
    description="Returns milestone status options. `is_terminal=true` rows are 'done' states.",
    dependencies=[Depends(require_permission(MILESTONE_STATUSES_READ))],
)
def list_milestone_statuses(
    include_inactive: bool = Query(False, description="Include deactivated rows"),
    controller: Annotated[MilestoneStatusController, Depends(get_milestone_status_controller)],
) -> List[MilestoneStatusResponse]:
    return controller.list_(include_inactive=include_inactive)


@router.get(
    "/{code}",
    summary="Get milestone status details",
    dependencies=[Depends(require_permission(MILESTONE_STATUSES_READ))],
    responses={404: {"description": "MilestoneStatus not found"}},
)
def get_milestone_status_details(
    code: str,
    controller: Annotated[MilestoneStatusController, Depends(get_milestone_status_controller)],
) -> MilestoneStatusResponse:
    return controller.get_details(code)


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    summary="Create a milestone status",
    dependencies=[Depends(require_permission(MILESTONE_STATUSES_MANAGE))],
    responses={409: {"description": "MilestoneStatus code already exists"}},
)
def create_milestone_status(
    payload: MilestoneStatusCreateRequest,
    controller: Annotated[MilestoneStatusController, Depends(get_milestone_status_controller)],
) -> MilestoneStatusResponse:
    return controller.create(payload)


@router.patch(
    "/{code}",
    summary="Update a milestone status",
    dependencies=[Depends(require_permission(MILESTONE_STATUSES_MANAGE))],
    responses={404: {"description": "MilestoneStatus not found"}},
)
def update_milestone_status(
    code: str,
    payload: MilestoneStatusUpdateRequest,
    controller: Annotated[MilestoneStatusController, Depends(get_milestone_status_controller)],
) -> MilestoneStatusResponse:
    return controller.update(code, payload)


@router.delete(
    "/{code}",
    summary="Delete (deactivate) a milestone status",
    dependencies=[Depends(require_permission(MILESTONE_STATUSES_MANAGE))],
    responses={404: {"description": "MilestoneStatus not found"}},
)
def delete_milestone_status(
    code: str,
    controller: Annotated[MilestoneStatusController, Depends(get_milestone_status_controller)],
) -> MilestoneStatusResponse:
    return controller.delete(code)


@router.post(
    "/{code}/restore",
    summary="Restore (reactivate) a milestone status",
    dependencies=[Depends(require_permission(MILESTONE_STATUSES_MANAGE))],
    responses={404: {"description": "MilestoneStatus not found"}},
)
def restore_milestone_status(
    code: str,
    controller: Annotated[MilestoneStatusController, Depends(get_milestone_status_controller)],
) -> MilestoneStatusResponse:
    return controller.restore(code)
