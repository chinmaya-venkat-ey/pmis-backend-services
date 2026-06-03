"""Business logic for the cost-types catalog.

Enforces:
  - Code uniqueness (lowercased server-side)
  - Delete via active=False (unified simple-deactivate pattern)
  - is_builtin is INFORMATIONAL only — does NOT block delete
"""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.core.errors import CatalogEntryConflictError, CatalogEntryNotFoundError
from app.models.cost_type import CostType
from app.repositories.cost_type_repository import CostTypeRepository
from app.schemas.cost_type import CostTypeCreateRequest, CostTypeUpdateRequest


class CostTypeService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = CostTypeRepository(db)

    def list_(self, *, include_inactive: bool = False) -> List[CostType]:
        return self.repo.list_(include_inactive=include_inactive)

    def get_by_code(self, code: str) -> CostType:
        row = self.repo.get_by_code(code)
        if row is None:
            raise CatalogEntryNotFoundError(f"Cost type code {code!r} not found")
        return row

    def create(self, payload: CostTypeCreateRequest) -> CostType:
        if self.repo.get_by_code(payload.code) is not None:
            raise CatalogEntryConflictError(
                f"Cost type code {payload.code!r} already exists",
                details={"code": payload.code},
            )
        row = self.repo.create(
            code=payload.code,           # already lowercased by the schema validator
            name=payload.name,
            description=payload.description,
            position=payload.position,
            is_builtin=False,
            active=True,
        )
        self.db.commit()
        return row

    def update(self, code: str, payload: CostTypeUpdateRequest) -> CostType:
        row = self.get_by_code(code)
        self.repo.update(row, **payload.model_dump(exclude_unset=True))
        self.db.commit()
        return row

    def delete(self, code: str) -> CostType:
        row = self.get_by_code(code)
        self.repo.deactivate(row)
        self.db.commit()
        return row

    def restore(self, code: str) -> CostType:
        row = self.get_by_code(code)
        self.repo.reactivate(row)
        self.db.commit()
        return row
