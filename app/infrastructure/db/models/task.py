"""Task SQLAlchemy model (parent: activity)."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Text, Index, CheckConstraint, text,
)
from ..utc_datetime import UtcDateTime
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class TaskModel(Base):
    """Tasks under an activity. Has type + optional actual dates."""
    __tablename__ = "tasks"

    id = Column(
        String(36), primary_key=True, index=True,
        default=lambda: str(uuid4()),
    )
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    activity_id = Column(String(36), ForeignKey("activities.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    # Doc 38: ``type`` no longer accepted on create — inherited from parent
    # activity (which itself is now nullable). Column kept for legacy rows.
    type = Column(String(20), nullable=True)

    start_date = Column(UtcDateTime, nullable=False)
    end_date = Column(UtcDateTime, nullable=False)
    actual_start_date = Column(UtcDateTime, nullable=True)
    actual_end_date = Column(UtcDateTime, nullable=True)

    position = Column(Integer, nullable=False, default=0)

    resource_mode = Column(String(10), nullable=True)
    resource_count = Column(Integer, nullable=True)

    # Doc 38: lifecycle status, settable via PATCH only (not on create).
    # NULL on legacy rows + on freshly-created rows that haven't been
    # PATCHed yet.
    status = Column(String(32), nullable=True, index=True)

    # Doc 41 follow-up: optional single assignee (FE dropdown — picks one
    # active user from the users catalog). Independent per-level: task's
    # assignee does NOT cascade to / from its subtasks. NULL = unassigned.
    # Wire keyword: ``assignedTo``; emitted alongside ``assignedToName``.
    assigned_to = Column(
        String(36), ForeignKey("users.id"), nullable=True, index=True,
    )

    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    updated_at = Column(UtcDateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    # Doc 26: users.id flipped to UUID String(36).
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    deleted_at = Column(UtcDateTime, nullable=True, index=True)

    __table_args__ = (
        CheckConstraint(
            # Doc 38: NULL allowed for new rows (type deprecated).
            "type IS NULL OR type IN ('standard', 'resource', 'transactional')",
            name="ck_tasks_type",
        ),
        CheckConstraint(
            "resource_mode IS NULL OR resource_mode IN ('count', 'details')",
            name="ck_tasks_resource_mode",
        ),
        CheckConstraint(
            "resource_count IS NULL OR resource_count >= 1",
            name="ck_tasks_resource_count_positive",
        ),
        Index("idx_tasks_activity_live", "activity_id", "deleted_at"),
        Index("idx_tasks_activity_position", "activity_id", "position"),
        Index("idx_tasks_project_live", "project_id", "deleted_at"),
        # One LIVE task per (activity_id, position) — drives label rank
        # for T{m}.{a}.{t}.
        Index(
            "uq_tasks_activity_position_live",
            "activity_id", "position",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<TaskModel(id='{self.id}', activity_id='{self.activity_id}', name='{self.name}')>"
