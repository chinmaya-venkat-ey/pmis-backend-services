"""ActivityRepository — CRUD + dependencies + 1:1 resource sidecar."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.activity_dependency import ActivityDependency
from app.models.activity_resource import ActivityResource


class ActivityRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, activity_id: str) -> Optional[Activity]:
        return self.db.get(Activity, activity_id)

    def list_for_milestone(
        self, milestone_id: str, *,
        offset: int = 1, page_size: int = 50, include_deleted: bool = False,
    ) -> Tuple[List[Activity], int]:
        clauses = [Activity.milestone_id == milestone_id]
        if not include_deleted:
            clauses.append(Activity.deleted_at.is_(None))
        stmt = select(Activity).where(and_(*clauses)).order_by(Activity.position.asc())
        total = self.db.execute(
            select(func.count()).select_from(Activity).where(and_(*clauses))
        ).scalar_one()
        rows = self.db.execute(
            stmt.offset(max(0, offset - 1) * page_size).limit(page_size)
        ).scalars().all()
        return list(rows), total

    def list_for_project(
        self, project_id: str, *,
        offset: int = 1, page_size: int = 100, include_deleted: bool = False,
    ) -> Tuple[List[Activity], int]:
        clauses = [Activity.project_id == project_id]
        if not include_deleted:
            clauses.append(Activity.deleted_at.is_(None))
        stmt = select(Activity).where(and_(*clauses)).order_by(
            Activity.milestone_id.asc(), Activity.position.asc()
        )
        total = self.db.execute(
            select(func.count()).select_from(Activity).where(and_(*clauses))
        ).scalar_one()
        rows = self.db.execute(
            stmt.offset(max(0, offset - 1) * page_size).limit(page_size)
        ).scalars().all()
        return list(rows), total

    def next_position_for_milestone(self, milestone_id: str) -> int:
        row = self.db.execute(
            select(func.coalesce(func.max(Activity.position), 0))
            .where(Activity.milestone_id == milestone_id)
            .where(Activity.deleted_at.is_(None))
        ).scalar_one()
        return int(row) + 1

    def create(self, **kwargs) -> Activity:
        row = Activity(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: Activity, **kwargs) -> Activity:
        for k, v in kwargs.items():
            setattr(row, k, v)
        self.db.flush()
        return row

    def soft_delete(self, row: Activity) -> Activity:
        row.deleted_at = datetime.now(timezone.utc)
        self.db.flush()
        return row

    def restore(self, row: Activity) -> Activity:
        row.deleted_at = None
        self.db.flush()
        return row

    # --------------------------------------------------------------- dependencies

    def list_dependencies_for(self, activity_id: str) -> List[str]:
        return list(self.db.execute(
            select(ActivityDependency.to_activity_id)
            .where(ActivityDependency.from_activity_id == activity_id)
        ).scalars())

    def replace_dependencies(self, activity_id: str, depends_on_ids: List[str]) -> None:
        self.db.execute(
            ActivityDependency.__table__.delete().where(
                ActivityDependency.from_activity_id == activity_id
            )
        )
        for tid in depends_on_ids:
            self.db.add(ActivityDependency(
                from_activity_id=activity_id, to_activity_id=tid,
            ))
        self.db.flush()

    # --------------------------------------------------------------- resource sidecar

    def get_resource(self, activity_id: str) -> Optional[ActivityResource]:
        return self.db.execute(
            select(ActivityResource)
            .where(ActivityResource.activity_id == activity_id)
            .where(ActivityResource.deleted_at.is_(None))
        ).scalar_one_or_none()

    def upsert_resource(self, *, activity_id: str, project_id: str, **fields) -> ActivityResource:
        existing = self.get_resource(activity_id)
        if existing is not None:
            for k, v in fields.items():
                setattr(existing, k, v)
            self.db.flush()
            return existing
        row = ActivityResource(activity_id=activity_id, project_id=project_id, **fields)
        self.db.add(row)
        self.db.flush()
        return row
