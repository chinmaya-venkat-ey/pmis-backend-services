"""Routes for the divisions catalog (CRUD + restore).

All endpoints under /masters/divisions/* per PLAN.md §2.4 (verb-suffix naming).
Auth gates: divisions:read for reads, divisions:manage for writes.
"""
from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, Depends, Query, status

from app.controllers.division_controller import DivisionController
from app.core.permissions import DIVISIONS_MANAGE, DIVISIONS_READ
from app.core.rbac import require_permission
from app.dependencies import get_division_controller
from app.schemas.division import (
    DivisionCreateRequest,
    DivisionResponse,
    DivisionUpdateRequest,
)


router = APIRouter(prefix="/divisions", tags=["divisions"])


@router.get(
    "",
    response_model_by_alias=True,
    summary="List divisions",
    description=(
        "Returns all divisions. By default omits inactive rows; pass "
        "`include_inactive=true` to see deactivated entries (used by admin "
        "screens). Requires divisions:read."
    ),
    dependencies=[Depends(require_permission(DIVISIONS_READ))],
)
def list_divisions(
    controller: Annotated[DivisionController, Depends(get_division_controller)],
    include_inactive: bool = Query(False, description="Include deactivated rows"),
) -> List[DivisionResponse]:
    return controller.list_(include_inactive=include_inactive)


@router.get(
    "/{code}",
    response_model_by_alias=True,
    summary="Get division details",
    description="Returns one division by code. 404 if not found. Requires divisions:read.",
    dependencies=[Depends(require_permission(DIVISIONS_READ))],
    responses={404: {"description": "Division code not found"}},
)
def get_division_details(
    code: str,
    controller: Annotated[DivisionController, Depends(get_division_controller)],
) -> DivisionResponse:
    return controller.get_details(code)


@router.post(
    "/create",
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="Create a division",
    description=(
        "Creates a new division. `code` is lowercase + URL-safe and must be "
        "unique. `email` + `phone_number` are required (doc 36). Requires "
        "divisions:manage."
    ),
    dependencies=[Depends(require_permission(DIVISIONS_MANAGE))],
    responses={409: {"description": "Division code already exists"}},
)
def create_division(
    payload: DivisionCreateRequest,
    controller: Annotated[DivisionController, Depends(get_division_controller)],
) -> DivisionResponse:
    return controller.create(payload)


@router.patch(
    "/{code}",
    response_model_by_alias=True,
    summary="Update a division",
    description=(
        "Partial update — only the fields you send are changed. `code` is "
        "immutable. Requires divisions:manage."
    ),
    dependencies=[Depends(require_permission(DIVISIONS_MANAGE))],
    responses={404: {"description": "Division code not found"}},
)
def update_division(
    code: str,
    payload: DivisionUpdateRequest,
    controller: Annotated[DivisionController, Depends(get_division_controller)],
) -> DivisionResponse:
    return controller.update(code, payload)


@router.delete(
    "/{code}",
    response_model_by_alias=True,
    summary="Delete (deactivate) a division",
    description=(
        "Soft-delete: flips `active=False`. Row is preserved for history. "
        "Use POST /restore to reverse. Requires divisions:manage."
    ),
    dependencies=[Depends(require_permission(DIVISIONS_MANAGE))],
    responses={404: {"description": "Division code not found"}},
)
def delete_division(
    code: str,
    controller: Annotated[DivisionController, Depends(get_division_controller)],
) -> DivisionResponse:
    return controller.delete(code)


@router.post(
    "/{code}/restore",
    response_model_by_alias=True,
    summary="Restore (reactivate) a division",
    description=(
        "Re-flips `active=True` on a previously deactivated division. "
        "Requires divisions:manage."
    ),
    dependencies=[Depends(require_permission(DIVISIONS_MANAGE))],
    responses={404: {"description": "Division code not found"}},
)
def restore_division(
    code: str,
    controller: Annotated[DivisionController, Depends(get_division_controller)],
) -> DivisionResponse:
    return controller.restore(code)
