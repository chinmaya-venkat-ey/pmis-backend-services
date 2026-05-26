"""Cross-schema READ-ONLY repository for the users.* RBAC tables.

Used by middleware/auth_middleware.py on every authed request to:
  1. Check if the JWT's jti is in users.revoked_tokens.
  2. Hydrate user_permissions (flat union, role-derived + direct grants).
  3. Hydrate scoped_permissions ({(kind, id): set(codes)}).
  4. Check is_admin via the seeded `admin` / `super_admin` role.

NEVER writes to users.* — that's user-svc's job.
"""
from __future__ import annotations

from typing import Dict, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models._cross_schema import (
    RevokedToken,
    Role,
    RolePermission,
    UserPermission,
    UserRole,
    UserRoleAssignment,
)


_ADMIN_ROLE_NAMES = ("admin", "super_admin")


class RbacReadRepository:
    def __init__(self, db: Session):
        self.db = db

    def is_revoked(self, jti: str) -> bool:
        if not jti:
            return False
        return self.db.get(RevokedToken, jti) is not None

    def effective_permissions_for_user(self, user_id: str) -> Set[str]:
        """Flat union of role-derived + direct-grant permission codes."""
        if not user_id:
            return set()

        perms: Set[str] = set()

        stmt_legacy = (
            select(RolePermission.permission_code)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
        )
        for (code,) in self.db.execute(stmt_legacy).all():
            perms.add(code)

        stmt_scoped = (
            select(RolePermission.permission_code)
            .join(UserRoleAssignment, UserRoleAssignment.role_id == RolePermission.role_id)
            .where(UserRoleAssignment.user_id == user_id)
        )
        for (code,) in self.db.execute(stmt_scoped).all():
            perms.add(code)

        stmt_direct = select(UserPermission.permission_code).where(
            UserPermission.user_id == user_id
        )
        for (code,) in self.db.execute(stmt_direct).all():
            perms.add(code)

        return perms

    def effective_permissions_by_scope(
        self, user_id: str,
    ) -> Dict[Tuple[str, Optional[str]], Set[str]]:
        """Doc-41 scoped permission map: {(kind, scope_id): set(codes)}."""
        scoped: Dict[Tuple[str, Optional[str]], Set[str]] = {}
        if not user_id:
            return scoped

        legacy_codes: Set[str] = set()
        stmt_legacy = (
            select(RolePermission.permission_code)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
        )
        for (code,) in self.db.execute(stmt_legacy).all():
            legacy_codes.add(code)
        if legacy_codes:
            scoped[("global", None)] = legacy_codes

        stmt_scoped = (
            select(
                RolePermission.permission_code,
                UserRoleAssignment.organization_id,
                UserRoleAssignment.project_id,
            )
            .join(UserRoleAssignment, UserRoleAssignment.role_id == RolePermission.role_id)
            .where(UserRoleAssignment.user_id == user_id)
        )
        for code, org_id, project_id in self.db.execute(stmt_scoped).all():
            if project_id is not None:
                key: Tuple[str, Optional[str]] = ("project", project_id)
            elif org_id is not None:
                key = ("org", org_id)
            else:
                key = ("global", None)
            scoped.setdefault(key, set()).add(code)

        direct_codes: Set[str] = set()
        stmt_direct = select(UserPermission.permission_code).where(
            UserPermission.user_id == user_id
        )
        for (code,) in self.db.execute(stmt_direct).all():
            direct_codes.add(code)
        if direct_codes:
            scoped.setdefault(("global", None), set()).update(direct_codes)

        return scoped

    def is_admin(self, user_id: str) -> bool:
        if not user_id:
            return False

        stmt_legacy = (
            select(Role.id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .where(Role.name.in_(_ADMIN_ROLE_NAMES))
            .limit(1)
        )
        if self.db.execute(stmt_legacy).first():
            return True

        stmt_scoped = (
            select(Role.id)
            .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
            .where(UserRoleAssignment.user_id == user_id)
            .where(Role.name.in_(_ADMIN_ROLE_NAMES))
            .limit(1)
        )
        return bool(self.db.execute(stmt_scoped).first())
