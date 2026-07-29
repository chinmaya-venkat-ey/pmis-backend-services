"""Routes for the designations catalog."""
from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query, status

from app.controllers.designation_controller import DesignationController
from app.core.permissions import DESIGNATIONS_MANAGE, DESIGNATIONS_READ
from app.core.rbac import require_permission, require_permission_any_scope
from app.dependencies import get_designation_controller
from app.schemas.designation import (
    DesignationCreateRequest,
    DesignationResponse,
    DesignationUpdateRequest,
)


router = APIRouter(prefix="/designations", tags=["designations"])


@router.get(
    "",
    summary="List designations",
    description="Returns active designations (e.g. for a designation picker). Requires designations:read.",
    dependencies=[Depends(require_permission_any_scope(DESIGNATIONS_READ))],
)
def list_designations(
    controller: Annotated[DesignationController, Depends(get_designation_controller)],
    include_inactive: bool = Query(False, description="Include deactivated rows"),
    vendor_id: Optional[str] = Query(
        None,
        description="Filter to one organization's designations (masters.vendors.id)",
    ),
) -> List[DesignationResponse]:
    return controller.list_(include_inactive=include_inactive, vendor_id=vendor_id)


@router.get(
    "/{designation_id}",
    summary="Get designation details",
    dependencies=[Depends(require_permission_any_scope(DESIGNATIONS_READ))],
    responses={404: {"description": "Designation not found"}},
)
def get_designation_details(
    designation_id: str,
    controller: Annotated[DesignationController, Depends(get_designation_controller)],
) -> DesignationResponse:
    return controller.get_details(designation_id)


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    summary="Create a designation",
    description="Creates a designation. `code` must be unique. Requires designations:manage.",
    dependencies=[Depends(require_permission(DESIGNATIONS_MANAGE))],
    responses={409: {"description": "Designation code already exists"}},
)
def create_designation(
    payload: DesignationCreateRequest,
    controller: Annotated[DesignationController, Depends(get_designation_controller)],
) -> DesignationResponse:
    return controller.create(payload)


@router.patch(
    "/{designation_id}",
    summary="Update a designation",
    dependencies=[Depends(require_permission(DESIGNATIONS_MANAGE))],
    responses={404: {"description": "Designation not found"}},
)
def update_designation(
    designation_id: str,
    payload: DesignationUpdateRequest,
    controller: Annotated[DesignationController, Depends(get_designation_controller)],
) -> DesignationResponse:
    return controller.update(designation_id, payload)


@router.delete(
    "/{designation_id}",
    summary="Delete (deactivate) a designation",
    dependencies=[Depends(require_permission(DESIGNATIONS_MANAGE))],
    responses={404: {"description": "Designation not found"}},
)
def delete_designation(
    designation_id: str,
    controller: Annotated[DesignationController, Depends(get_designation_controller)],
) -> DesignationResponse:
    return controller.delete(designation_id)


@router.post(
    "/{designation_id}/restore",
    summary="Restore (reactivate) a designation",
    dependencies=[Depends(require_permission(DESIGNATIONS_MANAGE))],
    responses={404: {"description": "Designation not found"}},
)
def restore_designation(
    designation_id: str,
    controller: Annotated[DesignationController, Depends(get_designation_controller)],
) -> DesignationResponse:
    return controller.restore(designation_id)
