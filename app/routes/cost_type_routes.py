"""Routes for the cost-types catalog (Project-Finance payment screen)."""
from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, Depends, Query, status

from app.controllers.cost_type_controller import CostTypeController
from app.core.permissions import COST_TYPES_MANAGE, COST_TYPES_READ
from app.core.rbac import require_permission, require_permission_any_scope
from app.dependencies import get_cost_type_controller
from app.schemas.cost_type import (
    CostTypeCreateRequest,
    CostTypeResponse,
    CostTypeUpdateRequest,
)


router = APIRouter(prefix="/cost-types", tags=["cost-types"])


@router.get(
    "",
    summary="List cost types",
    description="Returns cost types ordered by position. Requires cost_types:read.",
    dependencies=[Depends(require_permission_any_scope(COST_TYPES_READ))],
)
def list_cost_types(
    controller: Annotated[CostTypeController, Depends(get_cost_type_controller)],
    include_inactive: bool = Query(False, description="Include deactivated rows"),
) -> List[CostTypeResponse]:
    return controller.list_(include_inactive=include_inactive)


@router.get(
    "/{code}",
    summary="Get cost type details",
    dependencies=[Depends(require_permission_any_scope(COST_TYPES_READ))],
    responses={404: {"description": "Cost type not found"}},
)
def get_cost_type_details(
    code: str,
    controller: Annotated[CostTypeController, Depends(get_cost_type_controller)],
) -> CostTypeResponse:
    return controller.get_details(code)


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    summary="Create a cost type",
    description="`code` is normalized to lowercase server-side. Requires cost_types:manage.",
    dependencies=[Depends(require_permission(COST_TYPES_MANAGE))],
    responses={409: {"description": "Cost type code already exists"}},
)
def create_cost_type(
    payload: CostTypeCreateRequest,
    controller: Annotated[CostTypeController, Depends(get_cost_type_controller)],
) -> CostTypeResponse:
    return controller.create(payload)


@router.patch(
    "/{code}",
    summary="Update a cost type",
    dependencies=[Depends(require_permission(COST_TYPES_MANAGE))],
    responses={404: {"description": "Cost type not found"}},
)
def update_cost_type(
    code: str,
    payload: CostTypeUpdateRequest,
    controller: Annotated[CostTypeController, Depends(get_cost_type_controller)],
) -> CostTypeResponse:
    return controller.update(code, payload)


@router.delete(
    "/{code}",
    summary="Delete (deactivate) a cost type",
    dependencies=[Depends(require_permission(COST_TYPES_MANAGE))],
    responses={404: {"description": "Cost type not found"}},
)
def delete_cost_type(
    code: str,
    controller: Annotated[CostTypeController, Depends(get_cost_type_controller)],
) -> CostTypeResponse:
    return controller.delete(code)


@router.post(
    "/{code}/restore",
    summary="Restore (reactivate) a cost type",
    dependencies=[Depends(require_permission(COST_TYPES_MANAGE))],
    responses={404: {"description": "Cost type not found"}},
)
def restore_cost_type(
    code: str,
    controller: Annotated[CostTypeController, Depends(get_cost_type_controller)],
) -> CostTypeResponse:
    return controller.restore(code)
