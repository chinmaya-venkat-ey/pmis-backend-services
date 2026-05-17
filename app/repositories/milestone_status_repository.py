"""Data access for the milestone_statuses catalog."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.milestone_status import MilestoneStatus


class MilestoneStatusRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, status_id: int) -> Optional[MilestoneStatus]:
        return self.db.get(MilestoneStatus, status_id)

    def get_by_code(self, code: str) -> Optional[MilestoneStatus]:
        stmt = select(MilestoneStatus).where(MilestoneStatus.code == code)
        return self.db.execute(stmt).scalars().first()

    def list_(self, *, include_inactive: bool = False) -> List[MilestoneStatus]:
        stmt = select(MilestoneStatus)
        if not include_inactive:
            stmt = stmt.where(MilestoneStatus.active.is_(True))
        stmt = stmt.order_by(MilestoneStatus.label.asc())
        return list(self.db.execute(stmt).scalars().all())

    def create(self, **kwargs) -> MilestoneStatus:
        row = MilestoneStatus(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: MilestoneStatus, **kwargs) -> MilestoneStatus:
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        self.db.flush()
        return row

    def deactivate(self, row: MilestoneStatus) -> MilestoneStatus:
        row.active = False
        self.db.flush()
        return row

    def reactivate(self, row: MilestoneStatus) -> MilestoneStatus:
        row.active = True
        self.db.flush()
        return row
