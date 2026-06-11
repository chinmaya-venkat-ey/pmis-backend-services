"""Milestone routes — mounted under ``/project``.

Two routers because the URL surface is two-shaped:
  * project-scoped: ``POST/GET /project/projects/{uuid}/milestones``
  * id-scoped:      ``GET/PATCH/DELETE`` + ``POST /restore`` under
                    ``/project/milestones/{id}``

Create accepts dual-mode (JSON or multipart with optional ``body`` for an
inline comment and ``files`` for uploads). ``dependsOn`` and ``vendors``
travel inline on both the create and PATCH bodies.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse

from app.controllers.milestone_controller import MilestoneController
from app.core.permissions import (
    MILESTONES_CREATE,
    MILESTONES_DELETE,
    MILESTONES_READ,
    MILESTONES_RESTORE,
)
from app.core.rbac import (
    require_authenticated,
    require_permission,
    require_project_permission,
)
from app.dependencies import get_milestone_controller, get_optional_current_user_id
from app.schemas.milestone import (
    MilestoneCreateRequest,
    MilestoneResponse,
    MilestoneUpdateRequest,
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
    MILESTONE_MULTIPART_PROPERTIES,
    dual_mode_request_body,
)


# ----- /project/projects/{uuid}/milestones --------------------------------
project_scoped_router = APIRouter(prefix="/projects", tags=["milestones"])


async def _create_multipart(
    request: Request,
    project_uuid: str,
    controller: MilestoneController,
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
                "status", "priority",
            ),
            int_keys=("position",),
            array_keys=("dependsOn", "vendors", "vendorIds"),
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
        "depends_on": fields.get("dependsOn") or [],
        # Multipart wire used ``vendors`` in monolith; accept either alias.
        "vendor_ids": fields.get("vendorIds") or fields.get("vendors") or [],
    }
    normalized = {k: v for k, v in normalized.items() if v is not None}
    payload = MilestoneCreateRequest.model_validate(normalized)

    files = extract_files_from_form(form)
    pre_validate_files(files)
    body = form.get("body") if isinstance(form.get("body"), str) else None

    envelopes = upload_files_via_client(files) if files else []
    return controller.create(
        project_uuid, payload,
        caller_user_id=caller_user_id,
        body=body, attachments=envelopes or None,
    )


@project_scoped_router.post(
    "/{project_uuid}/milestones/create",
    response_model=MilestoneResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a milestone under a project (JSON or multipart)",
    description=(
        "Dual-mode dispatch: ``application/json`` keeps the legacy shape "
        "(milestone fields only); ``multipart/form-data`` accepts the same "
        "fields PLUS optional ``body`` (inline comment text) and ``files`` "
        "(uploads). When attachments are present the milestone + comment "
        "row + attachment metadata are persisted in the same request."
    ),
    dependencies=[Depends(require_project_permission(MILESTONES_CREATE))],
    openapi_extra=dual_mode_request_body(
        MilestoneCreateRequest,
        multipart_required=("name", "startDate", "endDate"),
        multipart_properties=MILESTONE_MULTIPART_PROPERTIES,
    ),
)
async def create_milestone(
    request: Request,
    project_uuid: str,
    controller: Annotated[MilestoneController, Depends(get_milestone_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return await dispatch_create(
        request,
        schema_cls=MilestoneCreateRequest,
        json_handler=lambda data: controller.create(
            project_uuid, data, caller_user_id=caller_user_id,
        ),
        multipart_handler=lambda: _create_multipart(
            request, project_uuid, controller, caller_user_id,
        ),
    )


@project_scoped_router.get(
    "/{project_uuid}/milestones",
    summary="List milestones under a project",
    dependencies=[Depends(require_project_permission(MILESTONES_READ))],
)
def list_project_milestones(
    project_uuid: str,
    controller: Annotated[MilestoneController, Depends(get_milestone_controller)],
    offset: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, alias="pageSize")] = 20,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
):
    return controller.list_for_project(
        project_uuid, offset=offset, page_size=page_size,
        include_deleted=include_deleted,
    )


# ----- /project/milestones/{id} -------------------------------------------
router = APIRouter(prefix="/milestones", tags=["milestones"])


@router.get(
    "/{milestone_id}",
    response_model=MilestoneResponse,
    summary="Get milestone by id",
    dependencies=[Depends(require_project_permission(MILESTONES_READ))],
)
def get_milestone(
    milestone_id: str,
    controller: Annotated[MilestoneController, Depends(get_milestone_controller)],
):
    return controller.get(milestone_id)


@router.patch(
    "/{milestone_id}",
    response_model=MilestoneResponse,
    summary="Update a milestone (field-level RBAC; depends_on + vendor_ids inline)",
    # Field-level RBAC runs in the service layer via assert_field_writes_allowed.
    # No umbrella code at the route.
    dependencies=[Depends(require_authenticated())],
)
def update_milestone(
    milestone_id: str,
    payload: MilestoneUpdateRequest,
    request: Request,
    controller: Annotated[MilestoneController, Depends(get_milestone_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return controller.update(
        milestone_id, payload,
        caller_user_id=caller_user_id, request=request,
    )


@router.delete(
    "/{milestone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a milestone (cascades to descendants)",
    dependencies=[Depends(require_project_permission(MILESTONES_DELETE))],
)
def delete_milestone(
    milestone_id: str,
    controller: Annotated[MilestoneController, Depends(get_milestone_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    controller.delete(milestone_id, caller_user_id=caller_user_id)


@router.post(
    "/{milestone_id}/restore",
    response_model=MilestoneResponse,
    summary="Restore a soft-deleted milestone",
    dependencies=[Depends(require_project_permission(MILESTONES_RESTORE))],
)
def restore_milestone(
    milestone_id: str,
    controller: Annotated[MilestoneController, Depends(get_milestone_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return controller.restore(milestone_id, caller_user_id=caller_user_id)
