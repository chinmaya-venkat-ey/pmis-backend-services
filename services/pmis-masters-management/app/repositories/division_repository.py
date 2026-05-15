"""Data access for the divisions catalog."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.division import Division


class DivisionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, division_id: int) -> Optional[Division]:
        return self.db.get(Division, division_id)

    def get_by_code(self, code: str) -> Optional[Division]:
        stmt = select(Division).where(Division.code == code)
        return self.db.execute(stmt).scalars().first()

    def list_(self, *, include_inactive: bool = False) -> List[Division]:
        stmt = select(Division)
        if not include_inactive:
            stmt = stmt.where(Division.active.is_(True))
        stmt = stmt.order_by(Division.label.asc())
        return list(self.db.execute(stmt).scalars().all())

    def create(self, **kwargs) -> Division:
        row = Division(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: Division, **kwargs) -> Division:
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        self.db.flush()
        return row

    def deactivate(self, row: Division) -> Division:
        row.active = False
        self.db.flush()
        return row

    def reactivate(self, row: Division) -> Division:
        row.active = True
        self.db.flush()
        return row
