"""Business logic for the carry-forward-methods catalog.

Code uniqueness (lowercased); delete via active=False; is_builtin is
informational only.
"""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.core.errors import CatalogEntryConflictError, CatalogEntryNotFoundError
from app.models.carry_forward_method import CarryForwardMethod
from app.repositories.carry_forward_method_repository import CarryForwardMethodRepository
from app.schemas.carry_forward_method import (
    CarryForwardMethodCreateRequest,
    CarryForwardMethodUpdateRequest,
)


class CarryForwardMethodService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = CarryForwardMethodRepository(db)

    def list_(self, *, include_inactive: bool = False) -> List[CarryForwardMethod]:
        return self.repo.list_(include_inactive=include_inactive)

    def get_by_code(self, code: str) -> CarryForwardMethod:
        row = self.repo.get_by_code(code)
        if row is None:
            raise CatalogEntryNotFoundError(f"Carry-forward method code {code!r} not found")
        return row

    def create(self, payload: CarryForwardMethodCreateRequest) -> CarryForwardMethod:
        if self.repo.get_by_code(payload.code) is not None:
            raise CatalogEntryConflictError(
                f"Carry-forward method code {payload.code!r} already exists",
                details={"code": payload.code},
            )
        row = self.repo.create(
            code=payload.code,           # already lowercased by the schema validator
            name=payload.name,
            description=payload.description,
            method=payload.method,
            variant=payload.variant,
            formula=payload.formula,
            position=payload.position,
            is_builtin=False,
            active=True,
        )
        self.db.commit()
        return row

    def update(self, code: str, payload: CarryForwardMethodUpdateRequest) -> CarryForwardMethod:
        row = self.get_by_code(code)
        self.repo.update(row, **payload.model_dump(exclude_unset=True))
        self.db.commit()
        return row

    def delete(self, code: str) -> CarryForwardMethod:
        row = self.get_by_code(code)
        self.repo.deactivate(row)
        self.db.commit()
        return row

    def restore(self, code: str) -> CarryForwardMethod:
        row = self.get_by_code(code)
        self.repo.reactivate(row)
        self.db.commit()
        return row
