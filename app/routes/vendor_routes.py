"""Routes for the vendors catalog — wire shape matches monolith /api/v3/vendors.

Response shapes:
  List / projects  → {_type:"Collection", total, count, _embedded:{elements:[...]}}
  Single vendor    → {_type:"Vendor", id, vendorCode, name, ..., projects:[...]}
  Delete           → null data (no-content equivalent)
  Users            → [{id, login, email, ...}]

All responses are wrapped in the PMIS envelope by HalApiRoute:
  {data: <above>, message: null, error: null, status: 200}
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.controllers.vendor_controller import VendorController
from app.core.permissions import VENDORS_MANAGE, VENDORS_READ
from app.core.rbac import require_permission, require_permission_any_scope
from app.dependencies import get_vendor_controller
from app.schemas.vendor import VendorCreateRequest, VendorUpdateRequest
from app.schemas.vendor_user import VendorUserSummary


router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get(
    "",
    summary="List vendors (newest first)",
    description=(
        "Returns vendors that are not soft-deleted, ordered by createdAt "
        "descending. Active and inactive vendors are returned by default. "
        "Pass active_only=true (picker dropdowns) to show only active. "
        "Requires vendors:read."
    ),
    dependencies=[Depends(require_permission_any_scope(VENDORS_READ))],
)
def list_vendors(
    request: Request,
    controller: Annotated[VendorController, Depends(get_vendor_controller)],
    active_only: bool = Query(
        False,
        description="When true, return only active vendors. Default false shows all (active + inactive).",
    ),
) -> Dict[str, Any]:
    held = getattr(request.state, "user_permissions", None) or set()
    return controller.list_(
        active_only=active_only,
        caller_vendor_id=getattr(request.state, "user_vendor_id", None),
        is_admin=getattr(request.state, "is_admin", False),
        # §3.1 (2026-06-02 audit) item 7: broad view requires vendors:manage
        # (admin/super_admin hold it via r005). Non-manage callers see only
        # their own vendor via caller_vendor_id.
        caller_can_see_all=(VENDORS_MANAGE in held),
    )


@router.get(
    "/{vendor_id}",
    summary="Get vendor details",
    description="Returns one vendor by UUID with embedded projects. 404 if not found. Requires vendors:read.",
    dependencies=[Depends(require_permission_any_scope(VENDORS_READ))],
    responses={404: {"description": "Vendor not found"}},
)
def get_vendor_details(
    vendor_id: str,
    controller: Annotated[VendorController, Depends(get_vendor_controller)],
) -> Dict[str, Any]:
    return controller.get_details(vendor_id)


@router.get(
    "/{vendor_id}/users",
    summary="List users belonging to this vendor",
    description=(
        "Returns all active (non-deleted) users whose vendor_id matches the given "
        "vendor UUID. Cross-schema read from users.users. Requires vendors:read."
    ),
    dependencies=[Depends(require_permission_any_scope(VENDORS_READ))],
    responses={404: {"description": "Vendor not found"}},
)
def list_users_for_vendor(
    vendor_id: str,
    controller: Annotated[VendorController, Depends(get_vendor_controller)],
) -> List[VendorUserSummary]:
    return controller.list_users(vendor_id)


@router.get(
    "/{vendor_id}/projects",
    summary="List the projects this vendor is mapped to",
    description=(
        "Returns a Collection of slim project entries. Excludes soft-deleted, "
        "closed, and completed projects. Requires vendors:read."
    ),
    dependencies=[Depends(require_permission_any_scope(VENDORS_READ))],
    responses={404: {"description": "Vendor not found"}},
)
def list_projects_for_vendor(
    vendor_id: str,
    controller: Annotated[VendorController, Depends(get_vendor_controller)],
) -> Dict[str, Any]:
    return controller.list_projects(vendor_id)


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    summary="Create a vendor",
    description=(
        "Creates a new vendor. name must be unique. phone_number / phoneNumber "
        "is required. Requires vendors:manage."
    ),
    dependencies=[Depends(require_permission(VENDORS_MANAGE))],
    responses={409: {"description": "Vendor name already in use"}},
)
def create_vendor(
    payload: VendorCreateRequest,
    controller: Annotated[VendorController, Depends(get_vendor_controller)],
) -> Dict[str, Any]:
    return controller.create(payload)


@router.patch(
    "/{vendor_id}",
    summary="Update a vendor",
    description=(
        "Partial update. name is unique — collision returns 409. "
        "projectIds: null = leave mappings unchanged, [] = clear all, "
        "non-empty list = replace. Requires vendors:manage."
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
    controller: Annotated[VendorController, Depends(get_vendor_controller)],
) -> Dict[str, Any]:
    return controller.update(vendor_id, payload)


@router.delete(
    "/{vendor_id}",
    status_code=status.HTTP_200_OK,
    summary="Soft-delete a vendor",
    description=(
        "Marks the vendor deleted (stamps deletedAt, flips active=False). "
        "Project mappings are preserved for restore. Requires vendors:manage."
    ),
    dependencies=[Depends(require_permission(VENDORS_MANAGE))],
    responses={404: {"description": "Vendor not found"}},
)
def delete_vendor(
    vendor_id: str,
    request: Request,
    controller: Annotated[VendorController, Depends(get_vendor_controller)],
) -> None:
    deleted_by_user_id = getattr(request.state, "user_id", None) or ""
    controller.delete(vendor_id, deleted_by_user_id=deleted_by_user_id)


@router.post(
    "/{vendor_id}/restore",
    summary="Restore a soft-deleted vendor",
    description=(
        "Clears deletedAt + deletedBy and flips active=True. "
        "Requires vendors:manage."
    ),
    dependencies=[Depends(require_permission(VENDORS_MANAGE))],
    responses={404: {"description": "Vendor not found"}},
)
def restore_vendor(
    vendor_id: str,
    controller: Annotated[VendorController, Depends(get_vendor_controller)],
) -> Dict[str, Any]:
    return controller.restore(vendor_id)
