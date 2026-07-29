"""Business logic for the designations catalog. Delete via active=False."""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.core.errors import CatalogEntryConflictError, CatalogEntryNotFoundError
from app.models.designation import Designation
from app.repositories.designation_repository import DesignationRepository
from app.schemas.designation import (
    DesignationCreateRequest,
    DesignationUpdateRequest,
)


class DesignationService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = DesignationRepository(db)

    def list_(
        self, *, include_inactive: bool = False, vendor_id: str | None = None,
    ) -> List[Designation]:
        return self.repo.list_(include_inactive=include_inactive, vendor_id=vendor_id)

    def get_by_id(self, designation_id: str) -> Designation:
        row = self.repo.get_by_id(designation_id)
        if row is None:
            raise CatalogEntryNotFoundError(f"Designation {designation_id!r} not found")
        return row

    def create(self, payload: DesignationCreateRequest) -> Designation:
        # Uniqueness is per organization: the same code may exist once per vendor
        # (and once globally when vendor_id is NULL).
        if self.repo.get_by_code(payload.code, payload.vendor_id) is not None:
            raise CatalogEntryConflictError(
                f"Designation code {payload.code!r} already exists for this organization",
                details={"code": payload.code, "vendorId": payload.vendor_id},
            )
        row = self.repo.create(
            code=payload.code,
            name=payload.name,
            vendor_id=payload.vendor_id,
            monthly_rate=payload.monthly_rate,
            active=payload.active,
        )
        self.db.commit()
        return row

    def update(
        self, designation_id: str, payload: DesignationUpdateRequest
    ) -> Designation:
        row = self.get_by_id(designation_id)
        self.repo.update(row, **payload.model_dump(exclude_unset=True))
        self.db.commit()
        return row

    def delete(self, designation_id: str) -> Designation:
        row = self.get_by_id(designation_id)
        self.repo.deactivate(row)
        self.db.commit()
        return row

    def restore(self, designation_id: str) -> Designation:
        row = self.get_by_id(designation_id)
        self.repo.reactivate(row)
        self.db.commit()
        return row
