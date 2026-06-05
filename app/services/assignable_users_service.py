"""AssignableUsersService — picker reads for the project User Management
view and the Task / Subtask assignee picker.

Two surfaces:

  * ``list_role_assignments_for_project`` — every user holding a
    project-scoped role on this project, grouped by role. Mirrors the
    monolith's ``GET /projects/{uuid}/role-assignments`` so the FE can
    avoid a cross-service call to user-mgmt for the read view.

  * ``list_assignable_users_for_project`` — union of project-tier role
    holders + org_admin holders on the project's vendor(s), minus
    admin / super_admin tier. Powers the Task / Sub-Task assignee
    picker (Round 11b spec).
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.core.errors import ProjectNotFoundError
from app.repositories.assignable_users_repository import AssignableUsersRepository
from app.repositories.project_repository import ProjectRepository


class AssignableUsersService:
    def __init__(self, db: Session):
        self.db = db
        self.projects = ProjectRepository(db)
        self.repo = AssignableUsersRepository(db)

    def list_role_assignments_for_project(
        self, project_id: str,
    ) -> Dict[str, Any]:
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError(f"Project with ID {project_id} not found")
        rows = self.repo.list_role_assignments_for_project(project_id)

        buckets: "OrderedDict[int, Dict[str, Any]]" = OrderedDict()
        for ura, role, user in rows:
            bucket = buckets.setdefault(role.id, {
                "role_id": role.id,
                "role_name": role.name,
                "users": [],
            })
            bucket["users"].append({
                "id": user.id,
                "login": user.login,
                "email": user.email,
                "full_name": user.full_name,
                "assignment_id": ura.id,
            })
        return {
            # Monolith parity: bare data envelope (no _type/_links wrap).
            "_bare": True,
            "project_id": project.id,
            "project_name": project.name,
            "roles": list(buckets.values()),
        }

    def list_assignable_users_for_project(
        self, project_id: str, *, authorization: str = "",
    ) -> Dict[str, Any]:
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError(f"Project with ID {project_id} not found")
        users: List[Dict[str, Any]] = self.repo.list_assignable_users_for_project(
            project_id, authorization=authorization,
        )
        return {
            # Monolith parity: bare data envelope (no _type/_links wrap).
            "_bare": True,
            "project_id": project.id,
            "project_name": project.name,
            "users": users,
        }
