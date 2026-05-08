"""Tasks routes."""
from typing import Any, Dict
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ....core.middleware.rbac import require_permission
from ....infrastructure.db.session import get_db
from .._inline_attachments import dispatch_create
from .controller import TaskController
from .permissions import (
    TASKS_CREATE, TASKS_READ, TASKS_UPDATE, TASKS_DELETE, TASKS_RESTORE,
)
from .schemas import TaskCreateRequest, TaskUpdateRequest, TaskListQuery


tasks_activity_router = APIRouter(prefix="/activities", tags=["tasks"])
tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])


# Doc 30: dual-mode body. JSON keeps the typed Pydantic schema;
# multipart adds optional ``body`` / ``files`` and JSON-encodes
# ``dependsOn`` and the ``resource`` nested object.
_TASK_MULTIPART_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["name", "startDate", "endDate"],
    "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": 255},
        "description": {"type": "string", "maxLength": 5000},
        "startDate": {"type": "string", "format": "date-time"},
        "endDate": {"type": "string", "format": "date-time"},
        "actualStartDate": {"type": "string", "format": "date-time"},
        "actualEndDate": {"type": "string", "format": "date-time"},
        "position": {"type": "integer", "minimum": 0},
        "resourceMode": {
            "type": "string",
            "description": (
                "Only meaningful when the parent activity is "
                "type='resource'. One of: count | details."
            ),
        },
        "resourceCount": {"type": "integer", "minimum": 1},
        "resource": {
            "type": "string",
            "description": (
                "JSON-encoded resource block. Used only when the parent "
                "activity is resource/details."
            ),
        },
        "dependsOn": {
            "type": "string",
            "description": "JSON-encoded array of task UUIDs.",
        },
        "body": {"type": "string", "description": "Optional comment text."},
        "files": {
            "type": "array",
            "items": {"type": "string", "format": "binary"},
            "description": "Optional file uploads (repeatable).",
        },
    },
}


@tasks_activity_router.post(
    "/{activity_id}/tasks/create",
    dependencies=[require_permission(TASKS_CREATE)],
    summary="Create task under activity",
    description=(
        "Create a task. Accepts EITHER ``application/json`` (legacy) "
        "OR ``multipart/form-data`` (doc 30 — same fields plus optional "
        "``body`` (comment text) and ``files`` (uploads))."
    ),
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": TaskCreateRequest.model_json_schema(by_alias=True),
                },
                "multipart/form-data": {"schema": _TASK_MULTIPART_SCHEMA},
            },
        },
    },
)
async def create(
    request: Request, activity_id: str, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return await dispatch_create(
        request,
        schema_cls=TaskCreateRequest,
        json_handler=lambda req, activity_id, db, data:
            TaskController.create(req, activity_id, data, db),
        multipart_handler=lambda req, activity_id, db:
            TaskController.create_multipart(req, activity_id, db),
        json_args=(activity_id, db),
        multipart_args=(activity_id, db),
    )


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
