"""Routes for the carry-forward-methods catalog (Project-Finance carry-forward
method selector)."""
from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, Depends, Query, status

from app.controllers.carry_forward_method_controller import CarryForwardMethodController
from app.core.permissions import CARRY_FORWARD_METHODS_MANAGE, CARRY_FORWARD_METHODS_READ
from app.core.rbac import require_permission, require_permission_any_scope
from app.dependencies import get_carry_forward_method_controller
from app.schemas.carry_forward_method import (
    CarryForwardMethodCreateRequest,
    CarryForwardMethodResponse,
    CarryForwardMethodUpdateRequest,
)


router = APIRouter(prefix="/carry-forward-methods", tags=["carry-forward-methods"])


@router.get(
    "",
    summary="List carry-forward methods",
    description="Ordered by position. Requires carry_forward_methods:read.",
    dependencies=[Depends(require_permission_any_scope(CARRY_FORWARD_METHODS_READ))],
)
def list_carry_forward_methods(
    controller: Annotated[CarryForwardMethodController, Depends(get_carry_forward_method_controller)],
    include_inactive: bool = Query(False, description="Include deactivated rows"),
) -> List[CarryForwardMethodResponse]:
    return controller.list_(include_inactive=include_inactive)


@router.get(
    "/{code}",
    summary="Get carry-forward method details",
    dependencies=[Depends(require_permission_any_scope(CARRY_FORWARD_METHODS_READ))],
    responses={404: {"description": "Carry-forward method not found"}},
)
def get_carry_forward_method_details(
    code: str,
    controller: Annotated[CarryForwardMethodController, Depends(get_carry_forward_method_controller)],
) -> CarryForwardMethodResponse:
    return controller.get_details(code)


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    summary="Create a carry-forward method",
    dependencies=[Depends(require_permission(CARRY_FORWARD_METHODS_MANAGE))],
    responses={409: {"description": "Carry-forward method code already exists"}},
)
def create_carry_forward_method(
    payload: CarryForwardMethodCreateRequest,
    controller: Annotated[CarryForwardMethodController, Depends(get_carry_forward_method_controller)],
) -> CarryForwardMethodResponse:
    return controller.create(payload)


@router.patch(
    "/{code}",
    summary="Update a carry-forward method",
    dependencies=[Depends(require_permission(CARRY_FORWARD_METHODS_MANAGE))],
    responses={404: {"description": "Carry-forward method not found"}},
)
def update_carry_forward_method(
    code: str,
    payload: CarryForwardMethodUpdateRequest,
    controller: Annotated[CarryForwardMethodController, Depends(get_carry_forward_method_controller)],
) -> CarryForwardMethodResponse:
    return controller.update(code, payload)


@router.delete(
    "/{code}",
    summary="Delete (deactivate) a carry-forward method",
    dependencies=[Depends(require_permission(CARRY_FORWARD_METHODS_MANAGE))],
    responses={404: {"description": "Carry-forward method not found"}},
)
def delete_carry_forward_method(
    code: str,
    controller: Annotated[CarryForwardMethodController, Depends(get_carry_forward_method_controller)],
) -> CarryForwardMethodResponse:
    return controller.delete(code)


@router.post(
    "/{code}/restore",
    summary="Restore (reactivate) a carry-forward method",
    dependencies=[Depends(require_permission(CARRY_FORWARD_METHODS_MANAGE))],
    responses={404: {"description": "Carry-forward method not found"}},
)
def restore_carry_forward_method(
    code: str,
    controller: Annotated[CarryForwardMethodController, Depends(get_carry_forward_method_controller)],
) -> CarryForwardMethodResponse:
    return controller.restore(code)
