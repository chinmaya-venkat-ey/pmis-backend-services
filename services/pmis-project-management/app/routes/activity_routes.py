"""Routes for /project/milestones/{id}/activities/* and /project/activities/{id}/*."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status

from app.controllers.activity_controller import ActivityController
from app.core.permissions import (
    ACTIVITIES_CREATE,
    ACTIVITIES_DELETE,
    ACTIVITIES_READ,
    ACTIVITIES_RESTORE,
    ACTIVITIES_UPDATE_DEPENDENCIES,
)
from app.core.rbac import require_authenticated, require_permission
from app.dependencies import get_activity_controller, get_optional_current_user_id
from app.schemas.activity import (
    ActivityCreateRequest,
    ActivityResponse,
    ActivityUpdateRequest,
)
from app.schemas.common import DependsListRequest


milestone_scoped_router = APIRouter(prefix="/milestones", tags=["activities"])


@milestone_scoped_router.get(
    "/{milestone_id}/activities/list",
    summary="List activities under a milestone",
    dependencies=[Depends(require_permission(ACTIVITIES_READ))],
)
def list_milestone_activities(
    milestone_id: str,
    offset: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    include_deleted: bool = Query(False),
    controller: ActivityController = Depends(get_activity_controller),
):
    return controller.list_for_milestone(
        milestone_id, offset=offset, page_size=page_size, include_deleted=include_deleted,
    )


router = APIRouter(prefix="/activities", tags=["activities"])


@router.post(
    "/create",
    response_model=ActivityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an activity (milestone_id in body)",
    dependencies=[Depends(require_permission(ACTIVITIES_CREATE))],
)
def create_activity(
    payload: ActivityCreateRequest,
    controller: ActivityController = Depends(get_activity_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.create(payload, caller_user_id=caller_user_id)


@router.get(
    "/{activity_id}/details",
    response_model=ActivityResponse,
    summary="Get activity details",
    dependencies=[Depends(require_permission(ACTIVITIES_READ))],
)
def get_activity(
    activity_id: str,
    controller: ActivityController = Depends(get_activity_controller),
):
    return controller.get(activity_id)


@router.patch(
    "/{activity_id}/update",
    response_model=ActivityResponse,
    summary="Update an activity (field-level RBAC)",
    description="Each touched field requires its `activities:update:<field>` code scoped to the parent project.",
    dependencies=[Depends(require_authenticated())],
)
def update_activity(
    activity_id: str,
    payload: ActivityUpdateRequest,
    request: Request,
    controller: ActivityController = Depends(get_activity_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.update(activity_id, payload, request=request, caller_user_id=caller_user_id)


@router.delete(
    "/{activity_id}/delete",
    response_model=ActivityResponse,
    summary="Soft-delete an activity",
    dependencies=[Depends(require_permission(ACTIVITIES_DELETE))],
)
def delete_activity(
    activity_id: str,
    controller: ActivityController = Depends(get_activity_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.delete(activity_id, caller_user_id=caller_user_id)


@router.post(
    "/{activity_id}/restore",
    response_model=ActivityResponse,
    summary="Restore an activity",
    dependencies=[Depends(require_permission(ACTIVITIES_RESTORE))],
)
def restore_activity(
    activity_id: str,
    controller: ActivityController = Depends(get_activity_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.restore(activity_id, caller_user_id=caller_user_id)


@router.put(
    "/{activity_id}/dependencies/replace",
    response_model=ActivityResponse,
    summary="Replace activity dependsOn list",
    dependencies=[Depends(require_permission(ACTIVITIES_UPDATE_DEPENDENCIES))],
)
def replace_activity_dependencies(
    activity_id: str,
    payload: DependsListRequest,
    controller: ActivityController = Depends(get_activity_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.replace_dependencies(activity_id, payload.depends_on, caller_user_id=caller_user_id)
