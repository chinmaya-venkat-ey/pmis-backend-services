"""Activity routes — mounted under ``/project``.

Two routers:
  * milestone-scoped: ``POST/GET /project/milestones/{milestone_id}/activities``
  * id-scoped:        ``GET/PATCH/DELETE`` + ``POST /restore`` under
                      ``/project/activities/{id}``

Create accepts dual-mode (JSON or multipart with optional ``body`` for an
inline comment and ``files`` for uploads). ``dependsOn`` travels inline
on both the create and PATCH bodies (no separate ``/dependencies`` endpoint).
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse

from app.controllers.activity_controller import ActivityController
from app.core.permissions import (
    ACTIVITIES_CREATE,
    ACTIVITIES_DELETE,
    ACTIVITIES_READ,
    ACTIVITIES_RESTORE,
)
from app.core.rbac import (
    require_authenticated,
    require_permission,
    require_project_permission,
)
from app.dependencies import get_activity_controller, get_optional_current_user_id
from app.schemas.activity import (
    ActivityCompletionEligibilityResponse,
    ActivityCreateRequest,
    ActivityResponse,
    ActivityStartRequest,
    ActivityUpdateRequest,
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
    ACTIVITY_MULTIPART_PROPERTIES,
    dual_mode_request_body,
)


# ----- /project/milestones/{milestone_id}/activities ----------------------
milestone_scoped_router = APIRouter(prefix="/milestones", tags=["activities"])


def _bearer_from_request(request: Request) -> Optional[str]:
    """Extract the caller's bearer token (for the write-time leave-mgmt rate call)."""
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(None, 1)[1].strip() or None
    return None


async def _create_multipart(
    request: Request,
    milestone_id: str,
    controller: ActivityController,
    caller_user_id: Optional[str],
    bearer_token: Optional[str] = None,
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
                "ownerDivision", "vendorId",
            ),
            int_keys=("position",),
            array_keys=("dependsOn", "concernedDivisions"),
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
        "owner_division": fields.get("ownerDivision"),
        "concerned_divisions": fields.get("concernedDivisions"),
        "vendor_id": fields.get("vendorId"),
        "depends_on": fields.get("dependsOn") or [],
    }
    normalized = {k: v for k, v in normalized.items() if v is not None}
    payload = ActivityCreateRequest.model_validate(normalized)

    files = extract_files_from_form(form)
    pre_validate_files(files)
    body = form.get("body") if isinstance(form.get("body"), str) else None

    envelopes = upload_files_via_client(files) if files else []
    return controller.create(
        milestone_id, payload,
        caller_user_id=caller_user_id,
        body=body, attachments=envelopes or None, bearer_token=bearer_token,
    )


