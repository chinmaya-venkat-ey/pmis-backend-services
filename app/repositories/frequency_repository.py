"""Data access for the frequencies catalog. Delete via active=False."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.frequency import Frequency


class FrequencyRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, frequency_id: str) -> Optional[Frequency]:
        return self.db.get(Frequency, frequency_id)

    def get_by_code(self, code: str) -> Optional[Frequency]:
        stmt = select(Frequency).where(Frequency.code == code.lower())
        return self.db.execute(stmt).scalars().first()

    def list_(self, *, include_inactive: bool = False) -> List[Frequency]:
        stmt = select(Frequency)
        if not include_inactive:
            stmt = stmt.where(Frequency.active.is_(True))
        stmt = stmt.order_by(Frequency.position.asc(), Frequency.code.asc())
        return list(self.db.execute(stmt).scalars().all())

    def create(self, **kwargs) -> Frequency:
        row = Frequency(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: Frequency, **kwargs) -> Frequency:
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        self.db.flush()
        return row

    def deactivate(self, row: Frequency) -> Frequency:
        row.active = False
        self.db.flush()
        return row

    def reactivate(self, row: Frequency) -> Frequency:
        row.active = True
        self.db.flush()
        return row
