"""
Project audit log database model.
"""
from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc)
from sqlalchemy import Column, Integer, String, DateTime, Index, ForeignKey, JSON
from ..utc_datetime import UtcDateTime
from ..session import Base


class ProjectAuditLogModel(Base):
    """Persisted record of a project-side state change or edit.

    Doc 33: ``actor_role`` column added so audit rows record the role
    bucket the actor occupied at the time of the change (``admin`` /
    ``member`` / ``vendor`` / ``viewer``). Important for transparency
    after the versioning workflow was removed and vendors gained
    write access to the same project surface admins/members had.
    """

    __tablename__ = "project_audit_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    # Doc 26: users.id flipped to UUID String(36).
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    actor_role = Column(String(50), nullable=True, index=True)
    action = Column(String(64), nullable=False, index=True)
    before = Column(JSON, nullable=True)
    after = Column(JSON, nullable=True)
    created_at = Column(UtcDateTime, default=_utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("idx_project_audit_logs_project_id", "project_id"),
        Index("idx_project_audit_logs_created_at", "created_at"),
        Index("idx_project_audit_logs_action", "action"),
    )

    def __repr__(self) -> str:
        return f"<ProjectAuditLogModel(id={self.id}, project_id={self.project_id}, action='{self.action}')>"
