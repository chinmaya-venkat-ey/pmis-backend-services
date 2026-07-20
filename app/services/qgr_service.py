"""QgrService — CRUD for project.project_qgr_config.

Small — this is a data-first table with almost no business rules:
  * List all rows for a project (chronological — history + active).
  * Add a new effective-dated row.
  * Delete a row (rarely used — kept because ops occasionally seed test
    values they want to remove).

The core validation logic:
  1. Cannot overlap another row of the SAME phase — unique constraint
     ``uq_qgr_project_phase_from`` on (project_id, phase, effective_from)
     enforces the rare duplicate case; broader overlap detection is
     deferred (settlement service reads the row active at the quarter's
     end date, so overlap is a soft warning not a hard block).
  2. effective_until >= effective_from when both set.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.models.project_qgr_config import ProjectQgrConfig


class QgrService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ list

    def list_for_project(self, project_id: str) -> List[ProjectQgrConfig]:
        return list(self.db.execute(
            select(ProjectQgrConfig)
            .where(ProjectQgrConfig.project_id == project_id)
            .order_by(
                ProjectQgrConfig.phase,
                ProjectQgrConfig.effective_from.desc(),
            )
        ).scalars().all())

    # ------------------------------------------------------------------ create

    def create(
        self,
        *,
        project_id: str,
        phase: str,
        qgr_amount_per_quarter: Decimal,
        effective_from: date,
        effective_until: Optional[date],
        notes: Optional[str],
    ) -> ProjectQgrConfig:
        if effective_until is not None and effective_until < effective_from:
            raise ValidationError(
                "effective_until must be on or after effective_from",
                code="invalid_effective_window",
            )
        row = ProjectQgrConfig(
            id=str(uuid4()),
            project_id=project_id,
            phase=phase,
            qgr_amount_per_quarter=qgr_amount_per_quarter,
            effective_from=effective_from,
            effective_until=effective_until,
            notes=notes,
        )
        self.db.add(row)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(row)
        return row

    # ------------------------------------------------------------------ delete

    def delete(self, *, project_id: str, config_id: str) -> None:
        row = self.db.execute(
            select(ProjectQgrConfig).where(
                ProjectQgrConfig.id == config_id,
                ProjectQgrConfig.project_id == project_id,
            )
        ).scalars().first()
        if row is None:
            raise NotFoundError(
                f"QGR config '{config_id}' not found on project '{project_id}'",
                code="qgr_config_not_found",
            )
        self.db.delete(row)
        self.db.commit()
