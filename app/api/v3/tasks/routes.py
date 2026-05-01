"""Tasks routes."""
from typing import Any, Dict
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ....core.middleware.rbac import require_permission
from ....infrastructure.db.session import get_db
from .controller import TaskController
from .permissions import (
    TASKS_CREATE, TASKS_READ, TASKS_UPDATE, TASKS_DELETE, TASKS_RESTORE,
)
from .schemas import TaskCreateRequest, TaskUpdateRequest, TaskListQuery


tasks_activity_router = APIRouter(prefix="/activities", tags=["tasks"])
tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])


@tasks_activity_router.post(
    "/{activity_id}/tasks/create",
    dependencies=[require_permission(TASKS_CREATE)],
    summary="Create task under activity", status_code=201,
)
def create(request: Request, activity_id: str, data: TaskCreateRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return TaskController.create(request, activity_id, data, db)


@tasks_activity_router.get(
    "/{activity_id}/tasks",
    dependencies=[require_permission(TASKS_READ)],
    summary="List tasks under activity",
)
def list_(
    request: Request, activity_id: str,
    offset: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100),
    includeDeleted: bool = Query(False),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return TaskController.list(
        request, activity_id,
        TaskListQuery(offset=offset, pageSize=pageSize, includeDeleted=includeDeleted),
        db,
    )


@tasks_router.get(
    "/{task_id}",
    dependencies=[require_permission(TASKS_READ)],
    summary="Get task by id",
)
def get(request: Request, task_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return TaskController.get(request, task_id, db)


@tasks_router.patch(
    "/{task_id}",
    dependencies=[require_permission(TASKS_UPDATE)],
    summary="Update task (handles type transitions + resource upsert)",
)
def update(request: Request, task_id: str, data: TaskUpdateRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return TaskController.update(request, task_id, data, db)


@tasks_router.delete(
    "/{task_id}",
    dependencies=[require_permission(TASKS_DELETE)],
    summary="Soft-delete task (cascades to subtasks)",
)
def delete(request: Request, task_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return TaskController.delete(request, task_id, db)


@tasks_router.post(
    "/{task_id}/restore",
    dependencies=[require_permission(TASKS_RESTORE)],
    summary="Restore a soft-deleted task (admin)",
)
def restore(request: Request, task_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return TaskController.restore(request, task_id, db)
