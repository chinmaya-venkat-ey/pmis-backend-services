"""
Project audit log repository.
"""
from typing import Optional, List, Tuple, Any, Dict
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..models.project_audit_log import ProjectAuditLogModel
from ..models.project import ProjectModel
from ..models.user import UserModel
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
            project_name=getattr(model, "project_name", None),
            project_status=getattr(model, "project_status", None),
            owner=getattr(model, "owner", None),
            actor_id=model.actor_id,
            actor_login=getattr(model, "actor_login", None),
            actor_code=getattr(model, "actor_code", None),
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
        actor_login: Optional[str] = None,
        actor_code: Optional[str] = None,
        project_name: Optional[str] = None,
        project_status: Optional[str] = None,
        owner: Optional[str] = None,
    ) -> ProjectAuditLogModel:
        """Insert one audit row.

        Doc 47: ``actor_login`` / ``actor_code`` / ``project_name`` /
        ``project_status`` / ``owner`` are denormalized snapshots — the
        caller (typically :func:`record_audit` in
        projects/services/audit.py) looks them up against the live
        ``users`` and ``projects`` tables before invoking this repo. We
        do a defensive resolve here too in case a call site forgot —
        the audit table's NOT NULL columns must always be populated,
        even for legacy direct callers that pre-dated doc 47.
        """
        if (actor_login is None or actor_code is None
                or project_name is None or project_status is None
                or owner is None):
            resolved = self._resolve_denormalized(project_id, actor_id)
            if actor_login is None:
                actor_login = resolved.get("actor_login") or "system"
            if actor_code is None:
                actor_code = resolved.get("actor_code") or "system"
            if project_name is None:
                project_name = resolved.get("project_name") or "(unknown)"
            if project_status is None:
                project_status = resolved.get("project_status") or "(unknown)"
            if owner is None:
                owner = resolved.get("owner") or "(unknown)"
        if actor_role is None:
            actor_role = "system"

        entry = ProjectAuditLogModel(
            project_id=project_id,
            project_name=project_name,
            project_status=project_status,
            owner=owner,
            actor_id=actor_id,
            actor_login=actor_login,
            actor_code=actor_code,
            actor_role=actor_role,
            action=action,
            before=before,
            after=after,
        )
        self.db.add(entry)
        self.db.flush()
        return entry

    def _resolve_denormalized(
        self, project_id: str, actor_id: Optional[str]
    ) -> Dict[str, Optional[str]]:
        """Best-effort lookup of project name/status/owner + user login.

        Single small query per missing field. Returns NULL strings if
        the source row was already deleted — defensive only; normal
        callers should pre-resolve via :func:`record_audit`.
        """
        out: Dict[str, Optional[str]] = {
            "project_name": None,
            "project_status": None,
            "owner": None,
            "actor_login": None,
            "actor_code": None,
        }
        if project_id:
            row = (
                self.db.query(
                    ProjectModel.name,
                    ProjectModel.status,
                    ProjectModel.owner,
                )
                .filter(ProjectModel.id == project_id)
                .first()
            )
            if row is not None:
                out["project_name"] = row[0]
                out["project_status"] = row[1]
                out["owner"] = row[2]
        if actor_id:
            row = (
                self.db.query(UserModel.login, UserModel.user_code)
                .filter(UserModel.id == actor_id)
                .first()
            )
            if row is not None:
                out["actor_login"] = row[0]
                out["actor_code"] = row[1]
        return out

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
