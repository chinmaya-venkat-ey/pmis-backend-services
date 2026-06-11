"""UserRoleAssignmentRepository — Doc-41 scoped role-assignment CRUD + queries."""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import and_, delete as sa_delete, or_, select
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

    def delete_by_project_and_role(self, project_id: str, role_id: int) -> int:
        """Delete all assignments for a given project_id + role_id (bulk-replace helper)."""
        result = self.db.execute(
            sa_delete(UserRoleAssignment)
            .where(UserRoleAssignment.project_id == project_id)
            .where(UserRoleAssignment.role_id == role_id)
        )
        self.db.flush()
        return result.rowcount

    # ------------------------------------------------------------------ cross-schema queries

    def list_projects_for_user(self, user_id: str) -> List[Project]:
        """Distinct, non-deleted projects the user has any role-assignment
        path into.

        Two sources are unioned so this listing matches what the auth
        layer (``rbac_repository.effective_permissions_by_scope`` —
        Round-7 vendor->project projection) treats as the user's
        effective project set:

          (a) Direct project-scoped grants
              ``user_role_assignment.project_id = P``.
              After the r014 normalisation the bulk of grants —
              project_admin, project_member — live here.

          (b) Vendor-scope projection
              ``user_role_assignment.organization_id = V``
              (with ``project_id IS NULL``) → every project mapped to V
              via ``project.project_vendors``. Currently this catches
              org_admin; importantly the join carries NO role-name
              filter, so any future role granted at vendor scope is
              auto-included with no code change — matching how
              Round-7 already behaves at permission-check time.

        Bug-Hunter leak (b) follow-up: a user with only an org_admin
        grant on UIDAI used to see an empty Projects list even though
        they could open every UIDAI project at runtime. Source (b)
        closes that gap.

        SEE ALSO `<PMIS-root>/role-vendor-projection-option3.md` (local
        design note, not committed) for Option 3 — making the
        projection rule a `users.roles` column instead of "any
        vendor-scoped row counts". The shape of THIS query stays the
        same under Option 3; only source (b)'s join gains a
        ``Role.vendor_projection IS TRUE`` filter.
        """
        # (a) direct project grants
        stmt_direct = (
            select(Project)
            .join(UserRoleAssignment, UserRoleAssignment.project_id == Project.id)
            .where(UserRoleAssignment.user_id == user_id)
            .where(Project.deleted_at.is_(None))
        )
        # (b) vendor-scope projection — any role at vendor scope.
        stmt_via_vendor = (
            select(Project)
            .join(
                ProjectVendor,
                ProjectVendor.project_id == Project.id,
            )
            .join(
                UserRoleAssignment,
                UserRoleAssignment.organization_id == ProjectVendor.vendor_id,
            )
            .where(UserRoleAssignment.user_id == user_id)
            .where(UserRoleAssignment.project_id.is_(None))
            .where(Project.deleted_at.is_(None))
        )
        out: dict[str, Project] = {}
        for p in self.db.execute(stmt_direct).scalars().all():
            out[p.id] = p
        for p in self.db.execute(stmt_via_vendor).scalars().all():
            out[p.id] = p
        return sorted(out.values(), key=lambda p: (p.name or ""))

    def list_projects_for_users(self, user_ids: List[str]) -> dict:
        """Per-page batch of :meth:`list_projects_for_user` — one query per
        source (direct + vendor-projection) for ALL ``user_ids``, grouped by
        user_id, each list deduped + sorted identically. Avoids the N+1 in the
        user-list response."""
        out: dict = {uid: {} for uid in user_ids}
        if not user_ids:
            return out
        # (a) direct project grants
        for uid, p in self.db.execute(
            select(UserRoleAssignment.user_id, Project)
            .select_from(Project)
            .join(UserRoleAssignment, UserRoleAssignment.project_id == Project.id)
            .where(UserRoleAssignment.user_id.in_(user_ids))
            .where(Project.deleted_at.is_(None))
        ).all():
            out[uid][p.id] = p
        # (b) vendor-scope projection (any role at vendor scope)
        for uid, p in self.db.execute(
            select(UserRoleAssignment.user_id, Project)
            .select_from(Project)
            .join(ProjectVendor, ProjectVendor.project_id == Project.id)
            .join(UserRoleAssignment, UserRoleAssignment.organization_id == ProjectVendor.vendor_id)
            .where(UserRoleAssignment.user_id.in_(user_ids))
            .where(UserRoleAssignment.project_id.is_(None))
            .where(Project.deleted_at.is_(None))
        ).all():
            out[uid][p.id] = p
        return {uid: sorted(d.values(), key=lambda p: (p.name or "")) for uid, d in out.items()}

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
        org-scoped assignment with this vendor OR who hold any
        project-scoped assignment whose project is mapped to this vendor.

        Bug #133: Project Mapping users (granted at project scope) were
        invisible in the vendor's user list because the prior query only
        checked direct vendor_id + org-scoped grants. Adding the third
        source surfaces every user reachable through the vendor's
        project_vendors mapping.
        """
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
        # Bug #133: include project-scoped role holders on any project
        # mapped to this vendor. Skip projects whose Project row is
        # soft-deleted (matches sibling list_projects_for_user /
        # list_projects_for_vendor queries above; otherwise a deleted
        # project's stale role assignments would leak the user here).
        stmt_project = (
            select(User)
            .join(UserRoleAssignment, UserRoleAssignment.user_id == User.id)
            .join(
                ProjectVendor,
                ProjectVendor.project_id == UserRoleAssignment.project_id,
            )
            .join(Project, Project.id == UserRoleAssignment.project_id)
            .where(ProjectVendor.vendor_id == vendor_id)
            .where(Project.deleted_at.is_(None))
            .where(User.deleted_at.is_(None))
        )
        out: dict[str, User] = {}
        for u in self.db.execute(stmt_direct).scalars().all():
            out[u.id] = u
        for u in self.db.execute(stmt_org).scalars().all():
            out[u.id] = u
        for u in self.db.execute(stmt_project).scalars().all():
            out[u.id] = u
        return sorted(out.values(), key=lambda u: u.login)

    def project_owning_vendors(self, project_id: str) -> List[str]:
        """Return the vendor_ids that own a project — used by Doc-44 caller
        gates ('org_admin may grant on projects in their own vendor only')."""
        stmt = select(ProjectVendor.vendor_id).where(
            ProjectVendor.project_id == project_id
        )
        return [row[0] for row in self.db.execute(stmt).all()]
