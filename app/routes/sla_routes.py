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

import io
import json

from fastapi import APIRouter, Body, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field, ValidationError as PydanticValidationError

from app.clients import FileStoreUnavailable
from app.controllers.sla_attachment_controller import SlaAttachmentController
from app.controllers.sla_controller import SlaController
from app.core.errors import ValidationError
from app.core.openapi_examples import (
    RESP_CONFLICT,
    RESP_NOT_FOUND,
    RESP_SEED_DEFAULTS,
    RESP_SLA_DELETED,
    RESP_SLA_DETAIL,
    RESP_SLA_DSL,
    RESP_SLA_LIST,
    RESP_VALIDATION_FAIL,
    with_examples,
)
from app.core.response import api_response, hal_collection, hal_resource
from app.dependencies import (
    get_bearer_token,
    get_optional_current_user_id,
    get_sla_attachment_controller,
    get_sla_controller,
)
from app.schemas.sla import SlaFromRfpRequest, SlaOnboardRequest, SlaUpdateRequest


class SlaSeedRequest(BaseModel):
    """Body for ``POST /sla-masters/seed-defaults``.

    Idempotent bulk seed. The body is optional — omit it to seed every
    supported contract type, or list a subset under ``contract_types``.
    Pass ``overwrite: true`` to refresh basic RFP-presentation fields on
    SLAs that were seeded under an older version of the bundle.
    """
    model_config = {
        "json_schema_extra": {
            "example": {
                "contract_types": ["PMU"],
                "overwrite": True,
                "project_id": "31eefb48-c2d3-4a4a-8fc7-a23b84d08e45",
            }
        }
    }

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

@router.post(
    "/sla-masters",
    status_code=201,
    summary="Onboard a new SLA master (JSON, full technical schema)",
    responses=with_examples(
        (201, "SLA created.", RESP_SLA_DETAIL),
        (409, "Duplicate sla_ref for this project.", RESP_CONFLICT),
        (422, "Schema validation failed.", RESP_VALIDATION_FAIL),
    ),
)
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

@router.get(
    "/sla-masters",
    summary="List SLA masters",
    responses=with_examples(
        (200, "Paginated list of SLAs.", RESP_SLA_LIST),
    ),
)
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

@router.get(
    "/sla-masters/{sla_id}",
    summary="Get full SLA master detail",
    responses=with_examples(
        (200, "SLA detail with metrics / bands / placeholders.", RESP_SLA_DETAIL),
        (404, "SLA not found.", RESP_NOT_FOUND),
    ),
)
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

@router.get(
    "/sla-masters/{sla_id}/dsl",
    summary="Get auto-generated YAML DSL for an SLA master",
    responses=with_examples(
        (200, "DSL source + version.", RESP_SLA_DSL),
        (404, "SLA not found.", RESP_NOT_FOUND),
    ),
)
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

@router.patch(
    "/sla-masters/{sla_id}",
    summary="Update basic SLA master fields (regenerates DSL)",
    responses=with_examples(
        (200, "SLA updated.", RESP_SLA_DETAIL),
        (404, "SLA not found.", RESP_NOT_FOUND),
        (422, "Schema validation failed.", RESP_VALIDATION_FAIL),
    ),
)
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

@router.delete(
    "/sla-masters/{sla_id}",
    summary="Soft-delete an SLA master (sets status=DELETED)",
    responses=with_examples(
        (200, "SLA soft-deleted.", RESP_SLA_DELETED),
        (404, "SLA not found.", RESP_NOT_FOUND),
    ),
)
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
#
# The endpoint accepts *multipart/form-data* so the same request can carry
# both the SLA payload AND any image attachments — the FE onboarding
# wizard sends them together so users only ever have to click "Save"
# once. Fields:
#
#   payload (required, form-text)  JSON-encoded SlaFromRfpRequest body.
#   files   (optional, form-file)  Zero or more image files
#                                  (PNG / JPEG / WebP / GIF, max 10 MB each).
# ---------------------------------------------------------------------------

