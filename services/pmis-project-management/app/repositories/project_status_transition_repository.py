"""Cross-schema reader for the masters.project_status_transitions FSM table.

Round-7: edges carry a PERMISSION CODE. Callers must hold that code at the
project scope or globally to take the transition.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models._cross_schema import ProjectStatusTransition


class ProjectStatusTransitionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_edge(
        self, from_status: Optional[str], to_status: str,
    ) -> Optional[ProjectStatusTransition]:
        """Return the active FSM edge row for (from_status, to_status), or None.

        `from_status=None` matches the initial-status seed row.
        """
        stmt = (
            select(ProjectStatusTransition)
            .where(ProjectStatusTransition.to_status == to_status)
            .where(ProjectStatusTransition.active.is_(True))
            .limit(1)
        )
        if from_status is None:
            stmt = stmt.where(ProjectStatusTransition.from_status.is_(None))
        else:
            stmt = stmt.where(ProjectStatusTransition.from_status == from_status)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_allowed_from(self, from_status: str) -> List[ProjectStatusTransition]:
        return list(self.db.execute(
            select(ProjectStatusTransition)
            .where(ProjectStatusTransition.from_status == from_status)
            .where(ProjectStatusTransition.active.is_(True))
        ).scalars())
