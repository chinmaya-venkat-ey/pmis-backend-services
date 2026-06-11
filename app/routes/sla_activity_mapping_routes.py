"""Routes for SLA-Activity mapping CRUD + evaluation.

Endpoints
---------
POST   /api/v3/sla-activity-mappings                          create
GET    /api/v3/activities/{activity_id}/sla-mappings           list mappings on an activity
PATCH  /api/v3/sla-activity-mappings/{mapping_id}              update overrides / status
DELETE /api/v3/sla-activity-mappings/{mapping_id}              soft-unmap (status -> RETIRED)
POST   /api/v3/sla-activity-mappings/{mapping_id}/evaluate     evaluate one mapping
POST   /api/v3/activities/{activity_id}/evaluate               fan-out across all mappings
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from app.controllers.sla_activity_mapping_controller import (
    SlaActivityMappingController,
)
from app.core.openapi_examples import (
    RESP_ACTIVITY_EVALUATE,
    RESP_CONFLICT,
    RESP_MAPPING_DETAIL,
    RESP_MAPPING_EVALUATE,
    RESP_MAPPING_LIST,
    RESP_MAPPING_RETIRED,
    RESP_NOT_FOUND,
    RESP_VALIDATION_FAIL,
    with_examples,
)
from app.core.response import api_response, hal_collection, hal_resource
from app.dependencies import (
    get_bearer_token,
    get_optional_current_user_id,
    get_sla_activity_mapping_controller,
)
from app.schemas.sla_activity_mapping import (
    SlaActivityMappingCreateRequest,
    SlaActivityMappingUpdateRequest,
)
from app.schemas.sla_evaluation import (
    ActivityEvaluationRequest,
    BulkEvaluationRequest,
    MappingEvaluationRequest,
    SimpleEvaluationRequest,
)

router = APIRouter(tags=["SLA Activity Mappings"])


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.post(
    "/sla-activity-mappings",
    status_code=201,
    summary="Map an SLA master to an activity (with optional overrides)",
    responses=with_examples(
        (201, "Mapping created.", RESP_MAPPING_DETAIL),
        (404, "SLA not found.", RESP_NOT_FOUND),
        (409, "Same SLA already mapped to this activity for that effective_from.", RESP_CONFLICT),
        (422, "Schema validation failed.", RESP_VALIDATION_FAIL),
    ),
)
def create_mapping(
    payload: SlaActivityMappingCreateRequest,
    ctrl: SlaActivityMappingController = Depends(get_sla_activity_mapping_controller),
    user_id: Optional[str] = Depends(get_optional_current_user_id),
):
    result = ctrl.create(payload, created_by=user_id)
    return api_response(
        data=hal_resource(
            "SlaActivityMapping",
            result.model_dump(),
            self_link=f"/api/v3/sla-activity-mappings/{result.id}",
        ),
        message=f"SLA '{result.sla_ref}' mapped to activity '{result.activity_id}'",
        status=201,
    )


@router.get(
    "/activities/{activity_id}/sla-mappings",
    summary="List SLA mappings on an activity",
    responses=with_examples(
        (200, "List of mappings (oldest-first).", RESP_MAPPING_LIST),
    ),
)
def list_mappings(
    activity_id: str,
    active_only: bool = True,
    ctrl: SlaActivityMappingController = Depends(get_sla_activity_mapping_controller),
):
    items = ctrl.list_for_activity(activity_id, active_only=active_only)
    elements = [
        hal_resource(
            "SlaActivityMapping",
            r.model_dump(),
            self_link=f"/api/v3/sla-activity-mappings/{r.id}",
        )
        for r in items
    ]
    return api_response(
        data=hal_collection(elements, total=len(elements), page_size=len(elements) or 1),
        status=200,
    )


@router.get(
    "/sla-activity-mappings",
    summary="List SLA mappings, optionally filtered by SLA",
    responses=with_examples(
        (200, "All live mappings for the SLA, newest first.", RESP_MAPPING_LIST),
    ),
)
def list_all_mappings(
    sla_id: Optional[str] = None,
    ctrl: SlaActivityMappingController = Depends(get_sla_activity_mapping_controller),
):
    # The FE's SLA-detail view fetches `/sla-activity-mappings?sla_id=…` to
    # show "Mapped Activities" for the template being viewed.
    if sla_id:
        items = ctrl.list_for_sla(sla_id)
    else:
        items = []
    elements = [
        hal_resource(
            "SlaActivityMapping",
            r.model_dump(),
            self_link=f"/api/v3/sla-activity-mappings/{r.id}",
        )
        for r in items
    ]
    return api_response(
        data=hal_collection(elements, total=len(elements), page_size=len(elements) or 1),
        status=200,
    )


@router.patch(
    "/sla-activity-mappings/{mapping_id}",
    summary="Update mapping overrides, status, or effective_until",
    responses=with_examples(
        (200, "Mapping updated.", RESP_MAPPING_DETAIL),
        (404, "Mapping not found.", RESP_NOT_FOUND),
        (422, "Schema validation failed.", RESP_VALIDATION_FAIL),
    ),
)
def update_mapping(
    mapping_id: str,
    payload: SlaActivityMappingUpdateRequest,
    ctrl: SlaActivityMappingController = Depends(get_sla_activity_mapping_controller),
):
    result = ctrl.update(mapping_id, payload)
    return api_response(
        data=hal_resource(
            "SlaActivityMapping",
            result.model_dump(),
            self_link=f"/api/v3/sla-activity-mappings/{result.id}",
        ),
        message=f"Mapping '{mapping_id}' updated",
        status=200,
    )


@router.delete(
    "/sla-activity-mappings/{mapping_id}",
    summary="Soft-unmap (sets status=RETIRED)",
    responses=with_examples(
        (200, "Mapping retired.", RESP_MAPPING_RETIRED),
        (404, "Mapping not found.", RESP_NOT_FOUND),
    ),
)
def unmap(
    mapping_id: str,
    ctrl: SlaActivityMappingController = Depends(get_sla_activity_mapping_controller),
):
    result = ctrl.unmap(mapping_id)
    return api_response(
        data=hal_resource(
            "SlaActivityMapping",
            result.model_dump(),
            self_link=f"/api/v3/sla-activity-mappings/{result.id}",
        ),
        message=f"Mapping '{mapping_id}' retired",
        status=200,
    )


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------

@router.post(
    "/sla-activity-mappings/{mapping_id}/evaluate",
    deprecated=True,
    summary="DEPRECATED — evaluate via mapping_id + verbose observation array. "
            "Use POST /activities/{activity_id}/sla-evaluate/{sla_ref} which "
            "takes one `value` field and derives metric_key / shape / mapping_id "
            "automatically.",
    responses=with_examples(
        (200, "Severity result. No LD% — see the separate LD API.", RESP_MAPPING_EVALUATE),
        (404, "Mapping not found.", RESP_NOT_FOUND),
        (422, "Observation shape doesn't match the SLA's formula type.", RESP_VALIDATION_FAIL),
    ),
)
def evaluate_mapping(
    mapping_id: str,
    payload: MappingEvaluationRequest,
    ctrl: SlaActivityMappingController = Depends(get_sla_activity_mapping_controller),
    bearer_token: Optional[str] = Depends(get_bearer_token),
):
    # Bearer is forwarded to pmis-project-management so it can resolve the
    # activity's project_id under the caller's permissions.
    result = ctrl.evaluate_mapping(mapping_id, payload, bearer_token=bearer_token)
    return api_response(
        data=hal_resource(
            "MappingEvaluation",
            result.model_dump(),
            self_link=f"/api/v3/sla-activity-mappings/{mapping_id}/evaluate",
        ),
        status=200,
    )


@router.post(
    "/activities/{activity_id}/evaluate",
    deprecated=True,
    summary="DEPRECATED — verbose-shape bulk evaluation. Use "
            "POST /activities/{activity_id}/sla-evaluate which takes "
            "{observations: {sla_ref: value}} and lets the backend "
            "translate the values per SLA.",
    responses=with_examples(
        (200, "Per-mapping results + severity_breakdown summary.", RESP_ACTIVITY_EVALUATE),
        (422, "Schema validation failed.", RESP_VALIDATION_FAIL),
    ),
)
def evaluate_activity(
    activity_id: str,
    payload: ActivityEvaluationRequest,
    ctrl: SlaActivityMappingController = Depends(get_sla_activity_mapping_controller),
    bearer_token: Optional[str] = Depends(get_bearer_token),
):
    result = ctrl.evaluate_activity(activity_id, payload, bearer_token=bearer_token)
    return api_response(
        data=hal_resource(
            "ActivityEvaluation",
            result.model_dump(),
            self_link=f"/api/v3/activities/{activity_id}/evaluate",
        ),
        status=200,
    )


# ---------------------------------------------------------------------------
# Caller-friendly evaluation: keyed by sla_ref instead of mapping_id, with
# a one-field observation body that the backend infers the shape from.
# ---------------------------------------------------------------------------

@router.post(
    "/activities/{activity_id}/sla-evaluate/{sla_ref}",
    summary="Evaluate the severity of one SLA on this activity (sla_ref keyed)",
    description=(
        "The non-technical companion to "
        "POST /sla-activity-mappings/{mapping_id}/evaluate. The caller "
        "supplies the human-readable SLA ref (e.g. ``PMU-SLA005``) and a "
        "single ``value`` (number, list, or dict). The backend looks up "
        "the active mapping, reads the SLA's primary metric, and picks "
        "the right observation shape automatically — so the caller "
        "never has to think about metric_key / shape / "
        "single_value-vs-daily_values."
    ),
    responses=with_examples(
        (200, "Severity result.", RESP_MAPPING_EVALUATE),
        (404, "No active mapping for that sla_ref on this activity.", RESP_NOT_FOUND),
        (422, "Value shape doesn't match the SLA's formula.", RESP_VALIDATION_FAIL),
    ),
)
def evaluate_by_sla_ref(
    activity_id: str,
    sla_ref: str,
    payload: SimpleEvaluationRequest,
    ctrl: SlaActivityMappingController = Depends(get_sla_activity_mapping_controller),
    bearer_token: Optional[str] = Depends(get_bearer_token),
):
    result = ctrl.evaluate_by_sla_ref(
        activity_id, sla_ref, payload, bearer_token=bearer_token,
    )
    return api_response(
        data=hal_resource(
            "MappingEvaluation",
            result.model_dump(),
            self_link=f"/api/v3/activities/{activity_id}/sla-evaluate/{sla_ref}",
        ),
        status=200,
    )


@router.post(
    "/activities/{activity_id}/sla-evaluate",
    summary="Evaluate every SLA on this activity (sla_ref-keyed observations)",
    description=(
        "Bulk evaluation. The body's ``observations`` is a flat map "
        "``{sla_ref: value}`` where each ``value`` is a number, list, or "
        "dict (same rules as the single-SLA endpoint). SLAs that are "
        "attached to the activity but missing from ``observations`` are "
        "evaluated against stored observations (stubbed in this phase) "
        "and skipped if none exist. Use this when you want one round-trip "
        "to score everything attached to an activity at quarter-close time."
    ),
    responses=with_examples(
        (200, "Per-mapping severity results + severity_breakdown summary.",
         RESP_ACTIVITY_EVALUATE),
        (422, "Value shape doesn't match the SLA's formula.", RESP_VALIDATION_FAIL),
    ),
)
def evaluate_activity_bulk(
    activity_id: str,
    payload: BulkEvaluationRequest,
    ctrl: SlaActivityMappingController = Depends(get_sla_activity_mapping_controller),
    bearer_token: Optional[str] = Depends(get_bearer_token),
):
    result = ctrl.evaluate_activity_bulk(
        activity_id, payload, bearer_token=bearer_token,
    )
    return api_response(
        data=hal_resource(
            "ActivityEvaluation",
            result.model_dump(),
            self_link=f"/api/v3/activities/{activity_id}/sla-evaluate",
        ),
        status=200,
    )


# ---------------------------------------------------------------------------
# Form-schema endpoint — drives the FE's evaluate modal
# ---------------------------------------------------------------------------

@router.get(
    "/activities/{activity_id}/sla-evaluate/{sla_ref}/form-schema",
    summary="Get the form spec the FE renders for evaluating this SLA on this activity",
    description=(
        "Returns a renderer-friendly form description: the inputs to "
        "ask the user, the RFP severity bands to show alongside, the "
        "period defaults, and the URL to POST when the user clicks Run. "
        "The shape of ``inputs[]`` is driven by the SLA's stored config "
        "(metric, bands, lookup_table) — when the SLA is updated the form "
        "automatically reflects the change with no FE deploy."
    ),
)
def get_eval_form_schema(
    activity_id: str,
    sla_ref: str,
    ctrl: SlaActivityMappingController = Depends(get_sla_activity_mapping_controller),
    bearer_token: Optional[str] = Depends(get_bearer_token),
):
    result = ctrl.get_evaluation_form_schema(
        activity_id, sla_ref, bearer_token=bearer_token,
    )
    return api_response(
        data=hal_resource(
            "EvalFormSchema",
            result.model_dump(),
            self_link=f"/api/v3/activities/{activity_id}/sla-evaluate/{sla_ref}/form-schema",
        ),
        status=200,
    )
