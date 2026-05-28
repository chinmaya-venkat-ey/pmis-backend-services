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
from app.core.response import api_response, hal_collection, hal_resource
from app.dependencies import (
    get_optional_current_user_id,
    get_sla_activity_mapping_controller,
)
from app.schemas.sla_activity_mapping import (
    SlaActivityMappingCreateRequest,
    SlaActivityMappingUpdateRequest,
)
from app.schemas.sla_evaluation import (
    ActivityEvaluationRequest,
    MappingEvaluationRequest,
)

router = APIRouter(tags=["SLA Activity Mappings"])


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.post(
    "/sla-activity-mappings",
    status_code=201,
    summary="Map an SLA master to an activity (with optional overrides)",
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


@router.patch(
    "/sla-activity-mappings/{mapping_id}",
    summary="Update mapping overrides, status, or effective_until",
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
    summary="Evaluate a single SLA mapping with the supplied observations",
)
def evaluate_mapping(
    mapping_id: str,
    payload: MappingEvaluationRequest,
    ctrl: SlaActivityMappingController = Depends(get_sla_activity_mapping_controller),
):
    result = ctrl.evaluate_mapping(mapping_id, payload)
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
    summary="Evaluate every active SLA mapping on an activity",
)
def evaluate_activity(
    activity_id: str,
    payload: ActivityEvaluationRequest,
    ctrl: SlaActivityMappingController = Depends(get_sla_activity_mapping_controller),
):
    result = ctrl.evaluate_activity(activity_id, payload)
    return api_response(
        data=hal_resource(
            "ActivityEvaluation",
            result.model_dump(),
            self_link=f"/api/v3/activities/{activity_id}/evaluate",
        ),
        status=200,
    )
