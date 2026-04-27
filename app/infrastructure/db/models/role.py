"""Role database model — owned by pmis-user-service."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Index, Integer, String

from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class RoleModel(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    permissions = Column(JSON, default=list, nullable=False)
    builtin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        Index("idx_roles_name", "name"),
        Index("idx_roles_builtin", "builtin"),
    )

    def __repr__(self) -> str:
        return f"<RoleModel(id={self.id}, name='{self.name}', builtin={self.builtin})>"
