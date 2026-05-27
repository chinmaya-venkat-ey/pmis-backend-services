"""Metric Observation routes — Phase 4.

Endpoints:
  POST   /api/v3/projects/{project_id}/slas/{sla_id}/observations               submit observation
  GET    /api/v3/projects/{project_id}/slas/{sla_id}/observations               list (paginated)
  GET    /api/v3/projects/{project_id}/slas/{sla_id}/observations/{obs_id}      get detail + band counts
  PATCH  /api/v3/projects/{project_id}/slas/{sla_id}/observations/{obs_id}      update PENDING obs
  POST   /api/v3/projects/{project_id}/slas/{sla_id}/observations/{obs_id}/approve
  POST   /api/v3/projects/{project_id}/slas/{sla_id}/observations/{obs_id}/reject
  POST   /api/v3/projects/{project_id}/slas/{sla_id}/observations/{obs_id}/exclude
  POST   /api/v3/projects/{project_id}/slas/{sla_id}/observations/{obs_id}/band-counts
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.controllers.observation_controller import ObservationController
from app.core.response import api_response, hal_collection, hal_resource
from app.dependencies import get_current_user_id, get_observation_controller
from app.schemas.observation import (
    BandCountSubmitRequest,
    ObservationCreateRequest,
    ObservationExcludeRequest,
    ObservationUpdateRequest,
)

router = APIRouter(tags=["Observations"])


# ---------------------------------------------------------------------------
# Submit / list
# ---------------------------------------------------------------------------

@router.post(
    "/projects/{project_id}/slas/{sla_id}/observations",
    status_code=201,
    summary="Submit a metric observation",
)
def create_observation(
    project_id: str,
    sla_id: str,
    payload: ObservationCreateRequest,
    caller_user_id: str = Depends(get_current_user_id),
    ctrl: ObservationController = Depends(get_observation_controller),
):
    result = ctrl.create(
        project_id, sla_id, payload, caller_user_id=caller_user_id
    )
    return api_response(
        data=hal_resource(
            "MetricObservation",
            result.model_dump(),
            self_link=f"/api/v3/projects/{project_id}/slas/{sla_id}/observations/{result.id}",
        ),
        message="Observation submitted successfully",
        status=201,
    )


@router.get(
    "/projects/{project_id}/slas/{sla_id}/observations",
    summary="List observations for an SLA",
)
def list_observations(
    project_id: str,
    sla_id: str,
    status: Optional[str] = Query(None, description="Filter by status: PENDING, APPROVED, REJECTED"),
    metric_key: Optional[str] = Query(None),
    period_start: Optional[date] = Query(None),
    period_end: Optional[date] = Query(None),
    offset: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctrl: ObservationController = Depends(get_observation_controller),
):
    items, total = ctrl.list_(
        project_id,
        sla_id,
        status=status,
        metric_key=metric_key,
        period_start=period_start,
        period_end=period_end,
        offset=offset,
        page_size=page_size,
    )
    base = f"/api/v3/projects/{project_id}/slas/{sla_id}/observations"
    elements = [
        hal_resource(
            "MetricObservation",
            item.model_dump(),
            self_link=f"{base}/{item.id}",
        )
        for item in items
    ]
    return api_response(
        data=hal_collection(
            elements,
            total=total,
            offset=offset,
            page_size=page_size,
            base_path=base,
        ),
        status=200,
    )


# ---------------------------------------------------------------------------
# Get / update single observation
# ---------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/slas/{sla_id}/observations/{observation_id}",
    summary="Get observation detail with band counts",
)
def get_observation(
    project_id: str,
    sla_id: str,
    observation_id: str,
    ctrl: ObservationController = Depends(get_observation_controller),
):
    result = ctrl.get(project_id, sla_id, observation_id)
    return api_response(
        data=hal_resource(
            "MetricObservation",
            result.model_dump(),
            self_link=f"/api/v3/projects/{project_id}/slas/{sla_id}/observations/{observation_id}",
        ),
        status=200,
    )


@router.patch(
    "/projects/{project_id}/slas/{sla_id}/observations/{observation_id}",
    summary="Update a PENDING observation",
)
def update_observation(
    project_id: str,
    sla_id: str,
    observation_id: str,
    payload: ObservationUpdateRequest,
    caller_user_id: str = Depends(get_current_user_id),
    ctrl: ObservationController = Depends(get_observation_controller),
):
    result = ctrl.update(
        project_id, sla_id, observation_id, payload, caller_user_id=caller_user_id
    )
    return api_response(
        data=hal_resource(
            "MetricObservation",
            result.model_dump(),
            self_link=f"/api/v3/projects/{project_id}/slas/{sla_id}/observations/{observation_id}",
        ),
        status=200,
    )


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

@router.post(
    "/projects/{project_id}/slas/{sla_id}/observations/{observation_id}/approve",
    summary="Approve a PENDING observation",
)
def approve_observation(
    project_id: str,
    sla_id: str,
    observation_id: str,
    caller_user_id: str = Depends(get_current_user_id),
    ctrl: ObservationController = Depends(get_observation_controller),
):
    result = ctrl.approve(
        project_id, sla_id, observation_id, caller_user_id=caller_user_id
    )
    return api_response(
        data=hal_resource("MetricObservation", result.model_dump()),
        message="Observation approved",
        status=200,
    )


@router.post(
    "/projects/{project_id}/slas/{sla_id}/observations/{observation_id}/reject",
    summary="Reject a PENDING observation",
)
def reject_observation(
    project_id: str,
    sla_id: str,
    observation_id: str,
    caller_user_id: str = Depends(get_current_user_id),
    ctrl: ObservationController = Depends(get_observation_controller),
):
    result = ctrl.reject(
        project_id, sla_id, observation_id, caller_user_id=caller_user_id
    )
    return api_response(
        data=hal_resource("MetricObservation", result.model_dump()),
        message="Observation rejected",
        status=200,
    )


@router.post(
    "/projects/{project_id}/slas/{sla_id}/observations/{observation_id}/exclude",
    summary="Set or clear the exclusion flag (force majeure, grace period)",
)
def exclude_observation(
    project_id: str,
    sla_id: str,
    observation_id: str,
    payload: ObservationExcludeRequest,
    ctrl: ObservationController = Depends(get_observation_controller),
):
    result = ctrl.exclude(project_id, sla_id, observation_id, payload)
    action = "excluded from" if payload.excluded else "re-included in"
    return api_response(
        data=hal_resource("MetricObservation", result.model_dump()),
        message=f"Observation {action} SLA evaluation",
        status=200,
    )


# ---------------------------------------------------------------------------
# Band counts (band_accumulation SLAs only — BSP / MSIP)
# ---------------------------------------------------------------------------

@router.post(
    "/projects/{project_id}/slas/{sla_id}/observations/{observation_id}/band-counts",
    summary="Submit band counts for a PENDING band_accumulation observation",
)
def submit_band_counts(
    project_id: str,
    sla_id: str,
    observation_id: str,
    payload: BandCountSubmitRequest,
    ctrl: ObservationController = Depends(get_observation_controller),
):
    band_counts = ctrl.submit_band_counts(
        project_id, sla_id, observation_id, payload
    )
    return api_response(
        data={
            "observation_id": observation_id,
            "band_counts": [bc.model_dump() for bc in band_counts],
        },
        message=f"{len(band_counts)} band count(s) saved",
        status=200,
    )
