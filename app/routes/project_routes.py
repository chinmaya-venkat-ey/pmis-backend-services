"""Project routes — mounted under ``/project``.

Path shape mirrors the monolith's ``/api/v3/projects/*`` surface so the FE
only swaps the prefix. Project create accepts dual-mode (JSON or
multipart); ``files`` in multipart are stored as one ``body IS NULL``
comment row with ``target_kind='project'`` (matches the monolith's
project attachment listing).
"""
from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response, JSONResponse

from app.controllers.project_controller import ProjectController
from app.core.permissions import (
    PROJECTS_CLOSE,
    PROJECTS_REOPEN,
    PROJECTS_CREATE,
    PROJECTS_DELETE_ALL,
    PROJECTS_PUBLISH,
    PROJECTS_READ,
    PROJECTS_READ_ALL,
    PROJECT_MEMBERS_READ,
    COMMENTS_CREATE,
)
from app.core.rbac import (
    require_authenticated,
    require_permission,
    require_project_permission,
)
from app.dependencies import (
    get_caller_is_admin,
    get_optional_current_user_id,
    get_project_controller,
)
from app.schemas.project import (
    ProjectCloseRequest,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
    ProjectUpsertRequest,
)
from app.utilities.multipart_form import (
    Multipart422,
    dispatch_create,
    extract_files_from_form,
    parse_form_fields,
    pre_validate_files,
)
from app.utilities.openapi_extra import (
    PROJECT_MULTIPART_PROPERTIES,
    dual_mode_request_body,
    multipart_files_only_request_body,
)


router = APIRouter(prefix="/projects", tags=["projects"])


# ---------------------------------------------------------------- CREATE
# Dual-mode body: application/json OR multipart/form-data with files[].

async def _create_multipart(
    request: Request,
    controller: ProjectController,
    caller_user_id: Optional[str],
):
    form = await request.form()
    try:
        fields = parse_form_fields(
            form,
            required_string_keys=("name",),
            string_keys=(
                "description", "statusExplanation", "parentId", "status",
                "owner", "category", "categoryOther",
                "categoryOtherReason", "startDate", "endDate",
            ),
            array_keys=("vendorIds",),
        )
    except Multipart422 as exc:
        # Raise so the framework's RequestValidationError handler emits
        # the standard ``{error: {...}, status: 422}`` envelope. Returning
        # a raw JSONResponse here would put the error body under ``data``
        # (HAL wrapper assumes any non-envelope dict is a success payload).
        raise RequestValidationError(exc.detail)
    # camelCase → snake_case
    normalized = {
        "name": fields.get("name"),
        "description": fields.get("description"),
        "status_explanation": fields.get("statusExplanation"),
        "parent_id": fields.get("parentId"),
        "status": fields.get("status"),
        "owner": fields.get("owner"),
        "category": fields.get("category"),
        "category_other": fields.get("categoryOther"),
        "category_other_reason": fields.get("categoryOtherReason"),
        "start_date": fields.get("startDate"),
        "end_date": fields.get("endDate"),
        "vendor_ids": fields.get("vendorIds") or [],
    }
    # Drop ``None`` so optional fields don't trip Pydantic when omitted.
    normalized = {k: v for k, v in normalized.items() if v is not None}
    payload = ProjectCreateRequest.model_validate(normalized)

    files = extract_files_from_form(form)
    # Fail-fast: validate files BEFORE the project row is created so we
    # never leave a half-made project behind on a bad upload.
    pre_validate_files(files)

    project = controller.create(payload, caller_user_id=caller_user_id)
    if files:
        # AttachmentService writes one body-NULL comment row carrying the
        # file metadata, audits the upload, and commits.
        controller.attachments.upload(
            "project", project.id, files,
            caller_user_id=caller_user_id or "",
        )
        # Rebuild the response after the attachment write so the freshly-
        # uploaded files surface under ``attachments[]`` (the response
        # built by ``controller.create`` is stale — it captured the
        # project state BEFORE the attachment commit).
        project = controller.get(project.id)
    return project


