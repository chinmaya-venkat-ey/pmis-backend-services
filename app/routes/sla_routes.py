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
from app.schemas.sla import SlaFromRfpRequest, SlaOnboardRequest, SlaUpdateRequest


class SlaSeedRequest(BaseModel):
    """Body for ``POST /sla-masters/seed-defaults``.

    The body is optional. Three equivalent ways to seed everything:

      * Omit the body / send ``{}``
      * Send ``{"contract_types": ["all"]}`` (or ``["ALL"]`` / ``["*"]``)
      * Send ``{"contract_types": ["BSP","MSAP","MSIP","PMU"]}``

    To seed a subset, list just those codes. Pass ``overwrite: true`` to refresh
    the basic RFP-presentation fields on SLAs that were seeded under an older
    version of the seed bundle.
    """
    contract_types: Optional[List[str]] = Field(
        default=None,
        description="Contract codes to seed. Allowed values: BSP, MSAP, MSIP, PMU, "
                    "or the special token 'all' (case-insensitive, also '*') which "
                    "expands to every supported contract. Omit or send an empty list "
                    "for the same effect as 'all'.",
        examples=[["all"], ["BSP", "MSAP"]],
    )
    overwrite: bool = Field(
        default=False,
        description="When true, SLAs that already exist are refreshed in place with "
                    "the latest seed values for the basic RFP fields (description, "
                    "category, scope_text, data_source, calculation_method, "
                    "reports_submitted_to, cadence, ld_computation_base, dates, "
                    "project_id, placeholders). Sub-tables (metrics / bands / "
                    "lookup / parameters / guards) are NOT touched; delete then "
                    "re-seed if you need a full reset.",
    )
    project_id: Optional[str] = Field(
        default=None,
        max_length=36,
        description="When supplied, every seeded SLA is stamped with this project_id "
                    "so the bundle becomes 'this project's SLA catalogue'. Leave "
                    "empty to seed as catalog templates (the legacy behaviour).",
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
    project_id: Optional[str] = Query(
        None,
        description="Filter by the project (PMC contract) that owns the SLA. "
                    "Preferred over contract_type when the FE knows which project the user "
                    "is working in.",
    ),
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
        project_id=project_id,
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
# POST /sla-masters/from-rfp — non-technical onboarding entry point
#
# Mirrors the UIDAI PMU SLA tables in the RFP 1:1. Use this from the FE
# wizard so users can fill the form by copying directly from the contract
# PDF without ever seeing metric_key, sort_order, range_min, etc. Backend
# derives those from the friendly fields the user provides.
# ---------------------------------------------------------------------------

@router.post(
    "/sla-masters/from-rfp",
    status_code=201,
    summary="Onboard an SLA using the RFP-shape payload (non-technical form)",
)
def onboard_sla_from_rfp(
    payload: SlaFromRfpRequest,
    ctrl: SlaController = Depends(get_sla_controller),
):
    result = ctrl.onboard_from_rfp(payload)
    return api_response(
        data=hal_resource(
            "SlaMaster",
            result.model_dump(),
            self_link=f"{_BASE}/{result.id}",
            extra_links=_sla_links(result.id),
        ),
        message=f"SLA '{result.sla_ref}' onboarded from RFP form",
        status=201,
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
    summary = ctrl.seed_defaults(
        payload.contract_types,
        overwrite=payload.overwrite,
        project_id=payload.project_id,
    )
    parts = [f"seeded {summary['seeded']} new"]
    if summary.get("overwritten"):
        parts.append(f"refreshed {summary['overwritten']} existing")
    parts.append(f"skipped {summary['skipped_existing']} existing")
    if summary["failed"]:
        parts.append(f"failed {len(summary['failed'])}")
    parts.append(f"(of {summary['total_candidates']} candidates)")
    msg = ", ".join(parts)
    return api_response(
        data=hal_resource(
            "SlaSeedSummary",
            summary,
            self_link=f"{_BASE}/seed-defaults",
        ),
        message=msg,
        status=201,
    )
