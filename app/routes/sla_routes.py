"""SLA master routes.

Endpoints:
  POST   /api/v3/sla-masters                        onboard a new SLA master
  GET    /api/v3/sla-masters                        list SLA masters (filterable)
  GET    /api/v3/sla-masters/{id}                   get full SLA detail
  GET    /api/v3/sla-masters/{id}/dsl               get auto-generated YAML DSL
  PATCH  /api/v3/sla-masters/{id}                   update basic fields (no sub-tables)
  DELETE /api/v3/sla-masters/{id}                   soft-delete
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.controllers.sla_controller import SlaController
from app.core.response import api_response, hal_collection, hal_resource
from app.dependencies import get_sla_controller
from app.schemas.sla import SlaOnboardRequest, SlaUpdateRequest

router = APIRouter(tags=["SLA Masters"])

_BASE = "/api/v3/sla-masters"


def _sla_links(sla_id: str) -> dict:
    return {
        "detail": {"href": f"{_BASE}/{sla_id}"},
        "dsl": {"href": f"{_BASE}/{sla_id}/dsl"},
    }


# ---------------------------------------------------------------------------
# POST /sla-masters
# ---------------------------------------------------------------------------

@router.post("/sla-masters", status_code=201, summary="Onboard a new SLA master")
def onboard_sla(
    payload: SlaOnboardRequest,
    ctrl: SlaController = Depends(get_sla_controller),
):
    result = ctrl.onboard(payload)
    return api_response(
        data=hal_resource(
            "SlaMaster",
            result.model_dump(),
            self_link=f"{_BASE}/{result.id}",
            extra_links=_sla_links(result.id),
        ),
        message=f"SLA '{result.sla_ref}' onboarded successfully",
        status=201,
    )


# ---------------------------------------------------------------------------
# GET /sla-masters
# ---------------------------------------------------------------------------

@router.get("/sla-masters", summary="List SLA masters")
def list_slas(
    contract_type: Optional[str] = Query(None, description="Filter by contract type (BSP|MSAP|MSIP|PMU)"),
    formula_type: Optional[str] = Query(
        None,
        description="Filter by formula type (band_accumulation|point_accumulation|fixed_escalation|wac)",
    ),
    status: Optional[str] = Query(None, description="Filter by status (ACTIVE|INACTIVE)"),
    offset: int = Query(1, ge=1, description="Page offset (1-based)"),
    page_size: int = Query(20, ge=1, le=200, alias="pageSize"),
    ctrl: SlaController = Depends(get_sla_controller),
):
    skip = (offset - 1) * page_size
    items, total = ctrl.list_slas(
        contract_type=contract_type,
        formula_type=formula_type,
        status=status,
        skip=skip,
        limit=page_size,
    )
    elements = [
        hal_resource(
            "SlaMaster",
            r.model_dump(),
            self_link=f"{_BASE}/{r.id}",
            extra_links=_sla_links(r.id),
        )
        for r in items
    ]
    return api_response(
        data=hal_collection(
            elements,
            total=total,
            offset=offset,
            page_size=page_size,
            base_path=_BASE,
        ),
        status=200,
    )


# ---------------------------------------------------------------------------
# GET /sla-masters/{id}
# ---------------------------------------------------------------------------

@router.get("/sla-masters/{sla_id}", summary="Get full SLA master detail")
def get_sla(
    sla_id: str,
    ctrl: SlaController = Depends(get_sla_controller),
):
    result = ctrl.get(sla_id)
    return api_response(
        data=hal_resource(
            "SlaMaster",
            result.model_dump(),
            self_link=f"{_BASE}/{sla_id}",
            extra_links=_sla_links(sla_id),
        ),
        status=200,
    )


# ---------------------------------------------------------------------------
# GET /sla-masters/{id}/dsl
# ---------------------------------------------------------------------------

@router.get("/sla-masters/{sla_id}/dsl", summary="Get auto-generated YAML DSL for an SLA master")
def get_sla_dsl(
    sla_id: str,
    ctrl: SlaController = Depends(get_sla_controller),
):
    result = ctrl.get_dsl(sla_id)
    return api_response(
        data=hal_resource(
            "SlaDsl",
            result.model_dump(),
            self_link=f"{_BASE}/{sla_id}/dsl",
        ),
        status=200,
    )


# ---------------------------------------------------------------------------
# PATCH /sla-masters/{id}
# ---------------------------------------------------------------------------

@router.patch("/sla-masters/{sla_id}", summary="Update basic SLA master fields (regenerates DSL)")
def update_sla(
    sla_id: str,
    payload: SlaUpdateRequest,
    ctrl: SlaController = Depends(get_sla_controller),
):
    result = ctrl.update(sla_id, payload)
    return api_response(
        data=hal_resource(
            "SlaMaster",
            result.model_dump(),
            self_link=f"{_BASE}/{sla_id}",
            extra_links=_sla_links(sla_id),
        ),
        message=f"SLA '{result.sla_ref}' updated (DSL v{result.dsl_version})",
        status=200,
    )


# ---------------------------------------------------------------------------
# DELETE /sla-masters/{id}
# ---------------------------------------------------------------------------

@router.delete("/sla-masters/{sla_id}", summary="Soft-delete an SLA master (sets status=DELETED)")
def delete_sla(
    sla_id: str,
    ctrl: SlaController = Depends(get_sla_controller),
):
    result = ctrl.delete(sla_id)
    return api_response(
        data=hal_resource(
            "SlaMaster",
            result.model_dump(),
            self_link=f"{_BASE}/{sla_id}",
        ),
        message=f"SLA '{result.sla_ref}' deleted",
        status=200,
    )
