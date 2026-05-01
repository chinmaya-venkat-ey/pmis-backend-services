"""
Project Member database model.
"""
from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc)
from sqlalchemy import Column, Integer, String, DateTime, Index, ForeignKey, UniqueConstraint, JSON
from ..session import Base


class ProjectMemberModel(Base):
    """Project Member database model."""

    __tablename__ = "project_members"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    roles = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # Unique constraint: one membership per project-user pair
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_user"),
        Index("idx_project_members_project_id", "project_id"),
        Index("idx_project_members_user_id", "user_id"),
        Index("idx_project_members_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ProjectMemberModel(id={self.id}, project_id={self.project_id}, user_id={self.user_id})>"
