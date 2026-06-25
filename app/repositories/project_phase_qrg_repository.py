"""Data access for project_phase_qrg (per-phase CONFIG: order + carry-forward).

SQL only. One live row per (project, phase); the service upserts it. Despite
the legacy table/class name, a row now carries the phase ``sequence`` and the
carry-forward ("carry forward cost") settings, not just the old QRG flag.
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
        self, project_id: str, phase: str, *, include_deleted: bool = False,
    ) -> Optional[ProjectPhaseQrg]:
        stmt = (
            select(ProjectPhaseQrg)
            .where(ProjectPhaseQrg.project_id == project_id)
            .where(ProjectPhaseQrg.phase == phase)
        )
        if not include_deleted:
            stmt = stmt.where(ProjectPhaseQrg.deleted_at.is_(None))
        return self.db.execute(stmt).scalar_one_or_none()

    def list_all_live(self, project_id: str) -> List[ProjectPhaseQrg]:
        """Phase-config rows ordered by ``sequence`` (NULLs last), then name."""
        return list(self.db.execute(
            select(ProjectPhaseQrg)
            .where(ProjectPhaseQrg.project_id == project_id)
            .where(ProjectPhaseQrg.deleted_at.is_(None))
            .order_by(
                ProjectPhaseQrg.sequence.asc().nulls_last(),
                ProjectPhaseQrg.phase.asc(),
            )
        ).scalars().all())

    def max_sequence(self, project_id: str) -> int:
        """Highest assigned ``sequence`` for the project (0 if none)."""
        rows = self.db.execute(
            select(ProjectPhaseQrg.sequence)
            .where(ProjectPhaseQrg.project_id == project_id)
            .where(ProjectPhaseQrg.deleted_at.is_(None))
            .where(ProjectPhaseQrg.sequence.is_not(None))
        ).scalars().all()
        return max(rows) if rows else 0

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
