"""Routes for the activity_statuses catalog (doc 37)."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query, status

from app.controllers.activity_status_controller import ActivityStatusController
from app.core.permissions import ACTIVITY_STATUSES_MANAGE, ACTIVITY_STATUSES_READ
from app.core.rbac import require_permission
from app.dependencies import get_activity_status_controller
from app.schemas.activity_status import (
    ActivityStatusCreateRequest,
    ActivityStatusResponse,
    ActivityStatusUpdateRequest,
)


router = APIRouter(prefix="/activity_statuses", tags=["activity_statuses"])


@router.get(
    "",
    response_model=List[ActivityStatusResponse],
    summary="List activity statuses",
    description="Returns activity status options. `is_terminal=true` rows are 'done' states.",
    dependencies=[Depends(require_permission(ACTIVITY_STATUSES_READ))],
)
def list_activity_statuses(
    include_inactive: bool = Query(False, description="Include deactivated rows"),
    controller: ActivityStatusController = Depends(get_activity_status_controller),
) -> List[ActivityStatusResponse]:
    return controller.list_(include_inactive=include_inactive)


@router.get(
    "/{code}",
    response_model=ActivityStatusResponse,
    summary="Get activity status details",
    dependencies=[Depends(require_permission(ACTIVITY_STATUSES_READ))],
    responses={404: {"description": "ActivityStatus not found"}},
)
def get_activity_status_details(
    code: str,
    controller: ActivityStatusController = Depends(get_activity_status_controller),
) -> ActivityStatusResponse:
    return controller.get_details(code)


@router.post(
    "/create",
    response_model=ActivityStatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an activity status",
    dependencies=[Depends(require_permission(ACTIVITY_STATUSES_MANAGE))],
    responses={409: {"description": "ActivityStatus code already exists"}},
)
def create_activity_status(
    payload: ActivityStatusCreateRequest,
    controller: ActivityStatusController = Depends(get_activity_status_controller),
) -> ActivityStatusResponse:
    return controller.create(payload)


@router.patch(
    "/{code}",
    response_model=ActivityStatusResponse,
    summary="Update an activity status",
    dependencies=[Depends(require_permission(ACTIVITY_STATUSES_MANAGE))],
    responses={404: {"description": "ActivityStatus not found"}},
)
def update_activity_status(
    code: str,
    payload: ActivityStatusUpdateRequest,
    controller: ActivityStatusController = Depends(get_activity_status_controller),
) -> ActivityStatusResponse:
    return controller.update(code, payload)


@router.delete(
    "/{code}",
    response_model=ActivityStatusResponse,
    summary="Delete (deactivate) an activity status",
    dependencies=[Depends(require_permission(ACTIVITY_STATUSES_MANAGE))],
    responses={404: {"description": "ActivityStatus not found"}},
)
def delete_activity_status(
    code: str,
    controller: ActivityStatusController = Depends(get_activity_status_controller),
) -> ActivityStatusResponse:
    return controller.delete(code)


@router.post(
    "/{code}/restore",
    response_model=ActivityStatusResponse,
    summary="Restore (reactivate) an activity status",
    dependencies=[Depends(require_permission(ACTIVITY_STATUSES_MANAGE))],
    responses={404: {"description": "ActivityStatus not found"}},
)
def restore_activity_status(
    code: str,
    controller: ActivityStatusController = Depends(get_activity_status_controller),
) -> ActivityStatusResponse:
    return controller.restore(code)
