"""AuditLogService — paginated read of ``project.project_audit_logs`` for
a single project.

Powers ``GET /project/projects/{uuid}/audit-logs``. Returns the project
header alongside the paginated audit rows so the FE can render context
without a separate project read.
"""
from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.core.errors import ProjectNotFoundError
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_repository import ProjectRepository


class AuditLogService:
    def __init__(self, db: Session):
        self.db = db
        self.projects = ProjectRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    def list_for_project(
        self, project_id: str, *, offset: int = 1, page_size: int = 50,
    ) -> Dict[str, Any]:
        project = self.projects.get_by_id(project_id, include_deleted=True)
        if project is None:
            raise ProjectNotFoundError(f"Project with ID {project_id} not found")
        rows, total = self.audit.list_for_project(
            project_id, offset=offset, page_size=page_size,
        )
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
            "count": len(rows),
            "offset": offset,
            "page_size": page_size,
            "_embedded": {"elements": rows},
        }
