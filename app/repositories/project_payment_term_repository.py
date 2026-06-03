"""Data access for project_payment_terms. SQL only — no business rules.

Soft-delete via ``deleted_at`` (default filter excludes deleted).
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.project_payment_term import ProjectPaymentTerm


class ProjectPaymentTermRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, term_id: str, *, include_deleted: bool = False) -> Optional[ProjectPaymentTerm]:
        stmt = select(ProjectPaymentTerm).where(ProjectPaymentTerm.id == term_id)
        if not include_deleted:
            stmt = stmt.where(ProjectPaymentTerm.deleted_at.is_(None))
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_project(
        self, project_id: str, *, offset: int = 1, page_size: int = 50,
        include_deleted: bool = False,
    ) -> Tuple[List[ProjectPaymentTerm], int]:
        clauses = [ProjectPaymentTerm.project_id == project_id]
        if not include_deleted:
            clauses.append(ProjectPaymentTerm.deleted_at.is_(None))
        stmt = (
            select(ProjectPaymentTerm).where(and_(*clauses))
            .order_by(ProjectPaymentTerm.phase.asc().nulls_last(), ProjectPaymentTerm.position.asc())
        )
        count_stmt = select(func.count()).select_from(ProjectPaymentTerm).where(and_(*clauses))
        total = self.db.execute(count_stmt).scalar_one()
        rows = self.db.execute(
            stmt.offset(max(0, offset - 1) * page_size).limit(page_size)
        ).scalars().all()
        return list(rows), total

    def list_all_live(self, project_id: str) -> List[ProjectPaymentTerm]:
        return list(self.db.execute(
            select(ProjectPaymentTerm)
            .where(ProjectPaymentTerm.project_id == project_id)
            .where(ProjectPaymentTerm.deleted_at.is_(None))
            .order_by(ProjectPaymentTerm.phase.asc().nulls_last(), ProjectPaymentTerm.position.asc())
        ).scalars().all())

    def next_position_for_project(self, project_id: str) -> int:
        row = self.db.execute(
            select(func.coalesce(func.max(ProjectPaymentTerm.position), 0))
            .where(ProjectPaymentTerm.project_id == project_id)
            .where(ProjectPaymentTerm.deleted_at.is_(None))
        ).scalar_one()
        return int(row) + 1

    def create(self, **kwargs) -> ProjectPaymentTerm:
        row = ProjectPaymentTerm(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: ProjectPaymentTerm, **kwargs) -> ProjectPaymentTerm:
        for k, v in kwargs.items():
            setattr(row, k, v)
        self.db.flush()
        return row

    def soft_delete(self, row: ProjectPaymentTerm) -> ProjectPaymentTerm:
        from app.utilities.timezones import now_ist
        row.deleted_at = now_ist()
        self.db.flush()
        return row

    def restore(self, row: ProjectPaymentTerm) -> ProjectPaymentTerm:
        row.deleted_at = None
        self.db.flush()
        return row
