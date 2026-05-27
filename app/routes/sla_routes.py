"""SLA Definition routes — Phase 3.

Endpoints:
  POST   /api/v3/projects/{project_id}/slas                         create SLA from DSL
  POST   /api/v3/projects/{project_id}/slas/from-template           create SLA from template
  GET    /api/v3/projects/{project_id}/slas                         list SLAs
  GET    /api/v3/projects/{project_id}/slas/{sla_id}                get SLA (full detail)
  PATCH  /api/v3/projects/{project_id}/slas/{sla_id}                update SLA (new DSL version)
  GET    /api/v3/projects/{project_id}/slas/{sla_id}/dsl            get current DSL text
  GET    /api/v3/projects/{project_id}/slas/{sla_id}/asl            get current ASL JSON

  GET    /api/v3/sla-templates                                      list reusable SLA templates
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.controllers.sla_controller import SlaController
from app.core.response import api_response, hal_collection, hal_resource
from app.dependencies import get_current_user_id, get_sla_controller
from app.schemas.sla import (
    SlaCreateFromTemplateRequest,
    SlaCreateRequest,
    SlaUpdateRequest,
)

router = APIRouter(tags=["SLAs"])


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

@router.get("/sla-templates", summary="List SLA templates")
def list_sla_templates(
    applicable_to: Optional[str] = Query(None, description="Filter by applicable type e.g. BSP"),
    ctrl: SlaController = Depends(get_sla_controller),
):
    templates = ctrl.list_templates(applicable_to=applicable_to)
    elements = [
        hal_resource("SlaTemplate", t.model_dump(), self_link=f"/api/v3/sla-templates/{t.template_ref}")
        for t in templates
    ]
    return api_response(
        data=hal_collection(elements, total=len(elements), page_size=len(elements) or 1),
        status=200,
    )


# ---------------------------------------------------------------------------
# SLA CRUD
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/slas", status_code=201, summary="Create SLA from DSL")
def create_sla(
    project_id: str,
    payload: SlaCreateRequest,
    caller_user_id: str = Depends(get_current_user_id),
    ctrl: SlaController = Depends(get_sla_controller),
):
    result = ctrl.create(project_id, payload, caller_user_id=caller_user_id)
    return api_response(
        data=hal_resource(
            "SlaDefinition",
            result.model_dump(),
            self_link=f"/api/v3/projects/{project_id}/slas/{result.id}",
        ),
        message="SLA created successfully",
        status=201,
    )


@router.post(
    "/projects/{project_id}/slas/from-template",
    status_code=201,
    summary="Create SLA from template",
)
def create_sla_from_template(
    project_id: str,
    payload: SlaCreateFromTemplateRequest,
    caller_user_id: str = Depends(get_current_user_id),
    ctrl: SlaController = Depends(get_sla_controller),
):
    result = ctrl.create_from_template(project_id, payload, caller_user_id=caller_user_id)
    return api_response(
        data=hal_resource(
            "SlaDefinition",
            result.model_dump(),
            self_link=f"/api/v3/projects/{project_id}/slas/{result.id}",
        ),
        message="SLA created from template successfully",
        status=201,
    )


@router.get("/projects/{project_id}/slas", summary="List SLAs for project")
def list_slas(
    project_id: str,
    status: Optional[str] = Query(None),
    milestone_id: Optional[str] = Query(None),
    activity_id: Optional[str] = Query(None),
    ctrl: SlaController = Depends(get_sla_controller),
):
    slas = ctrl.list_(project_id, status=status, milestone_id=milestone_id, activity_id=activity_id)
    elements = [
        hal_resource(
            "SlaDefinition",
            s.model_dump(),
            self_link=f"/api/v3/projects/{project_id}/slas/{s.id}",
        )
        for s in slas
    ]
    return api_response(
        data=hal_collection(elements, total=len(elements), page_size=len(elements) or 1),
        status=200,
    )


@router.get("/projects/{project_id}/slas/{sla_id}", summary="Get SLA detail")
def get_sla(
    project_id: str,
    sla_id: str,
    ctrl: SlaController = Depends(get_sla_controller),
):
    result = ctrl.get(project_id, sla_id)
    return api_response(
        data=hal_resource(
            "SlaDefinition",
            result.model_dump(),
            self_link=f"/api/v3/projects/{project_id}/slas/{sla_id}",
        ),
        status=200,
    )


@router.patch("/projects/{project_id}/slas/{sla_id}", summary="Update SLA (new DSL version)")
def update_sla(
    project_id: str,
    sla_id: str,
    payload: SlaUpdateRequest,
    caller_user_id: str = Depends(get_current_user_id),
    ctrl: SlaController = Depends(get_sla_controller),
):
    result = ctrl.update(project_id, sla_id, payload, caller_user_id=caller_user_id)
    return api_response(
        data=hal_resource(
            "SlaDefinition",
            result.model_dump(),
            self_link=f"/api/v3/projects/{project_id}/slas/{sla_id}",
        ),
        message="SLA updated — new DSL version created",
        status=200,
    )


@router.get("/projects/{project_id}/slas/{sla_id}/dsl", summary="Get current DSL text")
def get_sla_dsl(
    project_id: str,
    sla_id: str,
    ctrl: SlaController = Depends(get_sla_controller),
):
    dsl_text = ctrl.get_dsl(project_id, sla_id)
    return api_response(
        data={"sla_id": sla_id, "dsl": dsl_text},
        status=200,
    )


@router.get("/projects/{project_id}/slas/{sla_id}/asl", summary="Get current ASL JSON")
def get_sla_asl(
    project_id: str,
    sla_id: str,
    ctrl: SlaController = Depends(get_sla_controller),
):
    asl = ctrl.get_asl(project_id, sla_id)
    return api_response(
        data={"sla_id": sla_id, "asl": asl},
        status=200,
    )