@router.post(
    "/sla-masters/from-rfp",
    status_code=201,
    summary="Onboard an SLA using the RFP-shape payload + optional image attachments",
    responses=with_examples(
        (201, "SLA created. attachments_uploaded carries one row per file with ok/error.",
         RESP_SLA_DETAIL),
        (409, "Duplicate sla_ref for this project.", RESP_CONFLICT),
        (422, "Payload JSON failed schema validation.", RESP_VALIDATION_FAIL),
    ),
)
async def onboard_sla_from_rfp(
    payload: str = Form(
        ...,
        description="JSON-encoded SlaFromRfpRequest body. See the schema at the "
                    "bottom of this docs page for the exact shape. Use the "
                    "example below as a template — copy, edit, paste.",
        examples=[json.dumps({
            "sla_ref": "PMU-SLA001",
            "title": "Non-submission of deliverable",
            "project_id": "31eefb48-c2d3-4a4a-8fc7-a23b84d08e45",
            "contract_type": "PMU",
            "category_code": "DELIVERABLE_SUBMISSION",
            "definition": "Failure to submit the deliverable on or before the agreed date.",
            "scope": "Applies to all Phase-1 deliverables D1 through D8.",
            "data_source": "Project Tracker — deliverable submission timestamps.",
            "calculation": "LD = 0.5% of deliverable cost per week of delay.",
            "reports_submitted_to": "Concerned UIDAI Stakeholders",
            "measurement_interval": "ONE_TIME",
            "reporting_interval": "QUARTERLY",
            "applied_on": "FIXED_AMOUNT",
            "effective_from": "2024-04-01",
            "measurement": {"display_name": "Weeks delayed", "unit": "weeks"},
            "target_rows": [],
            "linear_escalation": {
                "rate_percent": "0.5", "unit": "week",
                "grace_units": 0, "max_units": 20,
            },
            "placeholders": [
                {"key": "ld_base_amount",
                 "label": "Cost of this deliverable (₹)",
                 "type": "money", "required": True,
                 "default_from": None,
                 "help": "Used as the LD% base. RFP §5.28.2.b."},
            ],
        }, indent=2)],
    ),
    files: list[UploadFile] = File(
        default=[],
        description="Optional image attachments (image/png|jpeg|webp|gif).",
    ),
    ctrl: SlaController = Depends(get_sla_controller),
    attachment_ctrl: SlaAttachmentController = Depends(get_sla_attachment_controller),
    user_id: Optional[str] = Depends(get_optional_current_user_id),
    bearer_token: Optional[str] = Depends(get_bearer_token),
):
    # 1. Parse the JSON-encoded payload. We do this manually so the route
    # signature stays multipart-shaped instead of relying on FastAPI's
    # auto-JSON-body coercion (which would force a separate endpoint).
    try:
        parsed_dict = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"`payload` is not valid JSON: {exc}",
            code="payload_invalid_json",
        ) from exc
    try:
        parsed = SlaFromRfpRequest.model_validate(parsed_dict)
    except PydanticValidationError as exc:
        raise ValidationError(
            f"`payload` failed schema validation: {exc.errors()}",
            code="payload_schema_invalid",
        ) from exc

    # 2. Create the SLA first so attachments can FK back to its id.
    result = ctrl.onboard_from_rfp(parsed, created_by=user_id)

    # 3. Upload each attachment, in order, to whichever backend
    # FILE_STORE_SERVICE_URL / FILE_SERVER_LOCAL_FALLBACK_ENABLED resolves
    # to. Failures are collected and reported so the FE can show partial-
    # success — the SLA itself is already saved, so we don't roll back.
    upload_summary: list[dict] = []
    for f in files or []:
        if not f or not f.filename:
            continue
        content = await f.read()
        bio = io.BytesIO(content)
        try:
            att = attachment_ctrl.upload(
                result.id,
                file_obj=bio,
                filename=f.filename,
                mime_type=f.content_type or "",
                size_bytes=len(content),
                uploaded_by=user_id,
                bearer_token=bearer_token,
            )
            upload_summary.append({
                "filename": f.filename,
                "ok": True,
                "attachment_id": att.id,
            })
        except FileStoreUnavailable as exc:
            upload_summary.append({
                "filename": f.filename, "ok": False,
                "error": f"file-store unavailable: {exc}",
            })
        except Exception as exc:  # noqa: BLE001
            upload_summary.append({
                "filename": f.filename, "ok": False,
                "error": str(exc)[:200],
            })

    body = result.model_dump()
    # Expose the per-file outcomes so the FE can toast any individual
    # upload that failed without throwing away the successful SLA save.
    if upload_summary:
        body["attachments_uploaded"] = upload_summary

    return api_response(
        data=hal_resource(
            "SlaMaster",
            body,
            self_link=f"{_BASE}/{result.id}",
            extra_links=_sla_links(result.id),
        ),
        message=(
            f"SLA '{result.sla_ref}' onboarded with {len(upload_summary)} attachment(s)"
            if upload_summary
            else f"SLA '{result.sla_ref}' onboarded from RFP form"
        ),
        status=201,
    )


# ---------------------------------------------------------------------------
# POST /sla-masters/seed-defaults
# ---------------------------------------------------------------------------

@router.post(
    "/sla-masters/seed-defaults",
    status_code=201,
    summary="Seed RFP-default SLAs for one or more contract types (idempotent)",
    responses=with_examples(
        (201, "Seed summary: how many were seeded / overwritten / skipped / failed.",
         RESP_SEED_DEFAULTS),
    ),
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
