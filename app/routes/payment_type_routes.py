"""Routes for the payment-types catalog (milestone Payment Type dropdown)."""
from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, Depends, Query, status

from app.controllers.payment_type_controller import PaymentTypeController
from app.core.permissions import PAYMENT_TYPES_MANAGE, PAYMENT_TYPES_READ
from app.core.rbac import require_permission, require_permission_any_scope
from app.dependencies import get_payment_type_controller
from app.schemas.payment_type import (
    PaymentTypeCreateRequest,
    PaymentTypeResponse,
    PaymentTypeUpdateRequest,
)


router = APIRouter(prefix="/payment-types", tags=["payment-types"])


@router.get(
    "",
    summary="List payment types",
    description="Returns payment types ordered by position. Requires payment_types:read.",
    dependencies=[Depends(require_permission_any_scope(PAYMENT_TYPES_READ))],
)
def list_payment_types(
    controller: Annotated[PaymentTypeController, Depends(get_payment_type_controller)],
    include_inactive: bool = Query(False, description="Include deactivated rows"),
) -> List[PaymentTypeResponse]:
    return controller.list_(include_inactive=include_inactive)


@router.get(
    "/{code}",
    summary="Get payment type details",
    dependencies=[Depends(require_permission_any_scope(PAYMENT_TYPES_READ))],
    responses={404: {"description": "Payment type not found"}},
)
def get_payment_type_details(
    code: str,
    controller: Annotated[PaymentTypeController, Depends(get_payment_type_controller)],
) -> PaymentTypeResponse:
    return controller.get_details(code)


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    summary="Create a payment type",
    description="`code` is normalized to lowercase server-side. Requires payment_types:manage.",
    dependencies=[Depends(require_permission(PAYMENT_TYPES_MANAGE))],
    responses={409: {"description": "Payment type code already exists"}},
)
def create_payment_type(
    payload: PaymentTypeCreateRequest,
    controller: Annotated[PaymentTypeController, Depends(get_payment_type_controller)],
) -> PaymentTypeResponse:
    return controller.create(payload)


@router.patch(
    "/{code}",
    summary="Update a payment type",
    dependencies=[Depends(require_permission(PAYMENT_TYPES_MANAGE))],
    responses={404: {"description": "Payment type not found"}},
)
def update_payment_type(
    code: str,
    payload: PaymentTypeUpdateRequest,
    controller: Annotated[PaymentTypeController, Depends(get_payment_type_controller)],
) -> PaymentTypeResponse:
    return controller.update(code, payload)


@router.delete(
    "/{code}",
    summary="Delete (deactivate) a payment type",
    dependencies=[Depends(require_permission(PAYMENT_TYPES_MANAGE))],
    responses={404: {"description": "Payment type not found"}},
)
def delete_payment_type(
    code: str,
    controller: Annotated[PaymentTypeController, Depends(get_payment_type_controller)],
) -> PaymentTypeResponse:
    return controller.delete(code)


@router.post(
    "/{code}/restore",
    summary="Restore (reactivate) a payment type",
    dependencies=[Depends(require_permission(PAYMENT_TYPES_MANAGE))],
    responses={404: {"description": "Payment type not found"}},
)
def restore_payment_type(
    code: str,
    controller: Annotated[PaymentTypeController, Depends(get_payment_type_controller)],
) -> PaymentTypeResponse:
    return controller.restore(code)
