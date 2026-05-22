"""Read-only RBAC queries used by auth middleware.

Reads from the users schema (cross-schema mirror) to resolve permissions
and admin status for an incoming JWT. file-svc does not own any auth tables.
"""
from __future__ import annotations

from typing import Set

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models._cross_schema import (
    Permission,
    RevokedToken,
    Role,
    RolePermission,
    User,
    UserRoleAssignment,
)


class RbacReadRepository:
    def __init__(self, db: Session):
        self.db = db

    def is_revoked(self, jti: str) -> bool:
        row = self.db.execute(
            select(RevokedToken).where(RevokedToken.jti == jti)
        ).scalar_one_or_none()
        return row is not None

    def is_admin(self, user_id: str) -> bool:
        user = self.db.get(User, user_id)
        if user is None:
            return False
        return bool(user.admin)

    def effective_permissions_for_user(self, user_id: str) -> Set[str]:
        """Return the flat set of permission codes the user holds via any role."""
        stmt = (
            select(RolePermission.permission_code)
            .join(UserRoleAssignment, UserRoleAssignment.role_id == RolePermission.role_id)
            .where(UserRoleAssignment.user_id == user_id)
            .distinct()
        )
        rows = self.db.execute(stmt).all()
        return {r[0] for r in rows}
