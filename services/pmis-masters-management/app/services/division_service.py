"""Business logic for the divisions catalog.

Enforces:
  - Code uniqueness on create
  - Built-in rows can't be deleted (CatalogBuiltinImmutableError)
  - "Delete" = deactivate (active=False); "restore" = reactivate (active=True)

Row-level scoping (e.g. "user only sees divisions in their org") would be
applied here as a filter — currently a no-op pending the user-svc port
discussion of Option C scoping semantics.
"""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.core.errors import (
    CatalogEntryConflictError,
    CatalogEntryNotFoundError,
)
from app.models.division import Division
from app.repositories.division_repository import DivisionRepository
from app.schemas.division import DivisionCreateRequest, DivisionUpdateRequest


class DivisionService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = DivisionRepository(db)

    def list_(self, *, include_inactive: bool = False) -> List[Division]:
        # Future scoping hook: filter by caller's permissions.
        return self.repo.list_(include_inactive=include_inactive)

    def get_by_code(self, code: str) -> Division:
        row = self.repo.get_by_code(code)
        if row is None:
            raise CatalogEntryNotFoundError(f"Division code {code!r} not found")
        return row

    def create(self, payload: DivisionCreateRequest) -> Division:
        if self.repo.get_by_code(payload.code) is not None:
            raise CatalogEntryConflictError(
                f"Division code {payload.code!r} already exists",
                details={"code": payload.code},
            )
        row = self.repo.create(
            code=payload.code,
            label=payload.label,
            is_builtin=False,
            requires_other=payload.requires_other,
            active=payload.active,
            email=str(payload.email),
            phone_number=payload.phone_number,
        )
        self.db.commit()
        return row

    def update(self, code: str, payload: DivisionUpdateRequest) -> Division:
        row = self.get_by_code(code)
        updates = payload.model_dump(exclude_unset=True)
        if "email" in updates and updates["email"] is not None:
            updates["email"] = str(updates["email"])
        self.repo.update(row, **updates)
        self.db.commit()
        return row

    def delete(self, code: str) -> Division:
        row = self.get_by_code(code)
        # is_builtin is informational only — divisions are fully deletable.
        self.repo.deactivate(row)
        self.db.commit()
        return row

    def restore(self, code: str) -> Division:
        row = self.get_by_code(code)
        self.repo.reactivate(row)
        self.db.commit()
        return row
