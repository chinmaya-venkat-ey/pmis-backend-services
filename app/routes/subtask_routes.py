"""Subtask routes — mounted under ``/project``.

Two routers covering three URL shapes (Doc-24 unbounded nesting):
  * task-scoped:    ``POST/GET /project/tasks/{task_id}/subtasks``
  * id-scoped:      ``GET/PATCH/DELETE`` + ``POST /restore`` under
                    ``/project/subtasks/{id}``
  * nested under another subtask: ``POST /project/subtasks/{parent_id}/subtasks``

Both create paths accept dual-mode (JSON or multipart with optional
``body`` + ``files``). ``dependsOn`` travels inline on create and PATCH.
Nesting is uncapped — the cascade soft-delete walks via parent_subtask_id
with a cycle-safe seen-set.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse

from app.controllers.subtask_controller import SubtaskController
from app.core.permissions import (
    SUBTASKS_CREATE,
    SUBTASKS_DELETE,
    SUBTASKS_READ,
    SUBTASKS_RESTORE,
)
from app.core.rbac import (
    require_authenticated,
    require_permission,
    require_project_permission,
)
from app.dependencies import get_optional_current_user_id, get_subtask_controller
from app.schemas.subtask import (
    SubtaskCreateRequest,
    SubtaskResponse,
    SubtaskUpdateRequest,
)
from app.utilities.multipart_form import (
    Multipart422,
    dispatch_create,
    extract_files_from_form,
    parse_form_fields,
    pre_validate_files,
    upload_files_via_client,
)
from app.utilities.openapi_extra import (
    SUBTASK_MULTIPART_PROPERTIES,
    dual_mode_request_body,
)


def _parse_subtask_multipart_form(form) -> SubtaskCreateRequest:
    """Shared form-decoder used by both subtask create endpoints."""
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
        raise _Multipart422HTTP(exc.detail)
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
    return SubtaskCreateRequest.model_validate(normalized)


class _Multipart422HTTP(Exception):
    def __init__(self, detail):
        self.detail = detail


def _multipart_422_response(detail):
    """Surface multipart parse failures through the framework's
    RequestValidationError handler so the body rides the canonical
    ``error`` envelope (not the success ``data`` envelope)."""
    from fastapi.exceptions import RequestValidationError
    raise RequestValidationError(detail)


# ----- /project/tasks/{task_id}/subtasks ---------------------------------
task_scoped_router = APIRouter(prefix="/tasks", tags=["subtasks"])


async def _create_under_task_multipart(
    request: Request,
    task_id: str,
    controller: SubtaskController,
    caller_user_id: Optional[str],
):
    form = await request.form()
    try:
        payload = _parse_subtask_multipart_form(form)
    except _Multipart422HTTP as exc:
        return _multipart_422_response(exc.detail)
    files = extract_files_from_form(form)
    pre_validate_files(files)
    body = form.get("body") if isinstance(form.get("body"), str) else None
    envelopes = upload_files_via_client(files) if files else []
    return controller.create_under_task(
        task_id, payload,
        caller_user_id=caller_user_id,
        body=body, attachments=envelopes or None,
    )


@task_scoped_router.post(
    "/{task_id}/subtasks/create",
    response_model=SubtaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a top-level subtask under a task (JSON or multipart)",
    dependencies=[Depends(require_project_permission(SUBTASKS_CREATE))],
    openapi_extra=dual_mode_request_body(
        SubtaskCreateRequest,
        multipart_required=("name", "startDate", "endDate"),
        multipart_properties=SUBTASK_MULTIPART_PROPERTIES,
    ),
)
async def create_subtask_under_task(
    request: Request,
    task_id: str,
    controller: Annotated[SubtaskController, Depends(get_subtask_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return await dispatch_create(
        request,
        schema_cls=SubtaskCreateRequest,
        json_handler=lambda data: controller.create_under_task(
            task_id, data, caller_user_id=caller_user_id,
        ),
        multipart_handler=lambda: _create_under_task_multipart(
            request, task_id, controller, caller_user_id,
        ),
    )


@task_scoped_router.get(
    "/{task_id}/subtasks",
    summary="List subtasks under a task",
    dependencies=[Depends(require_project_permission(SUBTASKS_READ))],
)
def list_task_subtasks(
    task_id: str,
    controller: Annotated[SubtaskController, Depends(get_subtask_controller)],
    offset: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, alias="pageSize")] = 20,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
):
    # Monolith parity: no ``topLevelOnly`` filter — returns every subtask
    # under the task (nested + top-level alike).
    return controller.list_for_task(
        task_id, offset=offset, page_size=page_size,
        include_deleted=include_deleted, top_level_only=False,
    )


# ----- /project/subtasks/{...} -------------------------------------------
router = APIRouter(prefix="/subtasks", tags=["subtasks"])


async def _create_nested_multipart(
    request: Request,
    parent_subtask_id: str,
    controller: SubtaskController,
    caller_user_id: Optional[str],
):
    form = await request.form()
    try:
        payload = _parse_subtask_multipart_form(form)
    except _Multipart422HTTP as exc:
        return _multipart_422_response(exc.detail)
    files = extract_files_from_form(form)
    pre_validate_files(files)
    body = form.get("body") if isinstance(form.get("body"), str) else None
    envelopes = upload_files_via_client(files) if files else []
    return controller.create_nested(
        parent_subtask_id, payload,
        caller_user_id=caller_user_id,
        body=body, attachments=envelopes or None,
    )


@router.post(
    "/{parent_subtask_id}/subtasks/create",
    response_model=SubtaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a subtask nested under another subtask (any depth)",
    description=(
        "Doc-24 nesting is uncapped. The new subtask inherits its parent's "
        "``task_id`` and ``project_id``."
    ),
    dependencies=[Depends(require_project_permission(SUBTASKS_CREATE))],
    openapi_extra=dual_mode_request_body(
        SubtaskCreateRequest,
        multipart_required=("name", "startDate", "endDate"),
        multipart_properties=SUBTASK_MULTIPART_PROPERTIES,
    ),
)
async def create_nested_subtask(
    request: Request,
    parent_subtask_id: str,
    controller: Annotated[SubtaskController, Depends(get_subtask_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return await dispatch_create(
        request,
        schema_cls=SubtaskCreateRequest,
        json_handler=lambda data: controller.create_nested(
            parent_subtask_id, data, caller_user_id=caller_user_id,
        ),
        multipart_handler=lambda: _create_nested_multipart(
            request, parent_subtask_id, controller, caller_user_id,
        ),
    )


@router.get(
    "/{subtask_id}",
    response_model=SubtaskResponse,
    summary="Get subtask by id",
    dependencies=[Depends(require_project_permission(SUBTASKS_READ))],
)
def get_subtask(
    subtask_id: str,
    controller: Annotated[SubtaskController, Depends(get_subtask_controller)],
):
    return controller.get(subtask_id)


@router.patch(
    "/{subtask_id}",
    response_model=SubtaskResponse,
    summary="Update a subtask (field-level RBAC + same-vendor assignment guard)",
    # Field-level RBAC runs in the service layer via assert_field_writes_allowed.
    # No umbrella code at the route.
    dependencies=[Depends(require_authenticated())],
)
def update_subtask(
    subtask_id: str,
    payload: SubtaskUpdateRequest,
    request: Request,
    controller: Annotated[SubtaskController, Depends(get_subtask_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return controller.update(
        subtask_id, payload,
        caller_user_id=caller_user_id, request=request,
    )


@router.delete(
    "/{subtask_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a subtask (cascades to nested subtasks at any depth)",
    dependencies=[Depends(require_project_permission(SUBTASKS_DELETE))],
)
def delete_subtask(
    subtask_id: str,
    controller: Annotated[SubtaskController, Depends(get_subtask_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    controller.delete(subtask_id, caller_user_id=caller_user_id)


@router.post(
    "/{subtask_id}/restore",
    response_model=SubtaskResponse,
    summary="Restore a subtask",
    dependencies=[Depends(require_project_permission(SUBTASKS_RESTORE))],
)
def restore_subtask(
    subtask_id: str,
    controller: Annotated[SubtaskController, Depends(get_subtask_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return controller.restore(subtask_id, caller_user_id=caller_user_id)
