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

    def list_(self, *, include_inactive: bool = False) -> List[Designation]:
        return self.repo.list_(include_inactive=include_inactive)

    def get_by_id(self, designation_id: str) -> Designation:
        row = self.repo.get_by_id(designation_id)
        if row is None:
            raise CatalogEntryNotFoundError(f"Designation {designation_id!r} not found")
        return row

    def create(self, payload: DesignationCreateRequest) -> Designation:
        if self.repo.get_by_code(payload.code) is not None:
            raise CatalogEntryConflictError(
                f"Designation code {payload.code!r} already exists",
                details={"code": payload.code},
            )
        row = self.repo.create(
            code=payload.code,
            name=payload.name,
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
