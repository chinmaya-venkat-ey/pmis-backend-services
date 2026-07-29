"""Data access for project.planned_resources. SQL only — no business rules.

Soft-delete via ``deleted_at`` (default filter excludes deleted).
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.planned_resource import PlannedResource
from app.utilities.positions import lock_position_scope


class PlannedResourceRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, row_id: str, *, include_deleted: bool = False) -> Optional[PlannedResource]:
        stmt = select(PlannedResource).where(PlannedResource.id == row_id)
        if not include_deleted:
            stmt = stmt.where(PlannedResource.deleted_at.is_(None))
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_project(self, project_id: str) -> List[PlannedResource]:
        return list(self.db.execute(
            select(PlannedResource)
            .where(PlannedResource.project_id == project_id)
            .where(PlannedResource.deleted_at.is_(None))
            .order_by(PlannedResource.position.asc())
        ).scalars().all())

    def list_for_cost_item(self, cost_item_id: str) -> List[PlannedResource]:
        return list(self.db.execute(
            select(PlannedResource)
            .where(PlannedResource.cost_item_id == cost_item_id)
            .where(PlannedResource.deleted_at.is_(None))
            .order_by(PlannedResource.position.asc())
        ).scalars().all())

    def sum_cost_for_cost_item(
        self, cost_item_id: str, *, exclude_id: Optional[str] = None,
    ) -> Decimal:
        """Σ ``computed_cost`` across live planned resources on a cost row."""
        stmt = (
            select(func.coalesce(func.sum(PlannedResource.computed_cost), 0))
            .where(PlannedResource.cost_item_id == cost_item_id)
            .where(PlannedResource.deleted_at.is_(None))
        )
        if exclude_id is not None:
            stmt = stmt.where(PlannedResource.id != exclude_id)
        return Decimal(self.db.execute(stmt).scalar_one())

    def next_position_for_project(self, project_id: str) -> int:
        lock_position_scope(self.db, f"plannedresource_pos:{project_id}")
        row = self.db.execute(
            select(func.coalesce(func.max(PlannedResource.position), 0))
            .where(PlannedResource.project_id == project_id)
            .where(PlannedResource.deleted_at.is_(None))
        ).scalar_one()
        return int(row) + 1

    def create(self, **kwargs) -> PlannedResource:
        row = PlannedResource(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: PlannedResource, **kwargs) -> PlannedResource:
        for k, v in kwargs.items():
            setattr(row, k, v)
        self.db.flush()
        return row

    def soft_delete(self, row: PlannedResource) -> PlannedResource:
        from app.utilities.timezones import now_ist
        row.deleted_at = now_ist()
        self.db.flush()
        return row
