"""Routes for the priorities catalog (doc 41)."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query, status

from app.controllers.priority_controller import PriorityController
from app.core.permissions import PRIORITIES_MANAGE, PRIORITIES_READ
from app.core.rbac import require_permission
from app.dependencies import get_priority_controller
from app.schemas.priority import (
    PriorityCreateRequest,
    PriorityResponse,
    PriorityUpdateRequest,
)


router = APIRouter(prefix="/priorities", tags=["priorities"])


@router.get(
    "",
    summary="List priorities",
    description="Returns priorities ordered by position. Requires priorities:read.",
    dependencies=[Depends(require_permission(PRIORITIES_READ))],
)
def list_priorities(
    include_inactive: bool = Query(False, description="Include deactivated rows"),
    controller: Annotated[PriorityController, Depends(get_priority_controller)] = Depends(get_priority_controller),
) -> List[PriorityResponse]:
    return controller.list_(include_inactive=include_inactive)


@router.get(
    "/{code}",
    summary="Get priority details",
    dependencies=[Depends(require_permission(PRIORITIES_READ))],
    responses={404: {"description": "Priority not found"}},
)
def get_priority_details(
    code: str,
    controller: Annotated[PriorityController, Depends(get_priority_controller)] = Depends(get_priority_controller),
) -> PriorityResponse:
    return controller.get_details(code)


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    summary="Create a priority",
    description="`code` is normalized to UPPERCASE server-side. Requires priorities:manage.",
    dependencies=[Depends(require_permission(PRIORITIES_MANAGE))],
    responses={409: {"description": "Priority code already exists"}},
)
def create_priority(
    payload: PriorityCreateRequest,
    controller: Annotated[PriorityController, Depends(get_priority_controller)] = Depends(get_priority_controller),
) -> PriorityResponse:
    return controller.create(payload)


@router.patch(
    "/{code}",
    summary="Update a priority",
    dependencies=[Depends(require_permission(PRIORITIES_MANAGE))],
    responses={404: {"description": "Priority not found"}},
)
def update_priority(
    code: str,
    payload: PriorityUpdateRequest,
    controller: Annotated[PriorityController, Depends(get_priority_controller)] = Depends(get_priority_controller),
) -> PriorityResponse:
    return controller.update(code, payload)


@router.delete(
    "/{code}",
    summary="Delete (deactivate) a priority",
    dependencies=[Depends(require_permission(PRIORITIES_MANAGE))],
    responses={404: {"description": "Priority not found"}},
)
def delete_priority(
    code: str,
    controller: Annotated[PriorityController, Depends(get_priority_controller)] = Depends(get_priority_controller),
) -> PriorityResponse:
    return controller.delete(code)


@router.post(
    "/{code}/restore",
    summary="Restore (reactivate) a priority",
    dependencies=[Depends(require_permission(PRIORITIES_MANAGE))],
    responses={404: {"description": "Priority not found"}},
)
def restore_priority(
    code: str,
    controller: Annotated[PriorityController, Depends(get_priority_controller)] = Depends(get_priority_controller),
) -> PriorityResponse:
    return controller.restore(code)
