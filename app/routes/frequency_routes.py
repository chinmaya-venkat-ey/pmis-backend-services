"""Routes for the frequencies catalog (Project-Finance payment screen)."""
from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, Depends, Query, status

from app.controllers.frequency_controller import FrequencyController
from app.core.permissions import FREQUENCIES_MANAGE, FREQUENCIES_READ
from app.core.rbac import require_permission
from app.dependencies import get_frequency_controller
from app.schemas.frequency import (
    FrequencyCreateRequest,
    FrequencyResponse,
    FrequencyUpdateRequest,
)


router = APIRouter(prefix="/frequencies", tags=["frequencies"])


@router.get(
    "",
    summary="List frequencies",
    description="Returns frequencies ordered by position. Requires frequencies:read.",
    dependencies=[Depends(require_permission(FREQUENCIES_READ))],
)
def list_frequencies(
    controller: Annotated[FrequencyController, Depends(get_frequency_controller)],
    include_inactive: bool = Query(False, description="Include deactivated rows"),
) -> List[FrequencyResponse]:
    return controller.list_(include_inactive=include_inactive)


@router.get(
    "/{code}",
    summary="Get frequency details",
    dependencies=[Depends(require_permission(FREQUENCIES_READ))],
    responses={404: {"description": "Frequency not found"}},
)
def get_frequency_details(
    code: str,
    controller: Annotated[FrequencyController, Depends(get_frequency_controller)],
) -> FrequencyResponse:
    return controller.get_details(code)


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    summary="Create a frequency",
    description="`code` is normalized to lowercase server-side. Requires frequencies:manage.",
    dependencies=[Depends(require_permission(FREQUENCIES_MANAGE))],
    responses={409: {"description": "Frequency code already exists"}},
)
def create_frequency(
    payload: FrequencyCreateRequest,
    controller: Annotated[FrequencyController, Depends(get_frequency_controller)],
) -> FrequencyResponse:
    return controller.create(payload)


@router.patch(
    "/{code}",
    summary="Update a frequency",
    dependencies=[Depends(require_permission(FREQUENCIES_MANAGE))],
    responses={404: {"description": "Frequency not found"}},
)
def update_frequency(
    code: str,
    payload: FrequencyUpdateRequest,
    controller: Annotated[FrequencyController, Depends(get_frequency_controller)],
) -> FrequencyResponse:
    return controller.update(code, payload)


@router.delete(
    "/{code}",
    summary="Delete (deactivate) a frequency",
    dependencies=[Depends(require_permission(FREQUENCIES_MANAGE))],
    responses={404: {"description": "Frequency not found"}},
)
def delete_frequency(
    code: str,
    controller: Annotated[FrequencyController, Depends(get_frequency_controller)],
) -> FrequencyResponse:
    return controller.delete(code)


@router.post(
    "/{code}/restore",
    summary="Restore (reactivate) a frequency",
    dependencies=[Depends(require_permission(FREQUENCIES_MANAGE))],
    responses={404: {"description": "Frequency not found"}},
)
def restore_frequency(
    code: str,
    controller: Annotated[FrequencyController, Depends(get_frequency_controller)],
) -> FrequencyResponse:
    return controller.restore(code)
