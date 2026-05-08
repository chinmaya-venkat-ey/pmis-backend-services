"""Milestone-to-milestone dependency association.

Mirrors the activity/task/subtask dependency tables. Soft-delete via
``deleted_at``; one live edge per (source, target) pair via partial
unique index.

Service-layer rules: same project, no self-edge, acyclic over live edges.
Cross-milestone within the same project is the whole point — these edges
exist only between distinct milestones of the same project.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, text

from ..utc_datetime import UtcDateTime
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class MilestoneDependencyModel(Base):
    __tablename__ = "milestone_dependencies"

    id = Column(
        String(36),
        primary_key=True,
        index=True,
        default=lambda: str(uuid4()),
    )
    source_milestone_id = Column(
        String(36),
        ForeignKey("milestones.id"),
        nullable=False,
        index=True,
    )
    target_milestone_id = Column(
        String(36),
        ForeignKey("milestones.id"),
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
        Index("idx_milestone_deps_source_live", "source_milestone_id", "deleted_at"),
        Index("idx_milestone_deps_target_live", "target_milestone_id", "deleted_at"),
        Index("idx_milestone_deps_project_live", "project_id", "deleted_at"),
        Index(
            "uq_milestone_deps_pair_live",
            "source_milestone_id", "target_milestone_id",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        state = "deleted" if self.deleted_at else "live"
        return (
            f"<MilestoneDependencyModel(source='{self.source_milestone_id}', "
            f"target='{self.target_milestone_id}', {state})>"
        )
