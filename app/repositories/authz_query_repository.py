"""AuthzQueryRepository — RBAC *discovery* reads for consuming services.

The enforcement surface (`/authz/context`) answers "can this token do X?".
This repository backs the *discovery* surface (`/authz/users`): "WHICH users
match this RBAC predicate?" — the half a boolean check API cannot serve
(pickers, list-scoping). user-svc answers the RBAC half; the calling service
supplies the resource facts (its own vendor/division/project data) and unions
locally.

Every query filters soft-deleted users out. Admin-tier detection mirrors the
hardened rule (legacy `user_roles` OR a GLOBAL-scope admin assignment — the
Round-8 C5 definition), so consumers stop re-deriving it themselves.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.models.role import Role
from app.models.user import User
from app.models.user_role import UserRole
from app.models.user_role_assignment import UserRoleAssignment


_ADMIN_ROLE_NAMES = ("admin", "super_admin")


class AuthzQueryRepository:
    def __init__(self, db: Session):
        self.db = db

    def users_by_project_role(
        self, project_id: str, role_name: Optional[str] = None,
    ) -> List[User]:
        """Users holding a project-scoped assignment on ``project_id``
        (optionally narrowed to one ``role_name``)."""
        stmt = (
            select(User)
            .join(UserRoleAssignment, UserRoleAssignment.user_id == User.id)
            .where(UserRoleAssignment.project_id == project_id)
            .where(User.deleted_at.is_(None))
        )
        if role_name:
            stmt = stmt.join(Role, Role.id == UserRoleAssignment.role_id).where(
                Role.name == role_name
            )
        return list(self.db.execute(stmt).scalars().unique().all())

    def users_by_org_role(
        self, vendor_ids: Sequence[str], role_name: Optional[str] = None,
    ) -> List[User]:
        """Users holding an org-scoped assignment on any of ``vendor_ids``
        (optionally narrowed to one ``role_name``, e.g. ``org_admin``)."""
        if not vendor_ids:
            return []
        stmt = (
            select(User)
            .join(UserRoleAssignment, UserRoleAssignment.user_id == User.id)
            .where(UserRoleAssignment.organization_id.in_(list(vendor_ids)))
            .where(User.deleted_at.is_(None))
        )
        if role_name:
            stmt = stmt.join(Role, Role.id == UserRoleAssignment.role_id).where(
                Role.name == role_name
            )
        return list(self.db.execute(stmt).scalars().unique().all())

    def users_by_division(self, divisions: Sequence[str]) -> List[User]:
        """Users whose ``users.division`` is in ``divisions``."""
        if not divisions:
            return []
        stmt = (
            select(User)
            .where(User.division.in_(list(divisions)))
            .where(User.deleted_at.is_(None))
        )
        return list(self.db.execute(stmt).scalars().unique().all())

    def users_by_division_role(
        self,
        divisions: Sequence[str],
        role_name: str,
        vendor_id: Optional[str] = None,
    ) -> List[User]:
        """Users whose ``users.division`` is in ``divisions`` AND who hold
        ``role_name`` in EITHER tier (legacy ``user_roles`` or Doc-41
        ``user_role_assignments``), optionally restricted to one organization
        via ``vendor_id``.

        Bug #226: the Manage-Team role pickers must show only the relevant
        role-holders — e.g. Activity Approvers = ``division_approver`` holders
        whose division is this activity's concerned division and whose
        ``vendor_id`` is the UIDAI organization.
        """
        if not divisions or not role_name:
            return []
        role_id = self.db.execute(
            select(Role.id).where(Role.name == role_name)
        ).scalar_one_or_none()
        if role_id is None:
            return []
        holds_role = or_(
            exists().where(and_(
                UserRoleAssignment.user_id == User.id,
                UserRoleAssignment.role_id == role_id,
            )),
            exists().where(and_(
                UserRole.user_id == User.id,
                UserRole.role_id == role_id,
            )),
        )
        stmt = (
            select(User)
            .where(User.division.in_(list(divisions)))
            .where(User.deleted_at.is_(None))
            .where(holds_role)
        )
        if vendor_id:
            stmt = stmt.where(User.vendor_id == vendor_id)
        return list(self.db.execute(stmt).scalars().unique().all())

    def admin_tier_user_ids(self) -> Set[str]:
        """User ids that are admin/super_admin tier — legacy ``user_roles``
        OR a GLOBAL-scope (org_id IS NULL AND project_id IS NULL)
        assignment. Round-8 C5: a scoped admin row does NOT count."""
        ids: Set[str] = set()
        legacy = self.db.execute(
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.name.in_(_ADMIN_ROLE_NAMES))
        ).all()
        ids.update(uid for (uid,) in legacy)
        scoped = self.db.execute(
            select(UserRoleAssignment.user_id)
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .where(Role.name.in_(_ADMIN_ROLE_NAMES))
            .where(UserRoleAssignment.organization_id.is_(None))
            .where(UserRoleAssignment.project_id.is_(None))
        ).all()
        ids.update(uid for (uid,) in scoped)
        return ids

    def roles_by_user_ids(
        self, user_ids: Sequence[str],
    ) -> Dict[str, List[str]]:
        """Batched {user_id: [sorted distinct role names]} across both the
        legacy ``user_roles`` tier and the Doc-41 ``user_role_assignments``
        tier. Lets a consumer project a display 'orgRole' without N+1."""
        out: Dict[str, Set[str]] = {}
        if not user_ids:
            return {}
        ids = list(user_ids)
        scoped = self.db.execute(
            select(UserRoleAssignment.user_id, Role.name)
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .where(UserRoleAssignment.user_id.in_(ids))
        ).all()
        for uid, name in scoped:
            out.setdefault(uid, set()).add(name)
        legacy = self.db.execute(
            select(UserRole.user_id, Role.name)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(ids))
        ).all()
        for uid, name in legacy:
            out.setdefault(uid, set()).add(name)
        return {uid: sorted(names) for uid, names in out.items()}
