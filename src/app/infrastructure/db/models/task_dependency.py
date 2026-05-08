"""Task-to-task dependency association (soft-delete).

See ``activity_dependency.py`` for the schema rationale. Same pattern:
- Surrogate UUID PK.
- Partial unique on ``(source_task_id, target_task_id)`` WHERE
  ``deleted_at IS NULL``.
- Hierarchy rule (service-layer): source.activity must already depend on
  target.activity (via ``activity_dependencies``), unless source and target
  share the same activity.
- Same-activity targets always allowed.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, text

from ..utc_datetime import UtcDateTime
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class TaskDependencyModel(Base):
    __tablename__ = "task_dependencies"

    id = Column(
        String(36),
        primary_key=True,
        index=True,
        default=lambda: str(uuid4()),
    )
    source_task_id = Column(
        String(36),
        ForeignKey("tasks.id"),
        nullable=False,
        index=True,
    )
    target_task_id = Column(
        String(36),
        ForeignKey("tasks.id"),
        nullable=False,
        index=True,
    )
    project_id = Column(
        String(36),
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )
    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    deleted_at = Column(UtcDateTime, nullable=True, index=True)
    # Doc 26: users.id flipped to UUID String(36).
    deleted_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        Index("idx_task_deps_source_live", "source_task_id", "deleted_at"),
        Index("idx_task_deps_target_live", "target_task_id", "deleted_at"),
        Index("idx_task_deps_project_live", "project_id", "deleted_at"),
        Index(
            "uq_task_deps_pair_live",
            "source_task_id", "target_task_id",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        state = "deleted" if self.deleted_at else "live"
        return (
            f"<TaskDependencyModel(source='{self.source_task_id}', "
            f"target='{self.target_task_id}', {state})>"
        )
