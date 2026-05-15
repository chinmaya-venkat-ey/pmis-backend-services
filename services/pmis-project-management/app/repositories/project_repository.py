"""ProjectRepository — CRUD against project.projects + project.project_vendors.

Doc-46 scoping is applied in `list_`: non-admin callers can opt to filter
projects to those they have an assignment on (via users.user_role_assignments
cross-schema). When `caller_user_id` is set + `caller_is_admin` is False,
visibility narrows to projects the caller is on or that map to their vendor.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models._cross_schema import UserRoleAssignment, User as MirrorUser
from app.models.project import Project
from app.models.project_vendor import ProjectVendor


class ProjectRepository:
    def __init__(self, db: Session):
        self.db = db

    # --------------------------------------------------------------- read

    def get_by_id(self, project_id: str) -> Optional[Project]:
        return self.db.get(Project, project_id)

    def get_by_code(self, project_code: str) -> Optional[Project]:
        return self.db.execute(
            select(Project).where(Project.project_code == project_code)
        ).scalar_one_or_none()

    def list_(
        self,
        *,
        offset: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        include_deleted: bool = False,
        caller_user_id: Optional[str] = None,
        caller_is_admin: bool = False,
    ) -> Tuple[List[Project], int]:
        stmt = select(Project)
        count_stmt = select(func.count()).select_from(Project)
        clauses = []
        if not include_deleted:
            clauses.append(Project.deleted_at.is_(None))
        if status is not None:
            clauses.append(Project.status == status)
        if caller_user_id and not caller_is_admin:
            # Doc-46: non-admin sees projects they have an assignment on, OR
            # projects mapped to their vendor.
            caller_vendor_subq = (
                select(MirrorUser.vendor_id)
                .where(MirrorUser.id == caller_user_id)
                .scalar_subquery()
            )
            assignment_subq = (
                select(UserRoleAssignment.project_id)
                .where(UserRoleAssignment.user_id == caller_user_id)
                .where(UserRoleAssignment.project_id.is_not(None))
            )
            vendor_proj_subq = (
                select(ProjectVendor.project_id)
                .where(ProjectVendor.vendor_id == caller_vendor_subq)
            )
            clauses.append(
                or_(
                    Project.id.in_(assignment_subq),
                    Project.id.in_(vendor_proj_subq),
                )
            )
        if clauses:
            stmt = stmt.where(and_(*clauses))
            count_stmt = count_stmt.where(and_(*clauses))

        total = self.db.execute(count_stmt).scalar_one()
        rows = self.db.execute(
            stmt.order_by(Project.created_at.desc())
            .offset(max(0, offset - 1) * page_size)
            .limit(page_size)
        ).scalars().all()
        return list(rows), total

    def list_vendors_for_project(self, project_id: str) -> List[str]:
        return list(
            self.db.execute(
                select(ProjectVendor.vendor_id)
                .where(ProjectVendor.project_id == project_id)
            ).scalars()
        )

    # --------------------------------------------------------------- write

    def create(self, **kwargs) -> Project:
        row = Project(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: Project, **kwargs) -> Project:
        for k, v in kwargs.items():
            setattr(row, k, v)
        self.db.flush()
        return row

    def soft_delete(self, row: Project, *, deleted_by_user_id: Optional[str]) -> Project:
        row.deleted_at = datetime.now(timezone.utc)
        row.deleted_by = deleted_by_user_id
        self.db.flush()
        return row

    def restore(self, row: Project) -> Project:
        row.deleted_at = None
        row.deleted_by = None
        self.db.flush()
        return row

    # --------------------------------------------------------------- vendor mapping

    def set_vendor_mapping(self, project_id: str, vendor_ids: List[str]) -> None:
        """Replace the M:N project↔vendor mapping with the given vendor_ids."""
        self.db.execute(
            ProjectVendor.__table__.delete().where(
                ProjectVendor.project_id == project_id
            )
        )
        for vid in vendor_ids:
            self.db.add(ProjectVendor(project_id=project_id, vendor_id=vid))
        self.db.flush()
