"""User-Role assignment (doc 21 part B)."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String

from ..utc_datetime import UtcDateTime
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class UserRoleModel(Base):
    __tablename__ = "user_roles"

    # Doc 26: users.id flipped to UUID String(36); the FK column type
    # follows. ``role_id`` stays Integer — roles.id PK was intentionally
    # left as Integer (admin-managed catalog, not user-facing).
    user_id = Column(
        String(36), ForeignKey("users.id"), primary_key=True, nullable=False,
    )
    role_id = Column(
        Integer, ForeignKey("roles.id"), primary_key=True, nullable=False,
    )
    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        Index("idx_user_roles_user", "user_id"),
        Index("idx_user_roles_role", "role_id"),
    )
