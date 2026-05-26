"""Routes for the activity_types catalog (doc 37)."""
from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, Depends, Query, status

from app.controllers.activity_type_controller import ActivityTypeController
from app.core.permissions import ACTIVITY_TYPES_MANAGE, ACTIVITY_TYPES_READ
from app.core.rbac import require_permission
from app.dependencies import get_activity_type_controller
from app.schemas.activity_type import (
    ActivityTypeCreateRequest,
    ActivityTypeResponse,
    ActivityTypeUpdateRequest,
)


router = APIRouter(prefix="/activity_types", tags=["activity_types"])


@router.get(
    "",
    summary="List activity types",
    dependencies=[Depends(require_permission(ACTIVITY_TYPES_READ))],
)
def list_activity_types(
    controller: Annotated[ActivityTypeController, Depends(get_activity_type_controller)],
    include_inactive: bool = Query(False, description="Include deactivated rows"),
) -> List[ActivityTypeResponse]:
    return controller.list_(include_inactive=include_inactive)


@router.get(
    "/{code}",
    summary="Get activity type details",
    dependencies=[Depends(require_permission(ACTIVITY_TYPES_READ))],
    responses={404: {"description": "ActivityType not found"}},
)
def get_activity_type_details(
    code: str,
    controller: Annotated[ActivityTypeController, Depends(get_activity_type_controller)],
) -> ActivityTypeResponse:
    return controller.get_details(code)


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    summary="Create an activity type",
    dependencies=[Depends(require_permission(ACTIVITY_TYPES_MANAGE))],
    responses={409: {"description": "ActivityType code already exists"}},
)
def create_activity_type(
    payload: ActivityTypeCreateRequest,
    controller: Annotated[ActivityTypeController, Depends(get_activity_type_controller)],
) -> ActivityTypeResponse:
    return controller.create(payload)


@router.patch(
    "/{code}",
    summary="Update an activity type",
    dependencies=[Depends(require_permission(ACTIVITY_TYPES_MANAGE))],
    responses={404: {"description": "ActivityType not found"}},
)
def update_activity_type(
    code: str,
    payload: ActivityTypeUpdateRequest,
    controller: Annotated[ActivityTypeController, Depends(get_activity_type_controller)],
) -> ActivityTypeResponse:
    return controller.update(code, payload)


@router.delete(
    "/{code}",
    summary="Delete (deactivate) an activity type",
    dependencies=[Depends(require_permission(ACTIVITY_TYPES_MANAGE))],
    responses={404: {"description": "ActivityType not found"}},
)
def delete_activity_type(
    code: str,
    controller: Annotated[ActivityTypeController, Depends(get_activity_type_controller)],
) -> ActivityTypeResponse:
    return controller.delete(code)


@router.post(
    "/{code}/restore",
    summary="Restore (reactivate) an activity type",
    dependencies=[Depends(require_permission(ACTIVITY_TYPES_MANAGE))],
    responses={404: {"description": "ActivityType not found"}},
)
def restore_activity_type(
    code: str,
    controller: Annotated[ActivityTypeController, Depends(get_activity_type_controller)],
) -> ActivityTypeResponse:
    return controller.restore(code)