@router.post(
    "/create",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project (JSON or multipart with file attachments)",
    description=(
        "Dual-mode dispatch. ``application/json`` carries project fields "
        "only. ``multipart/form-data`` accepts the same fields plus an "
        "optional ``files`` array; uploaded files land in the comments "
        "table as one ``body IS NULL`` row with ``target_kind='project'`` "
        "and surface back through ``GET /project/projects/{uuid}/attachments``."
    ),
    dependencies=[Depends(require_permission(PROJECTS_CREATE))],
    # Swagger UI can't auto-derive the body schema because the route
    # signature is ``request: Request`` (so we can sniff Content-Type).
    # Declare both content types explicitly.
    openapi_extra=dual_mode_request_body(
        ProjectCreateRequest,
        multipart_required=("name",),
        multipart_properties=PROJECT_MULTIPART_PROPERTIES,
    ),
)
async def create_project(
    request: Request,
    controller: Annotated[ProjectController, Depends(get_project_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return await dispatch_create(
        request,
        schema_cls=ProjectCreateRequest,
        json_handler=lambda data: controller.create(
            data, caller_user_id=caller_user_id,
        ),
        multipart_handler=lambda: _create_multipart(
            request, controller, caller_user_id,
        ),
    )


# ---------------------------------------------------------------- UPSERT

@router.put(
    "/{project_uuid}",
    response_model=ProjectResponse,
    summary="Create or update project by uuid (idempotent)",
    description=(
        "Idempotent create-or-update keyed by the URL UUID. Used by multi-"
        "step wizards: the FE generates the UUID once via crypto.randomUUID() "
        "and re-submits as the user progresses. Returns 201 on the INSERT "
        "branch and 200 on the UPDATE branch. The server auto-generates "
        "``project_code`` on insert and preserves it on update."
    ),
    dependencies=[Depends(require_permission(PROJECTS_CREATE))],
)
def upsert_project(
    project_uuid: str,
    payload: ProjectUpsertRequest,
    controller: Annotated[ProjectController, Depends(get_project_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    response, created = controller.upsert(
        project_uuid, payload, caller_user_id=caller_user_id,
    )
    # Carry the ``_created`` flag on the body so the FE can distinguish
    # the INSERT branch (201) from the UPDATE branch (200) without
    # reading the status code. Matches the monolith's upsert contract.
    body = response.model_dump(mode="json")
    body["_created"] = created
    return JSONResponse(
        status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        content=body,
    )


# ---------------------------------------------------------------- LIST

@router.get(
    "",
    summary="List live projects (excludes soft-deleted)",
    description=(
        "Default search listing. Soft-deleted projects are filtered out; "
        "results are newest-first. For the admin view that includes "
        "deleted rows, see ``GET /project/projects/all``."
    ),
    dependencies=[Depends(require_permission(PROJECTS_READ))],
)
def list_projects(
    request: Request,
    controller: Annotated[ProjectController, Depends(get_project_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
    offset: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, alias="pageSize")] = 20,
    active: Annotated[Optional[bool], Query()] = None,
):
    # Monolith parity (Doc-38): query schema is offset / pageSize / active
    # / includeDeleted ONLY — ``public`` + ``status`` were dropped.
    held = getattr(request.state, "user_permissions", None) or set()
    scoped = getattr(request.state, "scoped_permissions", None) or {}
    caller_project_ids = {pid for (kind, pid) in scoped if kind == "project" and pid}
    return controller.list_(
        offset=offset, page_size=page_size,
        status=None, active=active, public=None,
        include_deleted=False,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        caller_can_see_all=(PROJECTS_READ_ALL in held),
        caller_project_ids=caller_project_ids,
    )


@router.get(
    "/all",
    summary="List all projects including soft-deleted (admin / audit)",
    dependencies=[Depends(require_permission(PROJECTS_READ))],
)
def list_all_projects(
    request: Request,
    controller: Annotated[ProjectController, Depends(get_project_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
    offset: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, alias="pageSize")] = 20,
    active: Annotated[Optional[bool], Query()] = None,
):
    held = getattr(request.state, "user_permissions", None) or set()
    scoped = getattr(request.state, "scoped_permissions", None) or {}
    caller_project_ids = {pid for (kind, pid) in scoped if kind == "project" and pid}
    return controller.list_(
        offset=offset, page_size=page_size,
        status=None, active=active, public=None,
        include_deleted=True,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        caller_can_see_all=(PROJECTS_READ_ALL in held),
        caller_project_ids=caller_project_ids,
    )


# ---------------------------------------------------------------- READ / UPDATE / DELETE

@router.get(
    "/{project_uuid}",
    response_model=ProjectResponse,
    summary="Get project by uuid",
    description=(
        "Returns the full project resource. Non-admin callers receive "
        "404 when the project status is ``new`` or ``draft`` — mirrors "
        "the monolith's pre-publish visibility hide so the FE can't "
        "distinguish 'not yet published' from 'doesn't exist'."
    ),
    dependencies=[Depends(require_permission(PROJECTS_READ))],
    responses={404: {"description": "Project not found"}},
)
def get_project(
    project_uuid: str,
    controller: Annotated[ProjectController, Depends(get_project_controller)],
    caller_is_admin: Annotated[bool, Depends(get_caller_is_admin)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return controller.get(
        project_uuid,
        caller_is_admin=caller_is_admin,
        caller_user_id=caller_user_id,
    )


@router.patch(
    "/{project_uuid}",
    response_model=ProjectResponse,
    summary="Update a project (field-level RBAC + optional vendor_ids replace)",
    # Field-level RBAC runs in the service layer via assert_field_writes_allowed.
    # No umbrella code at the route — caller must hold the per-field codes for
    # whichever fields they touch.
    dependencies=[Depends(require_authenticated())],
)
def update_project(
    project_uuid: str,
    payload: ProjectUpdateRequest,
    request: Request,
    controller: Annotated[ProjectController, Depends(get_project_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return controller.update(
        project_uuid, payload,
        caller_user_id=caller_user_id, request=request,
    )


@router.delete(
    "/{project_uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a project (cascades to milestones / activities / tasks / subtasks)",
    dependencies=[Depends(require_project_permission(PROJECTS_DELETE_ALL))],
)
def delete_project(
    project_uuid: str,
    controller: Annotated[ProjectController, Depends(get_project_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    controller.delete(project_uuid, caller_user_id=caller_user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- lifecycle

@router.post(
    "/{project_uuid}/save",
    response_model=ProjectResponse,
    summary="Save project setup (new -> draft when at least one milestone exists)",
    description=(
        "Flips status from ``new`` to ``draft`` when the project carries "
        "at least one live milestone. Idempotent: a no-op once past ``new``."
    ),
    # Save is now authenticated-only at the route; no umbrella code. Any
    # field-level checks happen inside the service via the field walker.
    dependencies=[Depends(require_authenticated())],
)
def save_project(
    project_uuid: str,
    controller: Annotated[ProjectController, Depends(get_project_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return controller.save(project_uuid, caller_user_id=caller_user_id)


@router.post(
    "/{project_uuid}/publish",
    response_model=ProjectResponse,
    summary="Publish project",
    dependencies=[Depends(require_project_permission(PROJECTS_PUBLISH))],
)
def publish_project(
    project_uuid: str,
    controller: Annotated[ProjectController, Depends(get_project_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return controller.publish(project_uuid, caller_user_id=caller_user_id)


@router.post(
    "/{project_uuid}/close",
    response_model=ProjectResponse,
    summary="Close project (optional ``reason`` body)",
    dependencies=[Depends(require_project_permission(PROJECTS_CLOSE))],
)
def close_project(
    project_uuid: str,
    controller: Annotated[ProjectController, Depends(get_project_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    payload: Annotated[Optional[ProjectCloseRequest], Body()] = None,
):
    return controller.close(project_uuid, payload, caller_user_id=caller_user_id)


@router.post(
    "/{project_uuid}/reopen",
    response_model=ProjectResponse,
    summary="Reopen a closed project (closed -> published)",
    description=(
        "Inverse of ``/close``. Flips a closed project back to "
        "``published``, clears ``statusExplanation`` (including any "
        "auto-complete marker from the rollup cascade), and writes an "
        "audit row with ``action='reopen'`` capturing the prior reason."
    ),
    dependencies=[Depends(require_project_permission(PROJECTS_REOPEN))],
    responses={
        409: {"description": "Project is not closed (invalid_transition)."},
    },
)
def reopen_project(
    project_uuid: str,
    controller: Annotated[ProjectController, Depends(get_project_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return controller.reopen(project_uuid, caller_user_id=caller_user_id)


# ---------------------------------------------------------------- role-assignments

@router.get(
    "/{project_uuid}/role-assignments",
    summary="Per-project role assignments grouped by role",
    description=(
        "Returns users assigned to this project, grouped by the project-"
        "scoped role they hold (project_admin / project_member / "
        "division_member). Read-only mirror of user-mgmt's same-path "
        "endpoint so the FE can avoid a cross-service hop."
    ),
    dependencies=[Depends(require_permission(PROJECT_MEMBERS_READ))],
)
def list_project_role_assignments(
    project_uuid: str,
    controller: Annotated[ProjectController, Depends(get_project_controller)],
):
    return controller.role_assignments(project_uuid)


@router.get(
    "/{project_uuid}/assignable-users",
    summary="Users that can be assigned a Task / Sub-Task on this project",
    description=(
        "Union of (a) every user with a project-scoped role on this "
        "project AND (b) every user with an org_admin role on the "
        "project's owning vendor(s). Admin / super_admin tier users are "
        "filtered out. Each entry carries ``id`` / ``login`` / "
        "``fullName`` / ``email`` / ``orgRole``."
    ),
    dependencies=[Depends(require_permission(PROJECT_MEMBERS_READ))],
)
def list_project_assignable_users(
    project_uuid: str,
    request: Request,
    controller: Annotated[ProjectController, Depends(get_project_controller)],
):
    authorization = request.headers.get("authorization") or ""
    return controller.assignable_users(project_uuid, authorization=authorization)


# ---------------------------------------------------------------- audit-logs

@router.get(
    "/{project_uuid}/audit-logs",
    summary="Project audit log (paginated, newest-first)",
    description=(
        "Every state change, M/A/T/S edit, vendor mapping change, and "
        "lifecycle event captured against this project. Each row carries "
        "the actor + project context as snapshotted at write time."
    ),
    dependencies=[Depends(require_project_permission(PROJECTS_READ))],
)
def list_project_audit_logs(
    project_uuid: str,
    controller: Annotated[ProjectController, Depends(get_project_controller)],
    offset: Annotated[int, Query(ge=1, description="Page number (1-indexed).")] = 1,
    page_size: Annotated[int, Query(
        ge=1, le=200, alias="pageSize",
        description="Items per page (max 200).",
    )] = 50,
):
    return controller.audit_logs(
        project_uuid, offset=offset, page_size=page_size,
    )


# ---------------------------------------------------------------- discussion feed

@router.get(
    "/{project_uuid}/discussion-feed",
    summary="Unified discussion + attachments feed across the project tree",
    description=(
        "Every live comment row attached to this project OR any of its "
        "M/A/T/S descendants, paginated newest-first. Each entry carries "
        "``targetKind`` / ``targetId`` / ``targetName`` so the FE knows "
        "which entity in the tree the row belongs to."
    ),
    dependencies=[Depends(require_permission(PROJECTS_READ))],
)
def list_project_discussion_feed(
    project_uuid: str,
    controller: Annotated[ProjectController, Depends(get_project_controller)],
    offset: Annotated[int, Query(ge=1, description="Page number (1-indexed).")] = 1,
    page_size: Annotated[int, Query(
        ge=1, le=200, alias="pageSize",
        description="Items per page (max 200).",
    )] = 50,
):
    return controller.discussion_feed(
        project_uuid, offset=offset, page_size=page_size,
    )


# ---------------------------------------------------------------- attachments

@router.get(
    "/{project_uuid}/attachments",
    summary="List attachments uploaded against this project",
    # Round-8: scope-aware via require_project_permission since project_uuid
    # is in the URL.
    dependencies=[Depends(require_project_permission(PROJECTS_READ))],
)
def list_project_attachments(
    project_uuid: str,
    controller: Annotated[ProjectController, Depends(get_project_controller)],
):
    return controller.list_attachments(project_uuid)


@router.post(
    "/{project_uuid}/attachments",
    status_code=status.HTTP_201_CREATED,
    summary="Upload more attachments to an existing project (multipart)",
    description=(
        "Multipart-only endpoint for adding files to a project after "
        "create. Accepts ``files[]`` repeated; no comment body. Files "
        "land in the comments table with ``body=NULL`` and "
        "``target_kind='project'``."
    ),
    # Round-8: scope-aware via require_project_permission.
    dependencies=[Depends(require_project_permission(COMMENTS_CREATE))],
    openapi_extra=multipart_files_only_request_body(
        description=(
            "One or more files to attach to the project. Repeat the form "
            "key ``files`` for each file."
        ),
    ),
)
async def upload_project_attachments(
    project_uuid: str,
    controller: Annotated[ProjectController, Depends(get_project_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
    files: Annotated[List[UploadFile], File()],
):
    return controller.attachments.upload(
        "project", project_uuid, files,
        caller_user_id=caller_user_id or "",
    )
