"""Data access for the project_categories catalog."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project_category import ProjectCategory


class ProjectCategoryRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, category_id: int) -> Optional[ProjectCategory]:
        return self.db.get(ProjectCategory, category_id)

    def get_by_code(self, code: str) -> Optional[ProjectCategory]:
        stmt = select(ProjectCategory).where(ProjectCategory.code == code)
        return self.db.execute(stmt).scalars().first()

    def list_(self, *, include_inactive: bool = False) -> List[ProjectCategory]:
        stmt = select(ProjectCategory)
        if not include_inactive:
            stmt = stmt.where(ProjectCategory.active.is_(True))
        stmt = stmt.order_by(ProjectCategory.label.asc())
        return list(self.db.execute(stmt).scalars().all())

    def create(self, **kwargs) -> ProjectCategory:
        row = ProjectCategory(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: ProjectCategory, **kwargs) -> ProjectCategory:
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        self.db.flush()
        return row

    def deactivate(self, row: ProjectCategory) -> ProjectCategory:
        row.active = False
        self.db.flush()
        return row

    def reactivate(self, row: ProjectCategory) -> ProjectCategory:
        row.active = True
        self.db.flush()
        return row
