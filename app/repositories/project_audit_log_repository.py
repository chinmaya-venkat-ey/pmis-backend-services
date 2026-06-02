"""ProjectAuditLogRepository — append-only writer + paginated readers."""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.project_audit_log import ProjectAuditLog


class ProjectAuditLogRepository:
    def __init__(self, db: Session):
        self.db = db

    def write(
        self, *,
        project_id: str,
        target_kind: str,
        target_id: str,
        action: str,
        actor_user_id: Optional[str],
        changes: Optional[dict[str, Any]] = None,
        note: Optional[str] = None,
    ) -> ProjectAuditLog:
        row = ProjectAuditLog(
            project_id=project_id,
            target_kind=target_kind,
            target_id=target_id,
            action=action,
            actor_user_id=actor_user_id,
            changes=changes or {},
            note=note,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def list_for_target(
        self, target_kind: str, target_id: str, *,
        offset: int = 1, page_size: int = 100,
    ) -> List[ProjectAuditLog]:
        return list(self.db.execute(
            select(ProjectAuditLog)
            .where(ProjectAuditLog.target_kind == target_kind)
            .where(ProjectAuditLog.target_id == target_id)
            .order_by(ProjectAuditLog.created_at.desc())
            .offset(max(0, offset - 1) * page_size)
            .limit(page_size)
        ).scalars())

    def list_for_project(
        self, project_id: str, *,
        offset: int = 1, page_size: int = 100,
    ) -> Tuple[List[ProjectAuditLog], int]:
        """Paginated audit feed for one project. Returns (rows, total)."""
        clause = ProjectAuditLog.project_id == project_id
        total = self.db.execute(
            select(func.count()).select_from(ProjectAuditLog).where(clause)
        ).scalar_one()
        rows = list(self.db.execute(
            select(ProjectAuditLog)
            .where(clause)
            .order_by(ProjectAuditLog.created_at.desc(), ProjectAuditLog.id.desc())
            .offset(max(0, offset - 1) * page_size)
            .limit(page_size)
        ).scalars())
        return rows, total
