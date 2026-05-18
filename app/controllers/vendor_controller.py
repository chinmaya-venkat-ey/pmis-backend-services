"""VendorController — HTTP adapter for /masters/vendors/* routes.

Includes the extra `list_projects_for_vendor` adapter for the FE's
vendor-detail page (`GET /masters/vendors/{vendor_id}/projects/list`).
"""
from __future__ import annotations

from typing import List, Optional

from app.schemas.vendor import (
    VendorCreateRequest,
    VendorResponse,
    VendorUpdateRequest,
)
from app.schemas.vendor_project import VendorProjectSummary
from app.schemas.vendor_user import VendorUserSummary
from app.services.vendor_service import VendorService


class VendorController:
    def __init__(self, service: VendorService):
        self.service = service

    def list_(
        self,
        *,
        include_inactive: bool = False,
        include_deleted: bool = False,
        caller_vendor_id: Optional[str] = None,
        is_admin: bool = False,
    ) -> List[VendorResponse]:
        rows = self.service.list_(
            include_inactive=include_inactive,
            include_deleted=include_deleted,
            caller_vendor_id=caller_vendor_id,
            is_admin=is_admin,
        )
        return [VendorResponse.model_validate(r) for r in rows]

    def get_details(self, vendor_id: str) -> VendorResponse:
        return VendorResponse.model_validate(self.service.get_by_id(vendor_id))

    def create(self, payload: VendorCreateRequest) -> VendorResponse:
        return VendorResponse.model_validate(self.service.create(payload))

    def update(self, vendor_id: str, payload: VendorUpdateRequest) -> VendorResponse:
        return VendorResponse.model_validate(self.service.update(vendor_id, payload))

    def delete(self, vendor_id: str, *, deleted_by_user_id: str) -> VendorResponse:
        return VendorResponse.model_validate(
            self.service.delete(vendor_id, deleted_by_user_id=deleted_by_user_id)
        )

    def restore(self, vendor_id: str) -> VendorResponse:
        return VendorResponse.model_validate(self.service.restore(vendor_id))

    def list_projects(self, vendor_id: str) -> List[VendorProjectSummary]:
        # Ensure the vendor exists (404 otherwise) before listing its projects.
        self.service.get_by_id(vendor_id)
        rows = self.service.repo.list_projects_for_vendor(vendor_id)
        return [VendorProjectSummary.model_validate(r) for r in rows]

    def list_users(self, vendor_id: str) -> List[VendorUserSummary]:
        self.service.get_by_id(vendor_id)
        rows = self.service.repo.list_users_for_vendor(vendor_id)
        return [VendorUserSummary.model_validate(r) for r in rows]
