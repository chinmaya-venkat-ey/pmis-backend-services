"""UserRoleAssignmentRepository — Doc-41 scoped role-assignment CRUD + queries."""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models._cross_schema import Project, ProjectVendor, Vendor
from app.models.role import Role
from app.models.user import User
from app.models.user_role_assignment import UserRoleAssignment


class UserRoleAssignmentRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ reads

    def get_by_id(self, assignment_id: int) -> Optional[UserRoleAssignment]:
        return self.db.get(UserRoleAssignment, assignment_id)

    def list_by_user(
        self, user_id: str,
    ) -> List[Tuple[UserRoleAssignment, Role]]:
        stmt = (
            select(UserRoleAssignment, Role)
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .where(UserRoleAssignment.user_id == user_id)
            .order_by(UserRoleAssignment.id.asc())
        )
        return [(a, r) for a, r in self.db.execute(stmt).all()]

    def list_by_project(
        self, project_id: str,
    ) -> List[Tuple[UserRoleAssignment, Role, User]]:
        """Return all assignments scoped to a specific project_id."""
        stmt = (
            select(UserRoleAssignment, Role, User)
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .join(User, User.id == UserRoleAssignment.user_id)
            .where(UserRoleAssignment.project_id == project_id)
            .order_by(Role.name.asc(), User.login.asc())
        )
        return [(a, r, u) for a, r, u in self.db.execute(stmt).all()]

    def list_by_organization(
        self, organization_id: str,
    ) -> List[Tuple[UserRoleAssignment, Role, User]]:
        stmt = (
            select(UserRoleAssignment, Role, User)
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .join(User, User.id == UserRoleAssignment.user_id)
            .where(UserRoleAssignment.organization_id == organization_id)
            .order_by(Role.name.asc(), User.login.asc())
        )
        return [(a, r, u) for a, r, u in self.db.execute(stmt).all()]

    def find_existing(
        self,
        *,
        user_id: str,
        role_id: int,
        organization_id: Optional[str],
        project_id: Optional[str],
    ) -> Optional[UserRoleAssignment]:
        """Locate an assignment matching the (user, role, scope) triple — for
        idempotent create + duplicate detection."""
        stmt = (
            select(UserRoleAssignment)
            .where(UserRoleAssignment.user_id == user_id)
            .where(UserRoleAssignment.role_id == role_id)
        )
        if organization_id is None:
            stmt = stmt.where(UserRoleAssignment.organization_id.is_(None))
        else:
            stmt = stmt.where(UserRoleAssignment.organization_id == organization_id)
        if project_id is None:
            stmt = stmt.where(UserRoleAssignment.project_id.is_(None))
        else:
            stmt = stmt.where(UserRoleAssignment.project_id == project_id)
        return self.db.execute(stmt).scalars().first()

    # ------------------------------------------------------------------ writes

    def create(
        self,
        *,
        user_id: str,
        role_id: int,
        organization_id: Optional[str] = None,
        project_id: Optional[str] = None,
        created_by_user_id: Optional[str] = None,
    ) -> UserRoleAssignment:
        row = UserRoleAssignment(
            user_id=user_id,
            role_id=role_id,
            organization_id=organization_id,
            project_id=project_id,
            created_by=created_by_user_id,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def delete(self, row: UserRoleAssignment) -> int:
        self.db.delete(row)
        self.db.flush()
        return 1

    # ------------------------------------------------------------------ cross-schema queries

    def list_projects_for_user(self, user_id: str) -> List[Project]:
        """Distinct, non-deleted projects the user has any assignment in."""
        stmt = (
            select(Project)
            .join(UserRoleAssignment, UserRoleAssignment.project_id == Project.id)
            .where(UserRoleAssignment.user_id == user_id)
            .where(Project.deleted_at.is_(None))
            .distinct()
            .order_by(Project.name.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_projects_for_vendor(self, vendor_id: str) -> List[Project]:
        """Mirror of masters-svc's same-named query, scoped here for the
        /user/vendors/{vid}/projects/list endpoint."""
        stmt = (
            select(Project)
            .join(ProjectVendor, ProjectVendor.project_id == Project.id)
            .where(ProjectVendor.vendor_id == vendor_id)
            .where(Project.deleted_at.is_(None))
            .order_by(Project.name.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_users_for_vendor(self, vendor_id: str) -> List[User]:
        """Distinct users whose direct vendor_id matches OR who hold any
        org-scoped assignment with this vendor."""
        stmt_direct = (
            select(User)
            .where(User.vendor_id == vendor_id)
            .where(User.deleted_at.is_(None))
        )
        stmt_org = (
            select(User)
            .join(UserRoleAssignment, UserRoleAssignment.user_id == User.id)
            .where(UserRoleAssignment.organization_id == vendor_id)
            .where(User.deleted_at.is_(None))
        )
        out: dict[str, User] = {}
        for u in self.db.execute(stmt_direct).scalars().all():
            out[u.id] = u
        for u in self.db.execute(stmt_org).scalars().all():
            out[u.id] = u
        return sorted(out.values(), key=lambda u: u.login)

    def project_owning_vendors(self, project_id: str) -> List[str]:
        """Return the vendor_ids that own a project — used by Doc-44 caller
        gates ('org_admin may grant on projects in their own vendor only')."""
        stmt = select(ProjectVendor.vendor_id).where(
            ProjectVendor.project_id == project_id
        )
        return [row[0] for row in self.db.execute(stmt).all()]
