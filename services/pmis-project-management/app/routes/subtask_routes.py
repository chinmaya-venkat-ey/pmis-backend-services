"""Routes for /project/tasks/{id}/subtasks/* and /project/subtasks/{id}/*."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status

from app.controllers.subtask_controller import SubtaskController
from app.core.permissions import (
    SUBTASKS_CREATE,
    SUBTASKS_DELETE,
    SUBTASKS_READ,
    SUBTASKS_RESTORE,
    SUBTASKS_UPDATE_DEPENDENCIES,
)
from app.core.rbac import require_authenticated, require_permission
from app.dependencies import get_optional_current_user_id, get_subtask_controller
from app.schemas.common import DependsListRequest
from app.schemas.subtask import (
    SubtaskCreateRequest,
    SubtaskResponse,
    SubtaskUpdateRequest,
)


task_scoped_router = APIRouter(prefix="/tasks", tags=["subtasks"])


@task_scoped_router.get(
    "/{task_id}/subtasks/list",
    summary="List subtasks under a task",
    dependencies=[Depends(require_permission(SUBTASKS_READ))],
)
def list_task_subtasks(
    task_id: str,
    offset: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
    include_deleted: bool = Query(False),
    top_level_only: bool = Query(False),
    controller: SubtaskController = Depends(get_subtask_controller),
):
    return controller.list_for_task(
        task_id, offset=offset, page_size=page_size,
        include_deleted=include_deleted, top_level_only=top_level_only,
    )


router = APIRouter(prefix="/subtasks", tags=["subtasks"])


@router.post(
    "/create",
    response_model=SubtaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a subtask (top-level or nested)",
    description=(
        "Body carries either `task_id` (top-level child of a task) OR "
        "`parent_subtask_id` (nested child of another subtask). Nesting depth "
        "is capped by SUBTASK_MAX_NESTING_DEPTH (default 5)."
    ),
    dependencies=[Depends(require_permission(SUBTASKS_CREATE))],
    responses={
        409: {"description": "Subtask nesting depth exceeded OR dependency cycle"},
    },
)
def create_subtask(
    payload: SubtaskCreateRequest,
    controller: SubtaskController = Depends(get_subtask_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.create(payload, caller_user_id=caller_user_id)


@router.get(
    "/{subtask_id}/details",
    response_model=SubtaskResponse,
    summary="Get subtask details",
    dependencies=[Depends(require_permission(SUBTASKS_READ))],
)
def get_subtask(
    subtask_id: str,
    controller: SubtaskController = Depends(get_subtask_controller),
):
    return controller.get(subtask_id)


@router.patch(
    "/{subtask_id}/update",
    response_model=SubtaskResponse,
    summary="Update a subtask (field-level RBAC + same-vendor assignment guard)",
    description="Each touched field requires its `subtasks:update:<field>` code scoped to the parent project.",
    dependencies=[Depends(require_authenticated())],
)
def update_subtask(
    subtask_id: str,
    payload: SubtaskUpdateRequest,
    request: Request,
    controller: SubtaskController = Depends(get_subtask_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.update(subtask_id, payload, request=request, caller_user_id=caller_user_id)


@router.delete(
    "/{subtask_id}/delete",
    response_model=SubtaskResponse,
    summary="Soft-delete a subtask",
    dependencies=[Depends(require_permission(SUBTASKS_DELETE))],
)
def delete_subtask(
    subtask_id: str,
    controller: SubtaskController = Depends(get_subtask_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.delete(subtask_id, caller_user_id=caller_user_id)


@router.post(
    "/{subtask_id}/restore",
    response_model=SubtaskResponse,
    summary="Restore a subtask",
    dependencies=[Depends(require_permission(SUBTASKS_RESTORE))],
)
def restore_subtask(
    subtask_id: str,
    controller: SubtaskController = Depends(get_subtask_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.restore(subtask_id, caller_user_id=caller_user_id)


@router.put(
    "/{subtask_id}/dependencies/replace",
    response_model=SubtaskResponse,
    summary="Replace subtask dependsOn list",
    dependencies=[Depends(require_permission(SUBTASKS_UPDATE_DEPENDENCIES))],
)
def replace_subtask_dependencies(
    subtask_id: str,
    payload: DependsListRequest,
    controller: SubtaskController = Depends(get_subtask_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.replace_dependencies(subtask_id, payload.depends_on, caller_user_id=caller_user_id)
