"""Routes for the vendors catalog (CRUD + restore + projects sub-listing).

Vendors are the org-tier entity referenced by user.user_role_assignments.organization_id
and project.project_vendors.vendor_id. Soft-delete is audit-rich (deleted_at + deleted_by)
per Q1 — vendors are managed more carefully than other catalogs.

Auth gates: vendors:read for reads, vendors:manage for writes.
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query, Request, status

from app.controllers.vendor_controller import VendorController
from app.core.permissions import VENDORS_MANAGE, VENDORS_READ
from app.core.rbac import require_permission
from app.dependencies import get_vendor_controller
from app.schemas.vendor import (
    VendorCreateRequest,
    VendorResponse,
    VendorUpdateRequest,
)
from app.schemas.vendor_project import VendorProjectSummary


router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get(
    "/list",
    response_model=List[VendorResponse],
    summary="List vendors",
    description=(
        "Returns vendors visible to the caller. Non-admin users currently "
        "see only their own vendor (Option C row-level scoping — refined "
        "during user-svc port). Requires vendors:read."
    ),
    dependencies=[Depends(require_permission(VENDORS_READ))],
)
def list_vendors(
    request: Request,
    include_inactive: bool = Query(False, description="Include deactivated rows"),
    include_deleted: bool = Query(False, description="Include soft-deleted rows"),
    controller: VendorController = Depends(get_vendor_controller),
) -> List[VendorResponse]:
    # Row-level scope hooks from request.state (hydrated by AuthMiddleware).
    # `caller_vendor_id` lookup will land when user-svc populates it; for now
    # admins see all, non-admins see all (placeholder behavior).
    return controller.list_(
        include_inactive=include_inactive,
        include_deleted=include_deleted,
        caller_vendor_id=getattr(request.state, "user_vendor_id", None),
        is_admin=getattr(request.state, "is_admin", False),
    )


@router.get(
    "/{vendor_id}/details",
    response_model=VendorResponse,
    summary="Get vendor details",
    description="Returns one vendor by UUID. 404 if not found. Requires vendors:read.",
    dependencies=[Depends(require_permission(VENDORS_READ))],
    responses={404: {"description": "Vendor not found"}},
)
def get_vendor_details(
    vendor_id: str,
    controller: VendorController = Depends(get_vendor_controller),
) -> VendorResponse:
    return controller.get_details(vendor_id)


@router.get(
    "/{vendor_id}/projects/list",
    response_model=List[VendorProjectSummary],
    summary="List the projects this vendor is mapped to",
    description=(
        "Returns the slim project list a vendor participates in. Joins "
        "cross-schema via project.project_vendors → project.projects. "
        "Excludes soft-deleted projects. Requires vendors:read."
    ),
    dependencies=[Depends(require_permission(VENDORS_READ))],
    responses={404: {"description": "Vendor not found"}},
)
def list_projects_for_vendor(
    vendor_id: str,
    controller: VendorController = Depends(get_vendor_controller),
) -> List[VendorProjectSummary]:
    return controller.list_projects(vendor_id)


@router.post(
    "/create",
    response_model=VendorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a vendor",
    description=(
        "Creates a new vendor. `name` must be unique. `vendor_code` is "
        "auto-generated separately (post-Doc-25 — null at create time). "
        "Requires vendors:manage."
    ),
    dependencies=[Depends(require_permission(VENDORS_MANAGE))],
    responses={409: {"description": "Vendor name already in use"}},
)
def create_vendor(
    payload: VendorCreateRequest,
    controller: VendorController = Depends(get_vendor_controller),
) -> VendorResponse:
    return controller.create(payload)


@router.patch(
    "/{vendor_id}/update",
    response_model=VendorResponse,
    summary="Update a vendor",
    description=(
        "Partial update. `name` is unique — collision returns 409. "
        "Requires vendors:manage."
    ),
    dependencies=[Depends(require_permission(VENDORS_MANAGE))],
    responses={
        404: {"description": "Vendor not found"},
        409: {"description": "Vendor name already in use"},
    },
)
def update_vendor(
    vendor_id: str,
    payload: VendorUpdateRequest,
    controller: VendorController = Depends(get_vendor_controller),
) -> VendorResponse:
    return controller.update(vendor_id, payload)


@router.delete(
    "/{vendor_id}/delete",
    response_model=VendorResponse,
    summary="Delete (soft-delete) a vendor",
    description=(
        "Soft-delete: sets `deleted_at`, `deleted_by`, and flips `active=False`. "
        "Project + milestone mappings to the vendor are preserved (history-safe). "
        "Requires vendors:manage."
    ),
    dependencies=[Depends(require_permission(VENDORS_MANAGE))],
    responses={404: {"description": "Vendor not found"}},
)
def delete_vendor(
    vendor_id: str,
    request: Request,
    controller: VendorController = Depends(get_vendor_controller),
) -> VendorResponse:
    deleted_by_user_id = getattr(request.state, "user_id", None) or ""
    return controller.delete(vendor_id, deleted_by_user_id=deleted_by_user_id)


@router.post(
    "/{vendor_id}/restore",
    response_model=VendorResponse,
    summary="Restore a soft-deleted vendor",
    description=(
        "Clears `deleted_at` + `deleted_by` and flips `active=True`. "
        "Requires vendors:manage."
    ),
    dependencies=[Depends(require_permission(VENDORS_MANAGE))],
    responses={404: {"description": "Vendor not found"}},
)
def restore_vendor(
    vendor_id: str,
    controller: VendorController = Depends(get_vendor_controller),
) -> VendorResponse:
    return controller.restore(vendor_id)
