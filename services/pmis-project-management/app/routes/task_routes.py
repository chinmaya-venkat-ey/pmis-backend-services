"""Routes for /project/activities/{id}/tasks/* and /project/tasks/{id}/*."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status

from app.controllers.task_controller import TaskController
from app.core.permissions import (
    TASKS_CREATE,
    TASKS_DELETE,
    TASKS_READ,
    TASKS_RESTORE,
    TASKS_UPDATE_DEPENDENCIES,
)
from app.core.rbac import require_authenticated, require_permission
from app.dependencies import get_optional_current_user_id, get_task_controller
from app.schemas.common import DependsListRequest
from app.schemas.task import TaskCreateRequest, TaskResponse, TaskUpdateRequest


activity_scoped_router = APIRouter(prefix="/activities", tags=["tasks"])


@activity_scoped_router.get(
    "/{activity_id}/tasks/list",
    summary="List tasks under an activity",
    dependencies=[Depends(require_permission(TASKS_READ))],
)
def list_activity_tasks(
    activity_id: str,
    offset: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    include_deleted: bool = Query(False),
    controller: TaskController = Depends(get_task_controller),
):
    return controller.list_for_activity(
        activity_id, offset=offset, page_size=page_size, include_deleted=include_deleted,
    )


router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post(
    "/create",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task (activity_id in body)",
    dependencies=[Depends(require_permission(TASKS_CREATE))],
)
def create_task(
    payload: TaskCreateRequest,
    controller: TaskController = Depends(get_task_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.create(payload, caller_user_id=caller_user_id)


@router.get(
    "/{task_id}/details",
    response_model=TaskResponse,
    summary="Get task details",
    dependencies=[Depends(require_permission(TASKS_READ))],
)
def get_task(
    task_id: str,
    controller: TaskController = Depends(get_task_controller),
):
    return controller.get(task_id)


@router.patch(
    "/{task_id}/update",
    response_model=TaskResponse,
    summary="Update a task (field-level RBAC + same-vendor assignment guard)",
    description=(
        "Each touched field requires its `tasks:update:<field>` code scoped to "
        "the parent project. Setting `assigned_to` triggers the round-7 Q9 "
        "validation: assignee exists, not deleted, same vendor as project, "
        "and has a role-assignment on the project (explicit or via vendor)."
    ),
    dependencies=[Depends(require_authenticated())],
)
def update_task(
    task_id: str,
    payload: TaskUpdateRequest,
    request: Request,
    controller: TaskController = Depends(get_task_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.update(task_id, payload, request=request, caller_user_id=caller_user_id)


@router.delete(
    "/{task_id}/delete",
    response_model=TaskResponse,
    summary="Soft-delete a task",
    dependencies=[Depends(require_permission(TASKS_DELETE))],
)
def delete_task(
    task_id: str,
    controller: TaskController = Depends(get_task_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.delete(task_id, caller_user_id=caller_user_id)


@router.post(
    "/{task_id}/restore",
    response_model=TaskResponse,
    summary="Restore a task",
    dependencies=[Depends(require_permission(TASKS_RESTORE))],
)
def restore_task(
    task_id: str,
    controller: TaskController = Depends(get_task_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.restore(task_id, caller_user_id=caller_user_id)


@router.put(
    "/{task_id}/dependencies/replace",
    response_model=TaskResponse,
    summary="Replace task dependsOn list",
    dependencies=[Depends(require_permission(TASKS_UPDATE_DEPENDENCIES))],
)
def replace_task_dependencies(
    task_id: str,
    payload: DependsListRequest,
    controller: TaskController = Depends(get_task_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.replace_dependencies(task_id, payload.depends_on, caller_user_id=caller_user_id)
