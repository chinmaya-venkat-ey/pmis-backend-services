"""Subtasks routes."""
from typing import Any, Dict
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ....core.middleware.rbac import require_permission
from ....infrastructure.db.session import get_db
from .._inline_attachments import dispatch_create
from .controller import SubtaskController
from .permissions import (
    SUBTASKS_CREATE, SUBTASKS_READ, SUBTASKS_UPDATE, SUBTASKS_DELETE, SUBTASKS_RESTORE,
)
from .schemas import SubtaskCreateRequest, SubtaskUpdateRequest, SubtaskListQuery


subtasks_task_router = APIRouter(prefix="/tasks", tags=["subtasks"])
subtasks_router = APIRouter(prefix="/subtasks", tags=["subtasks"])


# Doc 30: dual-mode body. Same shape as task, since subtasks share
# resource/dependsOn semantics and inherit type from the parent task.
_SUBTASK_MULTIPART_SCHEMA: Dict[str, Any] = {
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
        "resourceMode": {"type": "string"},
        "resourceCount": {"type": "integer", "minimum": 1},
        "resource": {
            "type": "string",
            "description": "JSON-encoded resource block (resource/details only).",
        },
        "dependsOn": {
            "type": "string",
            "description": "JSON-encoded array of subtask UUIDs.",
        },
        "body": {"type": "string", "description": "Optional comment text."},
        "files": {
            "type": "array",
            "items": {"type": "string", "format": "binary"},
            "description": "Optional file uploads (repeatable).",
        },
    },
}


def _subtask_openapi_extra() -> Dict[str, Any]:
    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": SubtaskCreateRequest.model_json_schema(by_alias=True),
                },
                "multipart/form-data": {"schema": _SUBTASK_MULTIPART_SCHEMA},
            },
        },
    }


@subtasks_task_router.post(
    "/{task_id}/subtasks/create",
    dependencies=[require_permission(SUBTASKS_CREATE)],
    summary="Create subtask under task",
    description=(
        "Create a task-scoped subtask. Accepts EITHER ``application/json`` "
        "(legacy) OR ``multipart/form-data`` (doc 30 — same fields plus "
        "optional ``body`` (comment text) and ``files`` (uploads))."
    ),
    status_code=201,
    openapi_extra=_subtask_openapi_extra(),
)
async def create(
    request: Request, task_id: str, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return await dispatch_create(
        request,
        schema_cls=SubtaskCreateRequest,
        json_handler=lambda req, task_id, db, data:
            SubtaskController.create(req, task_id, data, db),
        multipart_handler=lambda req, task_id, db:
            SubtaskController.create_multipart(req, task_id, db),
        json_args=(task_id, db),
        multipart_args=(task_id, db),
    )


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


@subtasks_router.post(
    "/{parent_subtask_id}/subtasks/create",
    dependencies=[require_permission(SUBTASKS_CREATE)],
    summary="Create a subtask nested under another subtask (doc 24)",
    description=(
        "Create a subtask nested under another subtask. Same body as the "
        "task-scoped create endpoint. Accepts JSON or multipart (doc 30 — "
        "same fields plus optional ``body`` (comment text) and "
        "``files`` (uploads))."
    ),
    status_code=201,
    openapi_extra=_subtask_openapi_extra(),
)
async def create_nested(
    request: Request,
    parent_subtask_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return await dispatch_create(
        request,
        schema_cls=SubtaskCreateRequest,
        json_handler=lambda req, parent_subtask_id, db, data:
            SubtaskController.create_nested(req, parent_subtask_id, data, db),
        multipart_handler=lambda req, parent_subtask_id, db:
            SubtaskController.create_nested_multipart(req, parent_subtask_id, db),
        json_args=(parent_subtask_id, db),
        multipart_args=(parent_subtask_id, db),
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
