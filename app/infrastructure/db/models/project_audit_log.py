"""
Project audit log database model.
"""
from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc)
from sqlalchemy import Column, Integer, String, DateTime, Index, ForeignKey, JSON
from ..session import Base


class ProjectAuditLogModel(Base):
    """Persisted record of a project-side state change or edit."""

    __tablename__ = "project_audit_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    actor_id = Column(Integer, nullable=True, index=True)
    action = Column(String(64), nullable=False, index=True)
    before = Column(JSON, nullable=True)
    after = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("idx_project_audit_logs_project_id", "project_id"),
        Index("idx_project_audit_logs_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ProjectAuditLogModel(id={self.id}, project_id={self.project_id}, action='{self.action}')>"
