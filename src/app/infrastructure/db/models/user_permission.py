"""User-Permission direct grant (doc 21 part B).

Direct grants are *additive* on top of role-derived permissions. There
is no deny semantics — to revoke, the row is deleted.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String

from ..utc_datetime import UtcDateTime
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class UserPermissionModel(Base):
    __tablename__ = "user_permissions"

    # Doc 26: users.id flipped to UUID String(36); the FK column type follows.
    user_id = Column(
        String(36), ForeignKey("users.id"), primary_key=True, nullable=False,
    )
    permission_code = Column(
        String(128),
        ForeignKey("permissions.code"),
        primary_key=True,
        nullable=False,
    )
    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        Index("idx_user_permissions_user", "user_id"),
        Index("idx_user_permissions_permission", "permission_code"),
    )
