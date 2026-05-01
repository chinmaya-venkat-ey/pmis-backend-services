"""Project-member mapping table.

Owned jointly: this service writes a row when a user is created (so the
user gets immediate access to their assigned projects), and the
project-service / monolith reads them. Schema mirrors monolith exactly.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)

from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ProjectMemberModel(Base):
    __tablename__ = "project_members"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        String(36), ForeignKey("projects.id"), nullable=False, index=True,
    )
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True,
    )
    # Per-project role list (free-form for now; future: typed enum).
    roles = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_user"),
        Index("idx_project_members_project_id", "project_id"),
        Index("idx_project_members_user_id", "user_id"),
        Index("idx_project_members_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectMemberModel(id={self.id}, "
            f"project_id={self.project_id}, user_id={self.user_id})>"
        )
