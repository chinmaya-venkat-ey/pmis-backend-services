"""Data access for the resource_types catalog. Delete via active=False."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.resource_type import ResourceType


class ResourceTypeRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, rt_id: str) -> Optional[ResourceType]:
        return self.db.get(ResourceType, rt_id)

    def get_by_code(self, code: str) -> Optional[ResourceType]:
        stmt = select(ResourceType).where(ResourceType.code == code)
        return self.db.execute(stmt).scalars().first()

    def list_(self, *, include_inactive: bool = False) -> List[ResourceType]:
        stmt = select(ResourceType)
        if not include_inactive:
            stmt = stmt.where(ResourceType.active.is_(True))
        stmt = stmt.order_by(ResourceType.name.asc())
        return list(self.db.execute(stmt).scalars().all())

    def create(self, **kwargs) -> ResourceType:
        row = ResourceType(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: ResourceType, **kwargs) -> ResourceType:
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        self.db.flush()
        return row

    def deactivate(self, row: ResourceType) -> ResourceType:
        row.active = False
        self.db.flush()
        return row

    def reactivate(self, row: ResourceType) -> ResourceType:
        row.active = True
        self.db.flush()
        return row
