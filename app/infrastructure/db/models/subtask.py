"""Subtask SQLAlchemy model.

Parent shape (doc 24):
- ``task_id`` always points at the **root task** the subtree lives under.
- ``parent_subtask_id`` is NULL for top-level subtasks (direct children
  of the task) and points at another subtask's id for nested ones.

XOR semantics: ``parent_subtask_id IS NULL`` ⇔ "child of task";
``parent_subtask_id IS NOT NULL`` ⇔ "child of subtask".

Position uniqueness is enforced per parent via two partial-unique
indexes — one for top-level siblings under a task, one for children of
a given subtask. Together they keep S{m}.{a}.{t}.{s1}[.{s2}…] labels
unambiguous at every depth.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Text, Index, CheckConstraint, text,
)
from ..utc_datetime import UtcDateTime
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class SubtaskModel(Base):
    """Subtasks under a task. Has type + optional actual dates.

    Doc 24: ``parent_subtask_id`` enables nesting. ``task_id`` still
    points at the root task for cheap "all subtasks under task X" reads.
    """
    __tablename__ = "subtasks"

    id = Column(
        String(36), primary_key=True, index=True,
        default=lambda: str(uuid4()),
    )
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False, index=True)
    # Doc 24: nullable FK to another subtask. NULL = top-level under
    # task_id; non-NULL = nested child whose direct parent is another
    # subtask. ``use_alter`` breaks the self-FK cycle on table create.
    parent_subtask_id = Column(
        String(36),
        ForeignKey(
            "subtasks.id",
            name="fk_subtasks_parent_subtask_id",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )

    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    # Doc 38: ``type`` no longer accepted on create — inherited from parent
    # task / activity (both nullable). Column kept for legacy rows.
    type = Column(String(20), nullable=True)

    start_date = Column(UtcDateTime, nullable=False)
    end_date = Column(UtcDateTime, nullable=False)
    actual_start_date = Column(UtcDateTime, nullable=True)
    actual_end_date = Column(UtcDateTime, nullable=True)

    position = Column(Integer, nullable=False, default=0)

    resource_mode = Column(String(10), nullable=True)
    resource_count = Column(Integer, nullable=True)

    # Doc 38: lifecycle status, settable via PATCH only (not on create).
    status = Column(String(32), nullable=True, index=True)

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
            name="ck_subtasks_type",
        ),
        CheckConstraint(
            "resource_mode IS NULL OR resource_mode IN ('count', 'details')",
            name="ck_subtasks_resource_mode",
        ),
        CheckConstraint(
            "resource_count IS NULL OR resource_count >= 1",
            name="ck_subtasks_resource_count_positive",
        ),
        Index("idx_subtasks_task_live", "task_id", "deleted_at"),
        Index("idx_subtasks_task_position", "task_id", "position"),
        Index("idx_subtasks_project_live", "project_id", "deleted_at"),
        # One LIVE TOP-LEVEL subtask per (task_id, position) — anchors
        # the S{m}.{a}.{t}.{s1} segment.
        Index(
            "uq_subtasks_task_position_top_live",
            "task_id", "position",
            unique=True,
            sqlite_where=text(
                "deleted_at IS NULL AND parent_subtask_id IS NULL"
            ),
            postgresql_where=text(
                "deleted_at IS NULL AND parent_subtask_id IS NULL"
            ),
        ),
        # One LIVE child per (parent_subtask_id, position) — anchors the
        # nested segments S{...}.{sN}.
        Index(
            "uq_subtasks_subtask_position_live",
            "parent_subtask_id", "position",
            unique=True,
            sqlite_where=text(
                "deleted_at IS NULL AND parent_subtask_id IS NOT NULL"
            ),
            postgresql_where=text(
                "deleted_at IS NULL AND parent_subtask_id IS NOT NULL"
            ),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SubtaskModel(id='{self.id}', task_id='{self.task_id}', "
            f"parent_subtask_id='{self.parent_subtask_id}', "
            f"name='{self.name}')>"
        )
