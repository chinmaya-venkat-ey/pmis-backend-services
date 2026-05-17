"""Business logic for the milestone_statuses catalog."""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.core.errors import (
    CatalogEntryConflictError,
    CatalogEntryNotFoundError,
)
from app.models.milestone_status import MilestoneStatus
from app.repositories.milestone_status_repository import MilestoneStatusRepository
from app.schemas.milestone_status import (
    MilestoneStatusCreateRequest,
    MilestoneStatusUpdateRequest,
)


class MilestoneStatusService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = MilestoneStatusRepository(db)

    def list_(self, *, include_inactive: bool = False) -> List[MilestoneStatus]:
        return self.repo.list_(include_inactive=include_inactive)

    def get_by_code(self, code: str) -> MilestoneStatus:
        row = self.repo.get_by_code(code)
        if row is None:
            raise CatalogEntryNotFoundError(f"MilestoneStatus code {code!r} not found")
        return row

    def create(self, payload: MilestoneStatusCreateRequest) -> MilestoneStatus:
        if self.repo.get_by_code(payload.code) is not None:
            raise CatalogEntryConflictError(
                f"MilestoneStatus code {payload.code!r} already exists",
                details={"code": payload.code},
            )
        row = self.repo.create(
            code=payload.code,
            label=payload.label,
            is_builtin=False,
            is_terminal=payload.is_terminal,
            active=payload.active,
        )
        self.db.commit()
        return row

    def update(self, code: str, payload: MilestoneStatusUpdateRequest) -> MilestoneStatus:
        row = self.get_by_code(code)
        self.repo.update(row, **payload.model_dump(exclude_unset=True))
        self.db.commit()
        return row

    def delete(self, code: str) -> MilestoneStatus:
        row = self.get_by_code(code)
        # is_builtin is informational only — all statuses are deletable.
        self.repo.deactivate(row)
        self.db.commit()
        return row

    def restore(self, code: str) -> MilestoneStatus:
        row = self.get_by_code(code)
        self.repo.reactivate(row)
        self.db.commit()
        return row
