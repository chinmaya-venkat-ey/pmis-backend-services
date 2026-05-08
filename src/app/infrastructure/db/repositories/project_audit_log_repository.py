"""
Project audit log repository.
"""
from typing import Optional, List, Tuple, Any, Dict
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..models.project_audit_log import ProjectAuditLogModel
from ....domain.projects.project_audit_log import ProjectAuditLog


class ProjectAuditLogRepository:
    """Repository for project audit log entries.

    Writes do not commit — callers commit at the service-layer transaction edge
    so audit rows live inside the same transaction as the change they describe.
    """

    def __init__(self, db: Session):
        self.db = db

    def _to_domain(self, model: ProjectAuditLogModel) -> ProjectAuditLog:
        return ProjectAuditLog(
            id=model.id,
            project_id=model.project_id,
            actor_id=model.actor_id,
            actor_role=getattr(model, "actor_role", None),
            action=model.action,
            before=model.before,
            after=model.after,
            created_at=model.created_at,
        )

    def add(
        self,
        project_id: str,
        actor_id: Optional[str],
        action: str,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
        actor_role: Optional[str] = None,
    ) -> ProjectAuditLogModel:
        entry = ProjectAuditLogModel(
            project_id=project_id,
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            before=before,
            after=after,
        )
        self.db.add(entry)
        self.db.flush()
        return entry

    def list_for_project(
        self, project_id: str, offset: int = 0, limit: int = 50
    ) -> Tuple[List[ProjectAuditLog], int]:
        q = self.db.query(ProjectAuditLogModel).filter(
            ProjectAuditLogModel.project_id == project_id
        )
        total = q.with_entities(func.count(ProjectAuditLogModel.id)).scalar()
        rows = (
            q.order_by(ProjectAuditLogModel.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [self._to_domain(r) for r in rows], total
