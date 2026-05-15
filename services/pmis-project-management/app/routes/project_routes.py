"""Routes for /project/projects/* (CRUD + status transitions + vendor mapping)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status

from app.controllers.project_controller import ProjectController
from app.core.permissions import (
    PROJECTS_CLOSE,
    PROJECTS_CREATE,
    PROJECTS_DELETE_ALL,
    PROJECTS_DRAFT,
    PROJECTS_PUBLISH,
    PROJECTS_READ,
    PROJECTS_READ_ALL,
    PROJECTS_REOPEN,
    PROJECTS_UPDATE_VENDORS,
)
from app.core.rbac import (
    require_authenticated,
    require_permission,
    require_project_permission,
)
from app.dependencies import (
    get_caller_is_admin,
    get_caller_role_name,
    get_optional_current_user_id,
    get_project_controller,
)
from app.schemas.common import VendorIdsListRequest, VendorIdsListResponse
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectResponse,
    ProjectStatusTransitionRequest,
    ProjectUpdateRequest,
)


router = APIRouter(prefix="/projects", tags=["projects"])


@router.get(
    "/list",
    summary="List projects (filtered to caller's scope unless admin)",
    dependencies=[Depends(require_authenticated())],
)
def list_projects(
    offset: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    include_deleted: bool = Query(False),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
    caller_is_admin: bool = Depends(get_caller_is_admin),
    controller: ProjectController = Depends(get_project_controller),
):
    return controller.list_(
        offset=offset, page_size=page_size,
        status=status_filter, include_deleted=include_deleted,
        caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
    )


@router.post(
    "/create",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
    dependencies=[Depends(require_permission(PROJECTS_CREATE))],
)
def create_project(
    payload: ProjectCreateRequest,
    controller: ProjectController = Depends(get_project_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.create(payload, caller_user_id=caller_user_id)


@router.get(
    "/{project_uuid}/details",
    response_model=ProjectResponse,
    summary="Get project details",
    dependencies=[Depends(require_project_permission(PROJECTS_READ))],
    responses={404: {"description": "Project not found"}},
)
def get_project(
    project_uuid: str,
    controller: ProjectController = Depends(get_project_controller),
):
    return controller.get(project_uuid)


@router.patch(
    "/{project_uuid}/update",
    response_model=ProjectResponse,
    summary="Update a project's mutable fields (field-level RBAC)",
    description=(
        "Round-7 field-level model. Authenticated callers can hit this endpoint; "
        "for non-admins, each touched field must have its `projects:update:<field>` "
        "code held scoped to the project (or globally). 403 with `details.missing` "
        "lists the codes the caller lacks."
    ),
    dependencies=[Depends(require_authenticated())],
)
def update_project(
    project_uuid: str,
    payload: ProjectUpdateRequest,
    request: Request,
    controller: ProjectController = Depends(get_project_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.update(project_uuid, payload, request=request, caller_user_id=caller_user_id)


@router.delete(
    "/{project_uuid}/delete",
    response_model=ProjectResponse,
    summary="Soft-delete a project (admin/super_admin only)",
    dependencies=[Depends(require_permission(PROJECTS_DELETE_ALL))],
)
def delete_project(
    project_uuid: str,
    controller: ProjectController = Depends(get_project_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.delete(project_uuid, caller_user_id=caller_user_id)


@router.post(
    "/{project_uuid}/restore",
    response_model=ProjectResponse,
    summary="Restore a soft-deleted project",
    dependencies=[Depends(require_permission(PROJECTS_DELETE_ALL))],
)
def restore_project(
    project_uuid: str,
    controller: ProjectController = Depends(get_project_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.restore(project_uuid, caller_user_id=caller_user_id)


@router.post(
    "/{project_uuid}/status/transition",
    response_model=ProjectResponse,
    summary="Transition project status (FSM gated by permission code)",
    description=(
        "Round-7: FSM consults `masters.project_status_transitions(from_status, "
        "to_status, permission_code)`. The caller must hold the edge's "
        "`permission_code` (one of `projects:publish` / `:close` / `:reopen` / "
        "`:draft`) scoped to the project (or globally). Admins bypass."
    ),
    dependencies=[Depends(require_authenticated())],
    responses={409: {"description": "Transition not allowed under caller's permissions"}},
)
def transition_project_status(
    project_uuid: str,
    payload: ProjectStatusTransitionRequest,
    request: Request,
    controller: ProjectController = Depends(get_project_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
    caller_is_admin: bool = Depends(get_caller_is_admin),
):
    return controller.transition_status(
        project_uuid, payload, request=request,
        caller_user_id=caller_user_id,
        caller_is_admin=caller_is_admin,
    )


@router.put(
    "/{project_uuid}/vendors/replace",
    response_model=ProjectResponse,
    summary="Replace the M:N project <-> vendor mapping",
    dependencies=[Depends(require_project_permission(PROJECTS_UPDATE_VENDORS))],
)
def replace_project_vendors(
    project_uuid: str,
    payload: VendorIdsListRequest,
    controller: ProjectController = Depends(get_project_controller),
    caller_user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    return controller.set_vendors(project_uuid, payload.vendor_ids, caller_user_id=caller_user_id)
