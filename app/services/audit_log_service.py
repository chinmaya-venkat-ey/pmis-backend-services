"""AuditLogService — paginated read of ``project.project_audit_logs`` for
a single project.

Powers ``GET /project/projects/{uuid}/audit-logs``. Returns the project
header alongside the paginated audit rows so the FE can render context
without a separate project read.
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ProjectNotFoundError
from app.models._cross_schema import User
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_repository import ProjectRepository


def _serialize_entry(row, actor_map: dict) -> Dict[str, Any]:
    """Convert a ProjectAuditLog ORM row to a JSON-safe dict.

    Transformations applied for FE compatibility (Bug #10):
    - ``changes`` is flattened: per-field {before, after} deltas are
      aggregated into top-level ``before`` and ``after`` dicts.
    - Actor identity (login, user_code) is injected from ``actor_map``.
    """
    changes: dict = row.changes or {}

    # Aggregate per-field deltas produced by update audits.
    # create audits store {field: value} — treat as "after" only.
    before: Dict[str, Any] = {}
    after: Dict[str, Any] = {}
    for key, val in changes.items():
        if isinstance(val, dict) and "before" in val and "after" in val:
            before[key] = val["before"]
            after[key] = val["after"]
        else:
            after[key] = val

    actor_login = "—"
    actor_code = "—"
    if row.actor_user_id:
        u = actor_map.get(row.actor_user_id)
        if u:
            actor_login = u[0] or "—"
            actor_code = u[1] or row.actor_user_id
        else:
            actor_code = row.actor_user_id

    return {
        "id": row.id,
        "project_id": row.project_id,
        "target_kind": row.target_kind,
        "target_id": row.target_id,
        "action": row.action,
        "actor_user_id": row.actor_user_id,
        "actor_login": actor_login,
        "actor_code": actor_code,
        "before": before,
        "after": after,
        "changes": changes,
        "note": row.note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


class AuditLogService:
    def __init__(self, db: Session):
        self.db = db
        self.projects = ProjectRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    def _load_actor_map(self, actor_ids: List[str]) -> Dict[str, tuple]:
        """Batch-load (login, user_code) for a set of user IDs."""
        if not actor_ids:
            return {}
        rows = self.db.execute(
            select(User.id, User.login, User.user_code).where(User.id.in_(actor_ids))
        ).all()
        return {uid: (login, code) for uid, login, code in rows}

    def list_for_project(
        self, project_id: str, *, offset: int = 1, page_size: int = 50,
    ) -> Dict[str, Any]:
        project = self.projects.get_by_id(project_id, include_deleted=True)
        if project is None:
            raise ProjectNotFoundError(f"Project with ID {project_id} not found")
        rows, total = self.audit.list_for_project(
            project_id, offset=offset, page_size=page_size,
        )

        actor_ids = list({r.actor_user_id for r in rows if r.actor_user_id})
        actor_map = self._load_actor_map(actor_ids)

        elements = [_serialize_entry(r, actor_map) for r in rows]

        # Monolith parity: top-level Collection envelope with self-link,
        # count, and ``_embedded.elements`` (the wrap layer skips its
        # auto-wrap when ``_bare: True``).
        return {
            "_bare": True,
            "_type": "Collection",
            "_links": {
                "self": {
                    "href": (
                        f"/project/projects/{project_id}/audit-logs"
                        f"?offset={offset}&pageSize={page_size}"
                    ),
                },
            },
            "project": {
                "project_id": project.id,
                "project_code": project.project_code,
                "project_name": project.name,
                "project_status": project.status,
                "owner": project.owner,
            },
            "total": total,
            "count": len(elements),
            "offset": offset,
            "page_size": page_size,
            "_embedded": {"elements": elements},
        }
