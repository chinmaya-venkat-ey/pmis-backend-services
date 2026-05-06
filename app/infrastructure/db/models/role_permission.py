"""Role-Permission assignment (doc 21 part B)."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String

from ..utc_datetime import UtcDateTime
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class RolePermissionModel(Base):
    __tablename__ = "role_permissions"

    role_id = Column(
        Integer, ForeignKey("roles.id"), primary_key=True, nullable=False,
    )
    permission_code = Column(
        String(128),
        ForeignKey("permissions.code"),
        primary_key=True,
        nullable=False,
    )
    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        Index("idx_role_permissions_role", "role_id"),
        Index("idx_role_permissions_permission", "permission_code"),
    )
