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

    Doc 47 (audit enrichment): denormalized columns captured at write
    time so a log row stays meaningful even if the source rows later
    rename, get re-owned, or get soft-deleted. ``actor_login``,
    ``actor_code``, ``project_name``, ``project_status``, ``owner`` are
    all NOT NULL — the audit row is rejected at insert if the writer
    can't supply them. ``before`` / ``after`` stay nullable because
    create- and delete-class actions don't have one of those halves by
    design.
    """

    __tablename__ = "project_audit_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    # Doc 47: project_name + project_status + owner are snapshotted at
    # write time so the log row reads correctly even after the project
    # is renamed / closed / has its owner changed.
    project_name = Column(String(255), nullable=False)
    project_status = Column(String(50), nullable=False)
    owner = Column(String(50), nullable=False)
    # Doc 26: users.id flipped to UUID String(36). ``actor_id`` stays
    # nullable because some system-initiated actions (boot-time seeds,
    # background jobs) have no user attached.
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    # Doc 47: actor_login is the snapshotted username at write time.
    # NOT NULL — for system actions the writer passes 'system'.
    actor_login = Column(String(50), nullable=False, index=True)
    # Doc 47: actor_code mirrors users.user_code (e.g. US-CHIN-...).
    # Snapshotted at write time + NOT NULL with 'system' fallback for
    # actions where there's no real user (boot seeds, jobs).
    actor_code = Column(String(40), nullable=False)
    # Doc 47: actor_role flipped to NOT NULL with 'system' fallback so
    # every row identifies the role bucket of the actor.
    actor_role = Column(String(50), nullable=False, index=True)
    action = Column(String(64), nullable=False, index=True)
    before = Column(JSON, nullable=True)
    after = Column(JSON, nullable=True)
    created_at = Column(UtcDateTime, default=_utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("idx_project_audit_logs_project_id", "project_id"),
        Index("idx_project_audit_logs_created_at", "created_at"),
        Index("idx_project_audit_logs_action", "action"),
        Index("idx_project_audit_logs_actor_login", "actor_login"),
    )

    def __repr__(self) -> str:
        return f"<ProjectAuditLogModel(id={self.id}, project_id={self.project_id}, action='{self.action}')>"
