"""Data access for the activity_types catalog."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity_type import ActivityType


class ActivityTypeRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, type_id: int) -> Optional[ActivityType]:
        return self.db.get(ActivityType, type_id)

    def get_by_code(self, code: str) -> Optional[ActivityType]:
        stmt = select(ActivityType).where(ActivityType.code == code)
        return self.db.execute(stmt).scalars().first()

    def list_(self, *, include_inactive: bool = False) -> List[ActivityType]:
        stmt = select(ActivityType)
        if not include_inactive:
            stmt = stmt.where(ActivityType.active.is_(True))
        stmt = stmt.order_by(ActivityType.label.asc())
        return list(self.db.execute(stmt).scalars().all())

    def create(self, **kwargs) -> ActivityType:
        row = ActivityType(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: ActivityType, **kwargs) -> ActivityType:
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        self.db.flush()
        return row

    def deactivate(self, row: ActivityType) -> ActivityType:
        row.active = False
        self.db.flush()
        return row

    def reactivate(self, row: ActivityType) -> ActivityType:
        row.active = True
        self.db.flush()
        return row
