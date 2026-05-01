"""Milestone SQLAlchemy model."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON, Column, Integer, String, DateTime, ForeignKey, Text, Index,
)
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class MilestoneModel(Base):
    """Milestones under a project. No type, no actual_* dates."""
    __tablename__ = "milestones"

    # UUID primary key.
    id = Column(
        String(36), primary_key=True, index=True,
        default=lambda: str(uuid4()),
    )
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)

    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)

    position = Column(Integer, nullable=False, default=0)

    # Configurable status — values in MILESTONE_STATUS_CHOICES
    # (app/domain/milestones/milestone.py). Defaults to 'not_completed'.
    status = Column(String(32), nullable=False, default="not_completed", index=True)

    # List of milestone ids this milestone depends on. Stored as JSON so we
    # can extend later without a schema migration. Currently carried through
    # the API unchanged — no referential integrity is enforced.
    depends = Column(JSON, nullable=True)

    # Lineage pointer: when a version project is created from a baseline,
    # each cloned milestone records the id of its source baseline milestone
    # here. Baseline milestones have cloned_from_id=NULL. Used by the
    # baseline-to-versions propagation cascade.
    cloned_from_id = Column(
        String(36), ForeignKey("milestones.id"), nullable=True, index=True,
    )

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index("idx_milestones_project_live", "project_id", "deleted_at"),
        Index("idx_milestones_project_position", "project_id", "position"),
    )

    def __repr__(self) -> str:
        return f"<MilestoneModel(id='{self.id}', project_id='{self.project_id}', name='{self.name}')>"
