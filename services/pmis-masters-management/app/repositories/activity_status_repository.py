"""Data access for the activity_statuses catalog."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity_status import ActivityStatus


class ActivityStatusRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, status_id: int) -> Optional[ActivityStatus]:
        return self.db.get(ActivityStatus, status_id)

    def get_by_code(self, code: str) -> Optional[ActivityStatus]:
        stmt = select(ActivityStatus).where(ActivityStatus.code == code)
        return self.db.execute(stmt).scalars().first()

    def list_(self, *, include_inactive: bool = False) -> List[ActivityStatus]:
        stmt = select(ActivityStatus)
        if not include_inactive:
            stmt = stmt.where(ActivityStatus.active.is_(True))
        stmt = stmt.order_by(ActivityStatus.label.asc())
        return list(self.db.execute(stmt).scalars().all())

    def create(self, **kwargs) -> ActivityStatus:
        row = ActivityStatus(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: ActivityStatus, **kwargs) -> ActivityStatus:
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        self.db.flush()
        return row

    def deactivate(self, row: ActivityStatus) -> ActivityStatus:
        row.active = False
        self.db.flush()
        return row

    def reactivate(self, row: ActivityStatus) -> ActivityStatus:
        row.active = True
        self.db.flush()
        return row
