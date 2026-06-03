"""SLA master routes.

Endpoints:
  POST   /api/v3/sla-masters                        onboard a new SLA master
  POST   /api/v3/sla-masters/seed-defaults          idempotent bulk seed (RFP defaults)
  GET    /api/v3/sla-masters                        list SLA masters (filterable)
  GET    /api/v3/sla-masters/{id}                   get full SLA detail
  GET    /api/v3/sla-masters/{id}/dsl               get auto-generated YAML DSL
  PATCH  /api/v3/sla-masters/{id}                   update basic fields (no sub-tables)
  DELETE /api/v3/sla-masters/{id}                   soft-delete
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field

from app.controllers.sla_controller import SlaController
from app.core.response import api_response, hal_collection, hal_resource
from app.dependencies import get_sla_controller
from app.schemas.sla import SlaOnboardRequest, SlaUpdateRequest


class SlaSeedRequest(BaseModel):
    """Body for ``POST /sla-masters/seed-defaults``.

    The body is optional. Three equivalent ways to seed everything:

      * Omit the body / send ``{}``
      * Send ``{"contract_types": ["all"]}`` (or ``["ALL"]`` / ``["*"]``)
      * Send ``{"contract_types": ["BSP","MSAP","MSIP","PMU"]}``

    To seed a subset, list just those codes.
    """
    contract_types: Optional[List[str]] = Field(
        default=None,
        description="Contract codes to seed. Allowed values: BSP, MSAP, MSIP, PMU, "
                    "or the special token 'all' (case-insensitive, also '*') which "
                    "expands to every supported contract. Omit or send an empty list "
                    "for the same effect as 'all'.",
        examples=[["all"], ["BSP", "MSAP"]],
    )

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


# ---------------------------------------------------------------------------
# POST /sla-masters/seed-defaults
# ---------------------------------------------------------------------------

@router.post(
    "/sla-masters/seed-defaults",
    status_code=201,
    summary="Seed RFP-default SLAs for one or more contract types (idempotent)",
)
def seed_sla_defaults(
    payload: SlaSeedRequest = Body(default_factory=SlaSeedRequest),
    ctrl: SlaController = Depends(get_sla_controller),
):
    """Bulk-onboard the SLAs bundled in ``app/seed_data/sla_master_seeds.py``.

    Safe to call repeatedly: SLAs that already exist are counted under
    ``skipped_existing`` and not re-created. Use this once per environment to
    populate a fresh contract DB with the 36 RFP-default SLAs across BSP,
    MSAP, MSIP and PMU.
    """
    summary = ctrl.seed_defaults(payload.contract_types)
    msg = (
        f"Seeded {summary['seeded']} new, skipped {summary['skipped_existing']} existing"
        + (f", failed {len(summary['failed'])}" if summary["failed"] else "")
        + f" (of {summary['total_candidates']} candidates)"
    )
    return api_response(
        data=hal_resource(
            "SlaSeedSummary",
            summary,
            self_link=f"{_BASE}/seed-defaults",
        ),
        message=msg,
        status=201,
    )
