"""Subtask-to-subtask dependency association (soft-delete).

See ``activity_dependency.py`` for the schema rationale. Same pattern,
one level deeper. Hierarchy rule: source.task must already depend on
target.task (via ``task_dependencies``), unless they share the same task.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, text

from ..utc_datetime import UtcDateTime
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class SubtaskDependencyModel(Base):
    __tablename__ = "subtask_dependencies"

    id = Column(
        String(36),
        primary_key=True,
        index=True,
        default=lambda: str(uuid4()),
    )
    source_subtask_id = Column(
        String(36),
        ForeignKey("subtasks.id"),
        nullable=False,
        index=True,
    )
    target_subtask_id = Column(
        String(36),
        ForeignKey("subtasks.id"),
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
        Index("idx_subtask_deps_source_live", "source_subtask_id", "deleted_at"),
        Index("idx_subtask_deps_target_live", "target_subtask_id", "deleted_at"),
        Index("idx_subtask_deps_project_live", "project_id", "deleted_at"),
        Index(
            "uq_subtask_deps_pair_live",
            "source_subtask_id", "target_subtask_id",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        state = "deleted" if self.deleted_at else "live"
        return (
            f"<SubtaskDependencyModel(source='{self.source_subtask_id}', "
            f"target='{self.target_subtask_id}', {state})>"
        )
