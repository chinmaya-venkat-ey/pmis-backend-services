"""
Role database model.

Doc 21 part B: the legacy JSON ``permissions`` column was replaced by
the ``role_permissions`` join table. The column is no longer present on
the model; the alembic migration drops it on Postgres and the SQLite
drift healer leaves the column ignored.

``description`` was added for the role-management UI.
"""
from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc)
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Index
from ..utc_datetime import UtcDateTime
from ..session import Base


class RoleModel(Base):
    """Role database model."""

    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(String(1024), nullable=True)
    builtin = Column(Boolean, default=False, nullable=False)
    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    updated_at = Column(UtcDateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # Indexes
    __table_args__ = (
        Index("idx_roles_name", "name"),
        Index("idx_roles_builtin", "builtin"),
    )

    def __repr__(self) -> str:
        return f"<RoleModel(id={self.id}, name='{self.name}', builtin={self.builtin})>"
