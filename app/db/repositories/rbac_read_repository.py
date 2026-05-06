"""Read-only RBAC lookup (doc 38).

User-service is the AUTHORITATIVE writer for ``users``, ``roles``,
``role_permissions``, ``user_roles``, ``user_permissions``. This service
only reads them — to gate ``/api/v3/master/*`` endpoints with the
permission a JWT-authenticated caller actually holds.

We keep the model definitions here lightweight (raw SQL) so this
repo doesn't need to mirror the full SQLAlchemy model files from
user-service. The auth middleware calls
``effective_permissions_for_user(user_id)`` once per request.
"""
from __future__ import annotations

from typing import Set

from sqlalchemy import text
from sqlalchemy.orm import Session


class RbacReadRepository:
    def __init__(self, db: Session):
        self.db = db

    def effective_permissions_for_user(self, user_id: str) -> Set[str]:
        """Union of role-derived ∪ direct grants, as a set of codes.

        One indexed JOIN against the shared Postgres. Returns ``set()``
        when ``user_id`` is None / empty / not present.
        """
        if not user_id:
            return set()
        sql = text(
            "SELECT permission_code AS code "
            "FROM role_permissions rp "
            "JOIN user_roles ur ON ur.role_id = rp.role_id "
            "WHERE ur.user_id = :uid "
            "UNION "
            "SELECT permission_code AS code "
            "FROM user_permissions WHERE user_id = :uid"
        )
        rows = self.db.execute(sql, {"uid": user_id}).fetchall()
        return {r.code for r in rows if r.code}

    def is_admin(self, user_id: str) -> bool:
        """True iff the user holds the seeded ``admin`` role."""
        if not user_id:
            return False
        sql = text(
            "SELECT 1 FROM user_roles ur "
            "JOIN roles r ON r.id = ur.role_id "
            "WHERE ur.user_id = :uid AND r.name = 'admin' LIMIT 1"
        )
        return self.db.execute(sql, {"uid": user_id}).fetchone() is not None

    def is_revoked(self, jti: str) -> bool:
        """JWT JTI blacklist check."""
        if not jti:
            return False
        sql = text(
            "SELECT 1 FROM revoked_tokens WHERE jti = :jti LIMIT 1"
        )
        return self.db.execute(sql, {"jti": jti}).fetchone() is not None
