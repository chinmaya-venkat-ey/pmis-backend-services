"""VendorController — HTTP adapter for /master/vendors/* routes.

All public methods return plain dicts that match the monolith wire shape
(_type discriminator, camelCase keys, embedded projects list / Collection
wrapper). FastAPI JSON-encodes the dict and HalApiRoute wraps it in the
PMIS envelope {data:..., message:..., error:..., status:...}.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.schemas.vendor import (
    VendorCreateRequest,
    VendorUpdateRequest,
    _project_dict,
    _vendor_dict,
)
from app.schemas.vendor_user import VendorUserSummary
from app.services.vendor_service import VendorService


def _collection(items: List[Any]) -> Dict[str, Any]:
    """Build a PMIS Collection envelope."""
    return {
        "_type": "Collection",
        "total": len(items),
        "count": len(items),
        "_embedded": {"elements": items},
    }


class VendorController:
    def __init__(self, service: VendorService):
        self.service = service

    def list_(
        self,
        *,
        active_only: bool = False,
        caller_vendor_id: Optional[str] = None,
        is_admin: bool = False,
        caller_can_see_all: bool = False,
    ) -> Dict[str, Any]:
        vendors = self.service.list_(
            active_only=active_only,
            caller_vendor_id=caller_vendor_id,
            is_admin=is_admin,
            caller_can_see_all=caller_can_see_all,
        )
        vendor_ids = [v.id for v in vendors]
        projects_by_vendor = self.service.list_projects_for_vendors(vendor_ids)
        items = [
            _vendor_dict(v, projects_by_vendor.get(v.id, []))
            for v in vendors
        ]
        return _collection(items)

    def get_details(self, vendor_id: str) -> Dict[str, Any]:
        vendor = self.service.get_by_id(vendor_id)
        projects = self.service.repo.list_projects_for_vendor(vendor_id)
        return _vendor_dict(vendor, projects)

    def create(self, payload: VendorCreateRequest) -> Dict[str, Any]:
        vendor = self.service.create(payload)
        projects = self.service.repo.list_projects_for_vendor(vendor.id)
        return _vendor_dict(vendor, projects)

    def update(self, vendor_id: str, payload: VendorUpdateRequest) -> Dict[str, Any]:
        vendor = self.service.update(vendor_id, payload)
        projects = self.service.repo.list_projects_for_vendor(vendor_id)
        return _vendor_dict(vendor, projects)

    def delete(self, vendor_id: str, *, deleted_by_user_id: str) -> None:
        self.service.delete(vendor_id, deleted_by_user_id=deleted_by_user_id)

    def restore(self, vendor_id: str) -> Dict[str, Any]:
        vendor = self.service.restore(vendor_id)
        projects = self.service.repo.list_projects_for_vendor(vendor_id)
        return _vendor_dict(vendor, projects)

    def list_projects(self, vendor_id: str) -> Dict[str, Any]:
        self.service.get_by_id(vendor_id)
        rows = self.service.repo.list_projects_for_vendor(vendor_id)
        return _collection([_project_dict(p) for p in rows])

    def list_users(self, vendor_id: str) -> List[VendorUserSummary]:
        self.service.get_by_id(vendor_id)
        rows = self.service.repo.list_users_for_vendor(vendor_id)
        return [VendorUserSummary.model_validate(r) for r in rows]