@milestone_scoped_router.post(
    "/{milestone_id}/activities/create",
    response_model=ActivityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an activity under a milestone (JSON or multipart)",
    dependencies=[Depends(require_project_permission(ACTIVITIES_CREATE))],
    openapi_extra=dual_mode_request_body(
        ActivityCreateRequest,
        multipart_required=("name", "startDate", "endDate"),
        multipart_properties=ACTIVITY_MULTIPART_PROPERTIES,
    ),
)
async def create_activity(
    request: Request,
    milestone_id: str,
    controller: Annotated[ActivityController, Depends(get_activity_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    bearer = _bearer_from_request(request)
    return await dispatch_create(
        request,
        schema_cls=ActivityCreateRequest,
        json_handler=lambda data: controller.create(
            milestone_id, data, caller_user_id=caller_user_id, bearer_token=bearer,
        ),
        multipart_handler=lambda: _create_multipart(
            request, milestone_id, controller, caller_user_id, bearer,
        ),
    )


@milestone_scoped_router.get(
    "/{milestone_id}/activities",
    summary="List activities under a milestone",
    dependencies=[Depends(require_project_permission(ACTIVITIES_READ))],
)
def list_milestone_activities(
    milestone_id: str,
    controller: Annotated[ActivityController, Depends(get_activity_controller)],
    offset: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[Optional[int], Query(ge=1, alias="pageSize")] = None,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
):
    return controller.list_for_milestone(
        milestone_id, offset=offset, page_size=page_size,
        include_deleted=include_deleted,
    )


# ----- /project/activities/{id} ------------------------------------------
router = APIRouter(prefix="/activities", tags=["activities"])


@router.get(
    "/{activity_id}",
    response_model=ActivityResponse,
    summary="Get activity by id",
    dependencies=[Depends(require_project_permission(ACTIVITIES_READ))],
)
def get_activity(
    activity_id: str,
    controller: Annotated[ActivityController, Depends(get_activity_controller)],
):
    return controller.get(activity_id)


@router.get(
    "/{activity_id}/completion-eligibility",
    response_model=ActivityCompletionEligibilityResponse,
    summary="Check whether an activity's dependency targets are all completed",
    description=(
        "Read-only pre-flight for activity completion. Returns whether "
        "every dependency target of the activity is in a terminal status "
        "(``eligible``) plus the list of any blocking dependencies. Mutates "
        "nothing. Intended to be called before attempting a status→completed "
        "update (e.g. by the workflow service) so the caller can block the "
        "completion when dependencies are unfinished, mirroring the same "
        "gate the PATCH update enforces server-side."
    ),
    dependencies=[Depends(require_project_permission(ACTIVITIES_READ))],
)
def activity_completion_eligibility(
    activity_id: str,
    controller: Annotated[ActivityController, Depends(get_activity_controller)],
):
    return controller.completion_eligibility(activity_id)


@router.patch(
    "/{activity_id}",
    response_model=ActivityResponse,
    summary="Update an activity (field-level RBAC; depends_on inline)",
    # Field-level RBAC runs in the service layer via assert_field_writes_allowed.
    # No umbrella code at the route.
    dependencies=[Depends(require_authenticated())],
)
def update_activity(
    activity_id: str,
    payload: ActivityUpdateRequest,
    request: Request,
    controller: Annotated[ActivityController, Depends(get_activity_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return controller.update(
        activity_id, payload,
        caller_user_id=caller_user_id, request=request,
        bearer_token=_bearer_from_request(request),
    )


@router.post(
    "/{activity_id}/start",
    response_model=ActivityResponse,
    summary="Start an activity (#188 — validated: predecessors done, not started/terminal)",
    description=(
        "Marks the activity started (``activityStarted=true``) and stamps "
        "``actualStartDate`` (defaults to now). Rejects starting a completed "
        "activity, an already-started one, one on a closed project, or one "
        "whose predecessor activities are not yet completed. A started activity "
        "is still ``not_completed`` — the approval workflow runs later."
    ),
    # Auth at the route; field-level RBAC (activity_started / actual_start_date)
    # runs in the service via assert_field_writes_allowed.
    dependencies=[Depends(require_authenticated())],
)
def start_activity(
    activity_id: str,
    request: Request,
    controller: Annotated[ActivityController, Depends(get_activity_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    payload: Optional[ActivityStartRequest] = None,
):
    return controller.start(
        activity_id, payload or ActivityStartRequest(),
        caller_user_id=caller_user_id, request=request,
    )


@router.delete(
    "/{activity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete an activity (cascades to tasks / subtasks)",
    dependencies=[Depends(require_project_permission(ACTIVITIES_DELETE))],
)
def delete_activity(
    activity_id: str,
    controller: Annotated[ActivityController, Depends(get_activity_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    controller.delete(activity_id, caller_user_id=caller_user_id)


@router.post(
    "/{activity_id}/restore",
    response_model=ActivityResponse,
    summary="Restore an activity",
    dependencies=[Depends(require_project_permission(ACTIVITIES_RESTORE))],
)
def restore_activity(
    activity_id: str,
    controller: Annotated[ActivityController, Depends(get_activity_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return controller.restore(activity_id, caller_user_id=caller_user_id)
