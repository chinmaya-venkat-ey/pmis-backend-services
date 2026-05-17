"""Data access for the priorities catalog. Delete via active=False."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.priority import Priority


class PriorityRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, priority_id: str) -> Optional[Priority]:
        return self.db.get(Priority, priority_id)

    def get_by_code(self, code: str) -> Optional[Priority]:
        stmt = select(Priority).where(Priority.code == code.upper())
        return self.db.execute(stmt).scalars().first()

    def list_(self, *, include_inactive: bool = False) -> List[Priority]:
        stmt = select(Priority)
        if not include_inactive:
            stmt = stmt.where(Priority.active.is_(True))
        stmt = stmt.order_by(Priority.position.asc(), Priority.code.asc())
        return list(self.db.execute(stmt).scalars().all())

    def create(self, **kwargs) -> Priority:
        row = Priority(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: Priority, **kwargs) -> Priority:
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        self.db.flush()
        return row

    def deactivate(self, row: Priority) -> Priority:
        row.active = False
        self.db.flush()
        return row

    def reactivate(self, row: Priority) -> Priority:
        row.active = True
        self.db.flush()
        return row
