"""Data access for project_phase_cf_allocation (custom carry-forward shares).

SQL only. The service owns the "replace the whole set for a phase" semantics:
on each save it soft-deletes the phase's live rows and inserts the new shares.
"""
from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.project_phase_cf_allocation import ProjectPhaseCfAllocation


class ProjectPhaseCfAllocationRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_all_live(self, project_id: str) -> List[ProjectPhaseCfAllocation]:
        return list(self.db.execute(
            select(ProjectPhaseCfAllocation)
            .where(ProjectPhaseCfAllocation.project_id == project_id)
            .where(ProjectPhaseCfAllocation.deleted_at.is_(None))
            .order_by(
                ProjectPhaseCfAllocation.source_phase.asc(),
                ProjectPhaseCfAllocation.recipient_key.asc(),
            )
        ).scalars().all())

    def list_for_phase(self, project_id: str, source_phase: str) -> List[ProjectPhaseCfAllocation]:
        return list(self.db.execute(
            select(ProjectPhaseCfAllocation)
            .where(ProjectPhaseCfAllocation.project_id == project_id)
            .where(ProjectPhaseCfAllocation.source_phase == source_phase)
            .where(ProjectPhaseCfAllocation.deleted_at.is_(None))
        ).scalars().all())

    def soft_delete_for_phase(self, project_id: str, source_phase: str, *, actor_user_id=None) -> None:
        """Soft-delete every live share row for one carrying phase."""
        self.db.execute(
            update(ProjectPhaseCfAllocation)
            .where(ProjectPhaseCfAllocation.project_id == project_id)
            .where(ProjectPhaseCfAllocation.source_phase == source_phase)
            .where(ProjectPhaseCfAllocation.deleted_at.is_(None))
            .values(deleted_at=datetime.utcnow(), updated_by=actor_user_id)
        )
        self.db.flush()

    def replace_for_phase(
        self, project_id: str, source_phase: str, rows: List[dict], *, actor_user_id=None,
    ) -> List[ProjectPhaseCfAllocation]:
        """Soft-delete the phase's existing live shares and insert ``rows``.

        Each ``rows`` dict: ``{recipient_kind, recipient_key, alloc_mode,
        input_value, percent}``."""
        self.soft_delete_for_phase(project_id, source_phase, actor_user_id=actor_user_id)
        created: List[ProjectPhaseCfAllocation] = []
        for r in rows:
            row = ProjectPhaseCfAllocation(
                project_id=project_id,
                source_phase=source_phase,
                recipient_kind=r["recipient_kind"],
                recipient_key=r["recipient_key"],
                alloc_mode=r["alloc_mode"],
                input_value=r.get("input_value"),
                percent=r.get("percent"),
                created_by=actor_user_id,
                updated_by=actor_user_id,
            )
            self.db.add(row)
            created.append(row)
        self.db.flush()
        return created
