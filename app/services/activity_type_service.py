"""Business logic for the activity_types catalog."""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.core.errors import (
    CatalogEntryConflictError,
    CatalogEntryNotFoundError,
)
from app.models.activity_type import ActivityType
from app.repositories.activity_type_repository import ActivityTypeRepository
from app.schemas.activity_type import (
    ActivityTypeCreateRequest,
    ActivityTypeUpdateRequest,
)


class ActivityTypeService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ActivityTypeRepository(db)

    def list_(self, *, include_inactive: bool = False) -> List[ActivityType]:
        return self.repo.list_(include_inactive=include_inactive)

    def get_by_code(self, code: str) -> ActivityType:
        row = self.repo.get_by_code(code)
        if row is None:
            raise CatalogEntryNotFoundError(f"ActivityType code {code!r} not found")
        return row

    def create(self, payload: ActivityTypeCreateRequest) -> ActivityType:
        if self.repo.get_by_code(payload.code) is not None:
            raise CatalogEntryConflictError(
                f"ActivityType code {payload.code!r} already exists",
                details={"code": payload.code},
            )
        row = self.repo.create(
            code=payload.code,
            label=payload.label,
            is_builtin=False,
            active=payload.active,
        )
        self.db.commit()
        return row

    def update(self, code: str, payload: ActivityTypeUpdateRequest) -> ActivityType:
        row = self.get_by_code(code)
        self.repo.update(row, **payload.model_dump(exclude_unset=True))
        self.db.commit()
        return row

    def delete(self, code: str) -> ActivityType:
        row = self.get_by_code(code)
        # is_builtin is informational only — all activity types are deletable.
        self.repo.deactivate(row)
        self.db.commit()
        return row

    def restore(self, code: str) -> ActivityType:
        row = self.get_by_code(code)
        self.repo.reactivate(row)
        self.db.commit()
        return row
