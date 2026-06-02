"""Task routes — mounted under ``/project``.

Two routers:
  * activity-scoped: ``POST/GET /project/activities/{activity_id}/tasks``
  * id-scoped:       ``GET/PATCH/DELETE`` + ``POST /restore`` under
                     ``/project/tasks/{id}``

Create accepts dual-mode (JSON or multipart with optional ``body`` for an
inline comment and ``files`` for uploads). ``dependsOn`` travels inline
on both create and PATCH bodies.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse

from app.controllers.task_controller import TaskController
from app.core.permissions import (
    TASKS_CREATE,
    TASKS_DELETE,
    TASKS_READ,
    TASKS_RESTORE,
)
from app.core.rbac import (
    require_authenticated,
    require_permission,
    require_project_permission,
)
from app.dependencies import get_optional_current_user_id, get_task_controller
from app.schemas.task import TaskCreateRequest, TaskResponse, TaskUpdateRequest
from app.utilities.multipart_form import (
    Multipart422,
    dispatch_create,
    extract_files_from_form,
    parse_form_fields,
    pre_validate_files,
    upload_files_via_client,
)
from app.utilities.openapi_extra import (
    TASK_MULTIPART_PROPERTIES,
    dual_mode_request_body,
)


# ----- /project/activities/{activity_id}/tasks ---------------------------
activity_scoped_router = APIRouter(prefix="/activities", tags=["tasks"])


async def _create_multipart(
    request: Request,
    activity_id: str,
    controller: TaskController,
    caller_user_id: Optional[str],
):
    form = await request.form()
    try:
        fields = parse_form_fields(
            form,
            required_string_keys=("name",),
            string_keys=(
                "description", "startDate", "endDate",
                "actualStartDate", "actualEndDate",
                "status", "priority", "assignedTo",
            ),
            int_keys=("position",),
            array_keys=("dependsOn",),
        )
    except Multipart422 as exc:
        # Surface through the framework's RequestValidationError handler
        # so the response rides the standard ``error`` envelope.
        from fastapi.exceptions import RequestValidationError
        raise RequestValidationError(exc.detail)
    normalized = {
        "name": fields.get("name"),
        "description": fields.get("description"),
        "start_date": fields.get("startDate"),
        "end_date": fields.get("endDate"),
        "actual_start_date": fields.get("actualStartDate"),
        "actual_end_date": fields.get("actualEndDate"),
        "status": fields.get("status"),
        "priority": fields.get("priority"),
        "position": fields.get("position"),
        "assigned_to": fields.get("assignedTo"),
        "depends_on": fields.get("dependsOn") or [],
    }
    normalized = {k: v for k, v in normalized.items() if v is not None}
    payload = TaskCreateRequest.model_validate(normalized)

    files = extract_files_from_form(form)
    pre_validate_files(files)
    body = form.get("body") if isinstance(form.get("body"), str) else None

    envelopes = upload_files_via_client(files) if files else []
    return controller.create(
        activity_id, payload,
        caller_user_id=caller_user_id,
        body=body, attachments=envelopes or None,
    )


@activity_scoped_router.post(
    "/{activity_id}/tasks/create",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task under an activity (JSON or multipart)",
    dependencies=[Depends(require_project_permission(TASKS_CREATE))],
    openapi_extra=dual_mode_request_body(
        TaskCreateRequest,
        multipart_required=("name", "startDate", "endDate"),
        multipart_properties=TASK_MULTIPART_PROPERTIES,
    ),
)
async def create_task(
    request: Request,
    activity_id: str,
    controller: Annotated[TaskController, Depends(get_task_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return await dispatch_create(
        request,
        schema_cls=TaskCreateRequest,
        json_handler=lambda data: controller.create(
            activity_id, data, caller_user_id=caller_user_id,
        ),
        multipart_handler=lambda: _create_multipart(
            request, activity_id, controller, caller_user_id,
        ),
    )


@activity_scoped_router.get(
    "/{activity_id}/tasks",
    summary="List tasks under an activity",
    dependencies=[Depends(require_permission(TASKS_READ))],
)
def list_activity_tasks(
    activity_id: str,
    controller: Annotated[TaskController, Depends(get_task_controller)],
    offset: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    include_deleted: bool = Query(False, alias="includeDeleted"),
):
    return controller.list_for_activity(
        activity_id, offset=offset, page_size=page_size,
        include_deleted=include_deleted,
    )


# ----- /project/tasks/{id} -----------------------------------------------
router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Get task by id",
    dependencies=[Depends(require_permission(TASKS_READ))],
)
def get_task(
    task_id: str,
    controller: Annotated[TaskController, Depends(get_task_controller)],
):
    return controller.get(task_id)


@router.patch(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Update a task (field-level RBAC + same-vendor assignment guard)",
    description=(
        "``assigned_to`` triggers the Q9 validation: assignee must exist, "
        "not be soft-deleted, belong to the same vendor as the parent "
        "project, AND have a role-assignment on the project (explicit or "
        "via vendor projection). ``depends_on`` travels inline."
    ),
    # Field-level RBAC runs in the service layer via assert_field_writes_allowed.
    # No umbrella code at the route.
    dependencies=[Depends(require_authenticated())],
)
def update_task(
    task_id: str,
    payload: TaskUpdateRequest,
    request: Request,
    controller: Annotated[TaskController, Depends(get_task_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return controller.update(
        task_id, payload,
        caller_user_id=caller_user_id, request=request,
    )


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a task (cascades to subtasks)",
    dependencies=[Depends(require_project_permission(TASKS_DELETE))],
)
def delete_task(
    task_id: str,
    controller: Annotated[TaskController, Depends(get_task_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    controller.delete(task_id, caller_user_id=caller_user_id)


@router.post(
    "/{task_id}/restore",
    response_model=TaskResponse,
    summary="Restore a task",
    dependencies=[Depends(require_project_permission(TASKS_RESTORE))],
)
def restore_task(
    task_id: str,
    controller: Annotated[TaskController, Depends(get_task_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return controller.restore(task_id, caller_user_id=caller_user_id)
