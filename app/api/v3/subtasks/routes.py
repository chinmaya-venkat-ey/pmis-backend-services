"""Subtasks routes."""
from typing import Any, Dict
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ....core.middleware.rbac import require_permission
from ....infrastructure.db.session import get_db
from .controller import SubtaskController
from .permissions import (
    SUBTASKS_CREATE, SUBTASKS_READ, SUBTASKS_UPDATE, SUBTASKS_DELETE, SUBTASKS_RESTORE,
)
from .schemas import SubtaskCreateRequest, SubtaskUpdateRequest, SubtaskListQuery


subtasks_task_router = APIRouter(prefix="/tasks", tags=["subtasks"])
subtasks_router = APIRouter(prefix="/subtasks", tags=["subtasks"])


@subtasks_task_router.post(
    "/{task_id}/subtasks/create",
    dependencies=[require_permission(SUBTASKS_CREATE)],
    summary="Create subtask under task", status_code=201,
)
def create(request: Request, task_id: str, data: SubtaskCreateRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return SubtaskController.create(request, task_id, data, db)


@subtasks_task_router.get(
    "/{task_id}/subtasks",
    dependencies=[require_permission(SUBTASKS_READ)],
    summary="List subtasks under task",
)
def list_(
    request: Request, task_id: str,
    offset: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100),
    includeDeleted: bool = Query(False),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return SubtaskController.list(
        request, task_id,
        SubtaskListQuery(offset=offset, pageSize=pageSize, includeDeleted=includeDeleted),
        db,
    )


@subtasks_router.get(
    "/{subtask_id}",
    dependencies=[require_permission(SUBTASKS_READ)],
    summary="Get subtask by id",
)
def get(request: Request, subtask_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return SubtaskController.get(request, subtask_id, db)


@subtasks_router.patch(
    "/{subtask_id}",
    dependencies=[require_permission(SUBTASKS_UPDATE)],
    summary="Update subtask (handles type transitions + resource upsert)",
)
def update(request: Request, subtask_id: str, data: SubtaskUpdateRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return SubtaskController.update(request, subtask_id, data, db)


@subtasks_router.delete(
    "/{subtask_id}",
    dependencies=[require_permission(SUBTASKS_DELETE)],
    summary="Soft-delete subtask",
)
def delete(request: Request, subtask_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return SubtaskController.delete(request, subtask_id, db)


@subtasks_router.post(
    "/{subtask_id}/restore",
    dependencies=[require_permission(SUBTASKS_RESTORE)],
    summary="Restore a soft-deleted subtask (admin)",
)
def restore(request: Request, subtask_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return SubtaskController.restore(request, subtask_id, db)
