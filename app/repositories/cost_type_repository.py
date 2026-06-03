"""Data access for the cost-types catalog. Delete via active=False."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cost_type import CostType


class CostTypeRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, cost_type_id: str) -> Optional[CostType]:
        return self.db.get(CostType, cost_type_id)

    def get_by_code(self, code: str) -> Optional[CostType]:
        stmt = select(CostType).where(CostType.code == code.lower())
        return self.db.execute(stmt).scalars().first()

    def list_(self, *, include_inactive: bool = False) -> List[CostType]:
        stmt = select(CostType)
        if not include_inactive:
            stmt = stmt.where(CostType.active.is_(True))
        stmt = stmt.order_by(CostType.position.asc(), CostType.code.asc())
        return list(self.db.execute(stmt).scalars().all())

    def create(self, **kwargs) -> CostType:
        row = CostType(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: CostType, **kwargs) -> CostType:
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        self.db.flush()
        return row

    def deactivate(self, row: CostType) -> CostType:
        row.active = False
        self.db.flush()
        return row

    def reactivate(self, row: CostType) -> CostType:
        row.active = True
        self.db.flush()
        return row
