"""Business logic for the resource_types catalog. Delete via active=False."""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.core.errors import CatalogEntryConflictError, CatalogEntryNotFoundError
from app.models.resource_type import ResourceType
from app.repositories.resource_type_repository import ResourceTypeRepository
from app.schemas.resource_type import (
    ResourceTypeCreateRequest,
    ResourceTypeUpdateRequest,
)


class ResourceTypeService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ResourceTypeRepository(db)

    def list_(self, *, include_inactive: bool = False) -> List[ResourceType]:
        return self.repo.list_(include_inactive=include_inactive)

    def get_by_id(self, rt_id: str) -> ResourceType:
        row = self.repo.get_by_id(rt_id)
        if row is None:
            raise CatalogEntryNotFoundError(f"ResourceType {rt_id!r} not found")
        return row

    def create(self, payload: ResourceTypeCreateRequest) -> ResourceType:
        if self.repo.get_by_code(payload.code) is not None:
            raise CatalogEntryConflictError(
                f"ResourceType code {payload.code!r} already exists",
                details={"code": payload.code},
            )
        row = self.repo.create(
            code=payload.code,
            name=payload.name,
            active=payload.active,
        )
        self.db.commit()
        return row

    def update(self, rt_id: str, payload: ResourceTypeUpdateRequest) -> ResourceType:
        row = self.get_by_id(rt_id)
        self.repo.update(row, **payload.model_dump(exclude_unset=True))
        self.db.commit()
        return row

    def delete(self, rt_id: str) -> ResourceType:
        row = self.get_by_id(rt_id)
        self.repo.deactivate(row)
        self.db.commit()
        return row

    def restore(self, rt_id: str) -> ResourceType:
        row = self.get_by_id(rt_id)
        self.repo.reactivate(row)
        self.db.commit()
        return row
