"""ProjectLdConfig routes — LD financial terms per project.

Endpoints:
  POST   /api/v3/projects/{project_id}/ld-config    create LD config for a project
  GET    /api/v3/projects/{project_id}/ld-config    get LD config
  PATCH  /api/v3/projects/{project_id}/ld-config    update LD config
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.controllers.project_ld_config_controller import ProjectLdConfigController
from app.core.response import api_response, hal_resource
from app.dependencies import get_current_user_id, get_project_ld_config_controller
from app.schemas.project_ld_config import (
    ProjectLdConfigCreateRequest,
    ProjectLdConfigUpdateRequest,
)

router = APIRouter(tags=["Project LD Config"])


@router.post(
    "/projects/{project_id}/ld-config",
    status_code=201,
    summary="Create LD financial config for a project",
)
def create_project_ld_config(
    project_id: str,
    payload: ProjectLdConfigCreateRequest,
    caller_user_id: str = Depends(get_current_user_id),
    ctrl: ProjectLdConfigController = Depends(get_project_ld_config_controller),
):
    result = ctrl.create(project_id, payload, caller_user_id=caller_user_id)
    return api_response(
        data=hal_resource(
            "ProjectLdConfig",
            result.model_dump(),
            self_link=f"/api/v3/projects/{project_id}/ld-config",
        ),
        message="LD config created",
        status=201,
    )


@router.get(
    "/projects/{project_id}/ld-config",
    summary="Get LD financial config for a project",
)
def get_project_ld_config(
    project_id: str,
    ctrl: ProjectLdConfigController = Depends(get_project_ld_config_controller),
):
    result = ctrl.get(project_id)
    return api_response(
        data=hal_resource(
            "ProjectLdConfig",
            result.model_dump(),
            self_link=f"/api/v3/projects/{project_id}/ld-config",
        ),
        status=200,
    )


@router.patch(
    "/projects/{project_id}/ld-config",
    summary="Update LD financial config for a project",
)
def update_project_ld_config(
    project_id: str,
    payload: ProjectLdConfigUpdateRequest,
    caller_user_id: str = Depends(get_current_user_id),
    ctrl: ProjectLdConfigController = Depends(get_project_ld_config_controller),
):
    result = ctrl.update(project_id, payload, caller_user_id=caller_user_id)
    return api_response(
        data=hal_resource(
            "ProjectLdConfig",
            result.model_dump(),
            self_link=f"/api/v3/projects/{project_id}/ld-config",
        ),
        message="LD config updated",
        status=200,
    )
