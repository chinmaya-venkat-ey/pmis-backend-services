"""Business logic for the vendors catalog.

Enforces:
  - Name uniqueness on create (case-sensitive — matches source)
  - Soft-delete via deleted_at + deleted_by (NOT active=False alone)
  - Built-in handling NOT applicable here (vendors are all user-created)

Row-level scoping (org_admin sees only vendors in their org): the
`list_for_caller` helper accepts `caller_vendor_id` and `is_admin` from
the route — services pass them in based on request.state. Final scoping
rules are deferred to the user-svc port discussion.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.errors import CatalogEntryConflictError, CatalogEntryNotFoundError
from app.models.vendor import Vendor
from app.repositories.vendor_repository import VendorRepository
from app.schemas.vendor import VendorCreateRequest, VendorUpdateRequest


class VendorService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = VendorRepository(db)

    def list_(
        self,
        *,
        include_inactive: bool = False,
        include_deleted: bool = False,
        caller_vendor_id: Optional[str] = None,
        is_admin: bool = False,
    ) -> List[Vendor]:
        """List vendors. If `is_admin=False`, the result is scoped to the
        caller's own vendor (Option C row-level scoping — first-pass heuristic;
        refined during user-svc port)."""
        vendor_id_filter = None if is_admin else caller_vendor_id
        return self.repo.list_(
            include_inactive=include_inactive,
            include_deleted=include_deleted,
            vendor_id_filter=vendor_id_filter,
        )

    def get_by_id(self, vendor_id: str) -> Vendor:
        row = self.repo.get_by_id(vendor_id)
        if row is None:
            raise CatalogEntryNotFoundError(f"Vendor {vendor_id!r} not found")
        return row

    def create(self, payload: VendorCreateRequest) -> Vendor:
        if self.repo.get_by_name(payload.name) is not None:
            raise CatalogEntryConflictError(
                f"Vendor name {payload.name!r} already exists",
                details={"name": payload.name},
            )
        row = self.repo.create(
            name=payload.name,
            description=payload.description,
            email=str(payload.email) if payload.email else None,
            contact_person=payload.contact_person,
            phone_number=payload.phone_number,
            active=True,
        )
        self.db.commit()
        return row

    def update(self, vendor_id: str, payload: VendorUpdateRequest) -> Vendor:
        row = self.get_by_id(vendor_id)
        updates = payload.model_dump(exclude_unset=True)
        if updates.get("name") and updates["name"] != row.name:
            clash = self.repo.get_by_name(updates["name"])
            if clash is not None and clash.id != row.id:
                raise CatalogEntryConflictError(
                    f"Vendor name {updates['name']!r} already in use",
                    details={"name": updates["name"]},
                )
        if "email" in updates and updates["email"] is not None:
            updates["email"] = str(updates["email"])
        self.repo.update(row, **updates)
        self.db.commit()
        return row

    def delete(self, vendor_id: str, *, deleted_by_user_id: str) -> Vendor:
        row = self.get_by_id(vendor_id)
        self.repo.soft_delete(row, deleted_by_user_id=deleted_by_user_id)
        self.db.commit()
        return row

    def restore(self, vendor_id: str) -> Vendor:
        row = self.get_by_id(vendor_id)
        self.repo.restore(row)
        self.db.commit()
        return row
