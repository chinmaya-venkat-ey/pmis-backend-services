"""Business logic for the priorities catalog.

Enforces:
  - Code uniqueness (uppercased server-side)
  - Delete via active=False (unified pattern; was deleted_at pre-edit, simplified
    per user direction — only vendors retains the audit-rich deleted_at model)
  - is_builtin is INFORMATIONAL only — does NOT block delete
"""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.core.errors import CatalogEntryConflictError, CatalogEntryNotFoundError
from app.models.priority import Priority
from app.repositories.priority_repository import PriorityRepository
from app.schemas.priority import PriorityCreateRequest, PriorityUpdateRequest


class PriorityService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = PriorityRepository(db)

    def list_(self, *, include_inactive: bool = False) -> List[Priority]:
        return self.repo.list_(include_inactive=include_inactive)

    def get_by_code(self, code: str) -> Priority:
        row = self.repo.get_by_code(code)
        if row is None:
            raise CatalogEntryNotFoundError(f"Priority code {code!r} not found")
        return row

    def create(self, payload: PriorityCreateRequest) -> Priority:
        if self.repo.get_by_code(payload.code) is not None:
            raise CatalogEntryConflictError(
                f"Priority code {payload.code!r} already exists",
                details={"code": payload.code},
            )
        row = self.repo.create(
            code=payload.code,           # already uppercased by the schema validator
            name=payload.name,
            description=payload.description,
            position=payload.position,
            is_builtin=False,
            active=True,
        )
        self.db.commit()
        return row

    def update(self, code: str, payload: PriorityUpdateRequest) -> Priority:
        row = self.get_by_code(code)
        self.repo.update(row, **payload.model_dump(exclude_unset=True))
        self.db.commit()
        return row

    def delete(self, code: str) -> Priority:
        row = self.get_by_code(code)
        self.repo.deactivate(row)
        self.db.commit()
        return row

    def restore(self, code: str) -> Priority:
        row = self.get_by_code(code)
        self.repo.reactivate(row)
        self.db.commit()
        return row
