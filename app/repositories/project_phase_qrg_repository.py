"""Data access for project_phase_qrg (per-phase QRG-applied flag).

SQL only. One live row per (project, phase); the service upserts it.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project_phase_qrg import ProjectPhaseQrg


class ProjectPhaseQrgRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_for_phase(
        self, project_id: str, phase: int, *, include_deleted: bool = False,
    ) -> Optional[ProjectPhaseQrg]:
        stmt = (
            select(ProjectPhaseQrg)
            .where(ProjectPhaseQrg.project_id == project_id)
            .where(ProjectPhaseQrg.phase == phase)
        )
        if not include_deleted:
            stmt = stmt.where(ProjectPhaseQrg.deleted_at.is_(None))
        return self.db.execute(stmt).scalar_one_or_none()

    def get_applied_phase(self, project_id: str) -> Optional[int]:
        """The single phase that currently has QRG applied (lowest phase if
        legacy data has more than one), or ``None``. At most one is allowed
        going forward (enforced in the service)."""
        return self.db.execute(
            select(ProjectPhaseQrg.phase)
            .where(ProjectPhaseQrg.project_id == project_id)
            .where(ProjectPhaseQrg.qrg_applied.is_(True))
            .where(ProjectPhaseQrg.deleted_at.is_(None))
            .order_by(ProjectPhaseQrg.phase.asc())
            .limit(1)
        ).scalar_one_or_none()

    def list_all_live(self, project_id: str) -> List[ProjectPhaseQrg]:
        return list(self.db.execute(
            select(ProjectPhaseQrg)
            .where(ProjectPhaseQrg.project_id == project_id)
            .where(ProjectPhaseQrg.deleted_at.is_(None))
            .order_by(ProjectPhaseQrg.phase.asc())
        ).scalars().all())

    def create(self, **kwargs) -> ProjectPhaseQrg:
        row = ProjectPhaseQrg(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: ProjectPhaseQrg, **kwargs) -> ProjectPhaseQrg:
        for k, v in kwargs.items():
            setattr(row, k, v)
        self.db.flush()
        return row
