"""MilestoneRepository — CRUD + position management for project.milestones."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.milestone import Milestone
from app.models.milestone_dependency import MilestoneDependency
from app.models.milestone_vendor import MilestoneVendor


class MilestoneRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, milestone_id: str) -> Optional[Milestone]:
        return self.db.get(Milestone, milestone_id)

    def list_for_project(
        self, project_id: str, *,
        offset: int = 1, page_size: int = 50, include_deleted: bool = False,
    ) -> Tuple[List[Milestone], int]:
        clauses = [Milestone.project_id == project_id]
        if not include_deleted:
            clauses.append(Milestone.deleted_at.is_(None))
        stmt = select(Milestone).where(and_(*clauses)).order_by(Milestone.position.asc())
        count_stmt = select(func.count()).select_from(Milestone).where(and_(*clauses))
        total = self.db.execute(count_stmt).scalar_one()
        rows = self.db.execute(
            stmt.offset(max(0, offset - 1) * page_size).limit(page_size)
        ).scalars().all()
        return list(rows), total

    def next_position_for_project(self, project_id: str) -> int:
        row = self.db.execute(
            select(func.coalesce(func.max(Milestone.position), 0))
            .where(Milestone.project_id == project_id)
            .where(Milestone.deleted_at.is_(None))
        ).scalar_one()
        return int(row) + 1

    def create(self, **kwargs) -> Milestone:
        row = Milestone(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: Milestone, **kwargs) -> Milestone:
        for k, v in kwargs.items():
            setattr(row, k, v)
        self.db.flush()
        return row

    def soft_delete(self, row: Milestone) -> Milestone:
        row.deleted_at = datetime.now(timezone.utc)
        self.db.flush()
        return row

    def restore(self, row: Milestone) -> Milestone:
        row.deleted_at = None
        self.db.flush()
        return row

    # --------------------------------------------------------------- dependencies

    def list_dependencies_for(self, milestone_id: str) -> List[str]:
        return list(self.db.execute(
            select(MilestoneDependency.to_milestone_id)
            .where(MilestoneDependency.from_milestone_id == milestone_id)
        ).scalars())

    def replace_dependencies(self, milestone_id: str, depends_on_ids: List[str]) -> None:
        self.db.execute(
            MilestoneDependency.__table__.delete().where(
                MilestoneDependency.from_milestone_id == milestone_id
            )
        )
        for tid in depends_on_ids:
            self.db.add(MilestoneDependency(
                from_milestone_id=milestone_id, to_milestone_id=tid,
            ))
        self.db.flush()

    # --------------------------------------------------------------- vendors

    def list_vendors_for(self, milestone_id: str) -> List[str]:
        return list(self.db.execute(
            select(MilestoneVendor.vendor_id)
            .where(MilestoneVendor.milestone_id == milestone_id)
        ).scalars())

    def set_vendor_mapping(self, milestone_id: str, vendor_ids: List[str]) -> None:
        self.db.execute(
            MilestoneVendor.__table__.delete().where(
                MilestoneVendor.milestone_id == milestone_id
            )
        )
        for vid in vendor_ids:
            self.db.add(MilestoneVendor(milestone_id=milestone_id, vendor_id=vid))
        self.db.flush()
