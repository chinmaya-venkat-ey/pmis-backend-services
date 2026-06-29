"""Data access for the carry-forward-methods catalog. Delete via active=False."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.carry_forward_method import CarryForwardMethod


class CarryForwardMethodRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, method_id: str) -> Optional[CarryForwardMethod]:
        return self.db.get(CarryForwardMethod, method_id)

    def get_by_code(self, code: str) -> Optional[CarryForwardMethod]:
        stmt = select(CarryForwardMethod).where(CarryForwardMethod.code == code.lower())
        return self.db.execute(stmt).scalars().first()

    def list_(self, *, include_inactive: bool = False) -> List[CarryForwardMethod]:
        stmt = select(CarryForwardMethod)
        if not include_inactive:
            stmt = stmt.where(CarryForwardMethod.active.is_(True))
        stmt = stmt.order_by(CarryForwardMethod.position.asc(), CarryForwardMethod.code.asc())
        return list(self.db.execute(stmt).scalars().all())

    def create(self, **kwargs) -> CarryForwardMethod:
        row = CarryForwardMethod(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: CarryForwardMethod, **kwargs) -> CarryForwardMethod:
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        self.db.flush()
        return row

    def deactivate(self, row: CarryForwardMethod) -> CarryForwardMethod:
        row.active = False
        self.db.flush()
        return row

    def reactivate(self, row: CarryForwardMethod) -> CarryForwardMethod:
        row.active = True
        self.db.flush()
        return row
