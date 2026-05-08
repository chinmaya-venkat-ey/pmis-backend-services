"""Activity-to-activity dependency association.

**Soft-delete**: rows are never physically removed. A dep's life cycle is
``deleted_at IS NULL`` (live) → ``deleted_at IS NOT NULL`` (removed). The
partial unique index enforces one-live-edge-per-(source, target) pair while
allowing any number of deleted rows to coexist as history.

Schema
------
- Surrogate UUID PK (``id``) — lets historical rows share the same
  (source, target) with a live row.
- Partial unique index on ``(source_activity_id, target_activity_id)``
  WHERE ``deleted_at IS NULL`` prevents duplicate live edges.
- ``project_id`` denormalized for cheap "all edges in this project" queries.
- ``deleted_at`` + ``deleted_by`` track who removed an edge and when.

Rules (service-layer):
- source != target (no self-edge)
- both sides belong to the same project
- directed graph stays acyclic (DFS check against live edges only)
- target must be live; when a target is soft-deleted, rows pointing at it
  are soft-deleted in turn (silent cascade)

Lives on whichever project owns the source activity. On version creation,
the baseline's LIVE edges are cloned with id-rewrite.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, text

from ..utc_datetime import UtcDateTime
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ActivityDependencyModel(Base):
    __tablename__ = "activity_dependencies"

    id = Column(
        String(36),
        primary_key=True,
        index=True,
        default=lambda: str(uuid4()),
    )
    source_activity_id = Column(
        String(36),
        ForeignKey("activities.id"),
        nullable=False,
        index=True,
    )
    target_activity_id = Column(
        String(36),
        ForeignKey("activities.id"),
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
        Index("idx_activity_deps_source_live", "source_activity_id", "deleted_at"),
        Index("idx_activity_deps_target_live", "target_activity_id", "deleted_at"),
        Index("idx_activity_deps_project_live", "project_id", "deleted_at"),
        # One LIVE edge per (source, target). Soft-deleted rows can coexist
        # for the same pair (history).
        Index(
            "uq_activity_deps_pair_live",
            "source_activity_id", "target_activity_id",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        state = "deleted" if self.deleted_at else "live"
        return (
            f"<ActivityDependencyModel(source='{self.source_activity_id}', "
            f"target='{self.target_activity_id}', {state})>"
        )
