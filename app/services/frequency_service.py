"""Business logic for the frequencies catalog.

Enforces:
  - Code uniqueness (lowercased server-side)
  - Delete via active=False (unified simple-deactivate pattern)
  - is_builtin is INFORMATIONAL only — does NOT block delete
"""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.core.errors import CatalogEntryConflictError, CatalogEntryNotFoundError
from app.models.frequency import Frequency
from app.repositories.frequency_repository import FrequencyRepository
from app.schemas.frequency import FrequencyCreateRequest, FrequencyUpdateRequest


class FrequencyService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = FrequencyRepository(db)

    def list_(self, *, include_inactive: bool = False) -> List[Frequency]:
        return self.repo.list_(include_inactive=include_inactive)

    def get_by_code(self, code: str) -> Frequency:
        row = self.repo.get_by_code(code)
        if row is None:
            raise CatalogEntryNotFoundError(f"Frequency code {code!r} not found")
        return row

    def create(self, payload: FrequencyCreateRequest) -> Frequency:
        if self.repo.get_by_code(payload.code) is not None:
            raise CatalogEntryConflictError(
                f"Frequency code {payload.code!r} already exists",
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

    def update(self, code: str, payload: FrequencyUpdateRequest) -> Frequency:
        row = self.get_by_code(code)
        self.repo.update(row, **payload.model_dump(exclude_unset=True))
        self.db.commit()
        return row

    def delete(self, code: str) -> Frequency:
        row = self.get_by_code(code)
        self.repo.deactivate(row)
        self.db.commit()
        return row

    def restore(self, code: str) -> Frequency:
        row = self.get_by_code(code)
        self.repo.reactivate(row)
        self.db.commit()
        return row
