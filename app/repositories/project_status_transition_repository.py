"""Data access for the project_status_transitions catalog."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project_status_transition import ProjectStatusTransition


class ProjectStatusTransitionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, row_id: int) -> Optional[ProjectStatusTransition]:
        return self.db.get(ProjectStatusTransition, row_id)

    def get_by_edge(
        self,
        from_status: Optional[str],
        to_status: str,
    ) -> Optional[ProjectStatusTransition]:
        stmt = select(ProjectStatusTransition).where(
            ProjectStatusTransition.to_status == to_status
        )
        if from_status is None:
            stmt = stmt.where(ProjectStatusTransition.from_status.is_(None))
        else:
            stmt = stmt.where(ProjectStatusTransition.from_status == from_status)
        return self.db.execute(stmt).scalars().first()

    def list_(self, *, include_inactive: bool = False) -> List[ProjectStatusTransition]:
        stmt = select(ProjectStatusTransition)
        if not include_inactive:
            stmt = stmt.where(ProjectStatusTransition.active.is_(True))
        stmt = stmt.order_by(
            ProjectStatusTransition.from_status.asc().nulls_first(),
            ProjectStatusTransition.to_status.asc(),
        )
        return list(self.db.execute(stmt).scalars().all())

    def create(self, **kwargs) -> ProjectStatusTransition:
        row = ProjectStatusTransition(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: ProjectStatusTransition, **kwargs) -> ProjectStatusTransition:
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        self.db.flush()
        return row

    def deactivate(self, row: ProjectStatusTransition) -> ProjectStatusTransition:
        row.active = False
        self.db.flush()
        return row

    def reactivate(self, row: ProjectStatusTransition) -> ProjectStatusTransition:
        row.active = True
        self.db.flush()
        return row
