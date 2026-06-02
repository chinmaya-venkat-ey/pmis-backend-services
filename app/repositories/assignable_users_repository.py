"""Cross-schema reader for the per-project user pickers.

Two read surfaces:

  - ``list_role_assignments_for_project`` — every user with a
    project-scoped role on this project, grouped by role. Powers
    ``GET /project/projects/{uuid}/role-assignments``.

  - ``list_assignable_users_for_project`` — union of (a) project-tier
    role holders on this project AND (b) org_admin holders on the
    project's vendor(s), minus admin/super_admin tier users. Powers
    ``GET /project/projects/{uuid}/assignable-users``.

Both read cross-schema mirrors (``users.users``, ``users.roles``,
``users.user_roles``, ``users.user_role_assignments``) plus this
service's own ``project.project_vendors`` table.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models._cross_schema import (
    Role,
    User as MirrorUser,
    UserRole,
    UserRoleAssignment,
)
from app.models.project_vendor import ProjectVendor


_ADMIN_ROLE_NAMES = ("admin", "super_admin")
_ORG_ROLE_PRIORITY = (
    "super_admin", "admin", "org_admin", "project_admin", "project_member",
)


class AssignableUsersRepository:
    def __init__(self, db: Session):
        self.db = db

    # ----- role assignments listing -----------------------------------

    def list_role_assignments_for_project(
        self, project_id: str,
    ) -> List[Tuple[Any, Any, Any]]:
        """Return ``[(UserRoleAssignment, Role, User), ...]`` for users with
        a project-scoped grant on ``project_id``. Newest-first ordering
        by role name + user login keeps the FE grouping deterministic."""
        stmt = (
            select(UserRoleAssignment, Role, MirrorUser)
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .join(MirrorUser, MirrorUser.id == UserRoleAssignment.user_id)
            .where(UserRoleAssignment.project_id == project_id)
            .where(MirrorUser.deleted_at.is_(None))
            .order_by(Role.name.asc(), MirrorUser.login.asc())
        )
        return [tuple(row) for row in self.db.execute(stmt).all()]

    # ----- assignable users picker ------------------------------------

    def list_assignable_users_for_project(
        self, project_id: str,
    ) -> List[Dict[str, Any]]:
        """Union of project-tier holders + org_admin holders on the
        project's vendors. Admin / super_admin tier users are filtered
        out per spec (admins don't appear in project pickers).

        Each entry carries ``id`` / ``login`` / ``firstName`` /
        ``lastName`` / ``email`` / ``orgRole`` ready for FE rendering.
        """
        # (a) Project-scoped holders.
        project_users = self.db.execute(
            select(MirrorUser)
            .join(
                UserRoleAssignment,
                UserRoleAssignment.user_id == MirrorUser.id,
            )
            .where(UserRoleAssignment.project_id == project_id)
            .where(MirrorUser.deleted_at.is_(None))
        ).scalars().all()

        # (b) Org-admin holders on the project's vendor(s).
        vendor_ids = list(self.db.execute(
            select(ProjectVendor.vendor_id)
            .where(ProjectVendor.project_id == project_id)
        ).scalars())
        org_admin_users: List[Any] = []
        if vendor_ids:
            org_admin_users = list(self.db.execute(
                select(MirrorUser)
                .join(
                    UserRoleAssignment,
                    UserRoleAssignment.user_id == MirrorUser.id,
                )
                .join(Role, Role.id == UserRoleAssignment.role_id)
                .where(UserRoleAssignment.organization_id.in_(vendor_ids))
                .where(Role.name == "org_admin")
                .where(MirrorUser.deleted_at.is_(None))
            ).scalars())

        # Admin-tier exclusion set (any form: legacy user_roles OR
        # scoped user_role_assignments global row).
        admin_user_ids: set[str] = set()
        admin_legacy = self.db.execute(
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.name.in_(_ADMIN_ROLE_NAMES))
        ).all()
        admin_user_ids.update(uid for (uid,) in admin_legacy)
        admin_scoped = self.db.execute(
            select(UserRoleAssignment.user_id)
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .where(Role.name.in_(_ADMIN_ROLE_NAMES))
            .where(UserRoleAssignment.organization_id.is_(None))
            .where(UserRoleAssignment.project_id.is_(None))
        ).all()
        admin_user_ids.update(uid for (uid,) in admin_scoped)

        # Highest-tier orgRole projection per user.
        def _org_role_of(user_obj) -> str | None:
            held = {
                n for (n,) in self.db.execute(
                    select(Role.name)
                    .join(
                        UserRoleAssignment,
                        UserRoleAssignment.role_id == Role.id,
                    )
                    .where(UserRoleAssignment.user_id == user_obj.id)
                    .distinct()
                ).all()
            }
            for tier in _ORG_ROLE_PRIORITY:
                if tier in held:
                    return tier
            return None

        seen: Dict[str, Dict[str, Any]] = {}
        for u in list(project_users) + list(org_admin_users):
            if u.id in seen or u.id in admin_user_ids:
                continue
            seen[u.id] = {
                "id": u.id,
                "login": u.login,
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "org_role": _org_role_of(u),
            }
        return sorted(seen.values(), key=lambda x: (x["login"] or ""))
