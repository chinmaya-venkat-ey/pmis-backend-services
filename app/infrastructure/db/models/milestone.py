"""Milestone SQLAlchemy model."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Text, Index, text,
)
from ..utc_datetime import UtcDateTime
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class MilestoneModel(Base):
    """Milestones under a project. No type column.

    Tester report (post-Doc 41 follow-up): ``actual_start_date`` and
    ``actual_end_date`` were added so the FE can render them on the
    milestone edit form, matching the existing
    activity / task / subtask pattern.
    """
    __tablename__ = "milestones"

    # UUID primary key.
    id = Column(
        String(36), primary_key=True, index=True,
        default=lambda: str(uuid4()),
    )
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)

    start_date = Column(UtcDateTime, nullable=False)
    end_date = Column(UtcDateTime, nullable=False)
    # Tester report: actual dates added so the FE can render them on
    # the milestone edit form, matching activity / task / subtask.
    # Both nullable — populated when work actually starts / finishes;
    # never required at create or update time.
    actual_start_date = Column(UtcDateTime, nullable=True)
    actual_end_date = Column(UtcDateTime, nullable=True)

    position = Column(Integer, nullable=False, default=0)

    # Configurable status — values in MILESTONE_STATUS_CHOICES
    # (app/domain/milestones/milestone.py). Defaults to 'not_completed'.
    status = Column(String(32), nullable=False, default="not_completed", index=True)

    # Doc 41 follow-up: priority code from the ``priorities`` catalog.
    # Independent per-level — milestone priority is NOT derived from or
    # constrained by activity / task / subtask priorities. Required on
    # the wire on create; existing rows backfilled to ``p3`` (low).
    priority = Column(String(16), nullable=True, index=True)

    # The legacy ``depends`` JSON column was removed in doc 22 (display-label
    # rework). Milestone-to-milestone dependencies now live in the
    # ``milestone_dependencies`` edge table (per doc 21A) and are surfaced
    # through the API as ``dependsOn`` / ``dependsOnDisplay``.

    # Doc 33: ``cloned_from_id`` was removed along with the versioning
    # feature. Milestones live directly under their project.

    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    updated_at = Column(UtcDateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    # Doc 26: users.id flipped to UUID String(36).
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    deleted_at = Column(UtcDateTime, nullable=True, index=True)

    __table_args__ = (
        Index("idx_milestones_project_live", "project_id", "deleted_at"),
        Index("idx_milestones_project_position", "project_id", "position"),
        # One LIVE milestone per (project_id, position). Position is the
        # rank source for display labels (M1, M2, …); duplicates would make
        # label resolution ambiguous. Soft-deleted rows can share positions
        # with a live row (history kept).
        Index(
            "uq_milestones_project_position_live",
            "project_id", "position",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<MilestoneModel(id='{self.id}', project_id='{self.project_id}', name='{self.name}')>"
