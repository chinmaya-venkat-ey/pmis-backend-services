"""Cross-schema READ-ONLY repository for the users.* RBAC tables.

Used by middleware/auth_middleware.py on every authed request to:
  1. Check if the JWT's jti is in users.revoked_tokens (early-rejection).
  2. Hydrate user_permissions = effective set (role-derived UNION direct grants).
  3. Check is_admin = does the user hold the seeded `admin` or `super_admin` role.

All reads use SQLAlchemy 2.0 select() against the cross-schema mirrors in
app/models/_cross_schema.py. NEVER writes to users.* — that's user-svc's job.

The "admin" detection matches the monolith convention: role name in
('admin', 'super_admin') grants the admin shortcut (bypasses per-permission
checks).
"""
from __future__ import annotations

from typing import Set

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models._cross_schema import (
    Role,
    RolePermission,
    UserPermission,
    UserRole,
    UserRoleAssignment,
    RevokedToken,
)


_ADMIN_ROLE_NAMES = ("admin", "super_admin")


class RbacReadRepository:
    """Cross-schema reader for users.* — never mutates."""

    def __init__(self, db: Session):
        self.db = db

    def is_revoked(self, jti: str) -> bool:
        """True if the jti is in users.revoked_tokens. Cheap PK lookup."""
        if not jti:
            return False
        row = self.db.get(RevokedToken, jti)
        return row is not None

    def effective_permissions_for_user(self, user_id: str) -> Set[str]:
        """Union of:
          - role-derived perms (via user_roles + user_role_assignments → role_permissions)
          - direct grants (via user_permissions)
        Returns a flat set of permission_code strings.
        """
        if not user_id:
            return set()

        perms: Set[str] = set()

        # Role-derived (legacy global tier — users.user_roles)
        stmt_legacy = (
            select(RolePermission.permission_code)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
        )
        for (code,) in self.db.execute(stmt_legacy).all():
            perms.add(code)

        # Role-derived (Doc-41 scoped — users.user_role_assignments)
        # For masters-svc's broad permission gate, we treat ANY scoped
        # assignment as granting the role's permissions to the user.
        # Row-level scoping (e.g. "this vendor only") is applied as a
        # service-layer filter, not at the permission level (Option C
        # spec — see PLAN.md §9.6).
        stmt_scoped = (
            select(RolePermission.permission_code)
            .join(
                UserRoleAssignment,
                UserRoleAssignment.role_id == RolePermission.role_id,
            )
            .where(UserRoleAssignment.user_id == user_id)
        )
        for (code,) in self.db.execute(stmt_scoped).all():
            perms.add(code)

        # Direct user grants (users.user_permissions)
        stmt_direct = select(UserPermission.permission_code).where(
            UserPermission.user_id == user_id
        )
        for (code,) in self.db.execute(stmt_direct).all():
            perms.add(code)

        return perms

    def is_admin(self, user_id: str) -> bool:
        """True if the user holds the seeded `admin` OR `super_admin` role
        (via either users.user_roles or users.user_role_assignments)."""
        if not user_id:
            return False

        # Legacy global tier
        stmt_legacy = (
            select(Role.id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .where(Role.name.in_(_ADMIN_ROLE_NAMES))
            .limit(1)
        )
        if self.db.execute(stmt_legacy).first():
            return True

        # Doc-41 scoped tier
        stmt_scoped = (
            select(Role.id)
            .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
            .where(UserRoleAssignment.user_id == user_id)
            .where(Role.name.in_(_ADMIN_ROLE_NAMES))
            .limit(1)
        )
        if self.db.execute(stmt_scoped).first():
            return True

        return False
