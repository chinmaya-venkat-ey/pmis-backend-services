"""Activity SQLAlchemy model."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Text, Index, CheckConstraint, text,
)
from ..utc_datetime import UtcDateTime
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ActivityModel(Base):
    """Activities under a milestone. Has type + optional actual dates."""
    __tablename__ = "activities"

    id = Column(
        String(36), primary_key=True, index=True,
        default=lambda: str(uuid4()),
    )
    # Denormalized project_id for cheap "everything under project X" queries.
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    milestone_id = Column(String(36), ForeignKey("milestones.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)

    type = Column(String(20), nullable=False)

    start_date = Column(UtcDateTime, nullable=False)
    end_date = Column(UtcDateTime, nullable=False)
    actual_start_date = Column(UtcDateTime, nullable=True)
    actual_end_date = Column(UtcDateTime, nullable=True)

    position = Column(Integer, nullable=False, default=0)

    # Resource-type flavor.
    resource_mode = Column(String(10), nullable=True)
    resource_count = Column(Integer, nullable=True)

    # Standard-activity-only fields. For any non-'standard' activity these
    # MUST remain NULL; the schema / service layer enforces this.
    # ``status`` is one of ACTIVITY_STATUS_CHOICES (e.g. 'not_completed' |
    # 'completed'), extensible. The status-completion gate uses this column:
    # an activity may only flip to 'completed' once every activity it
    # ``dependsOn`` (per the activity_dependencies table) is also 'completed'.
    status = Column(String(32), nullable=True, index=True)

    # Doc 33: ``cloned_from_id`` was removed along with the versioning
    # feature. Activities live directly under their parent milestone.

    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    updated_at = Column(UtcDateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    # Doc 26: users.id flipped to UUID String(36).
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    deleted_at = Column(UtcDateTime, nullable=True, index=True)

    __table_args__ = (
        CheckConstraint(
            "type IN ('standard', 'resource', 'transactional')",
            name="ck_activities_type",
        ),
        CheckConstraint(
            "resource_mode IS NULL OR resource_mode IN ('count', 'details')",
            name="ck_activities_resource_mode",
        ),
        CheckConstraint(
            "resource_count IS NULL OR resource_count >= 1",
            name="ck_activities_resource_count_positive",
        ),
        Index("idx_activities_milestone_live", "milestone_id", "deleted_at"),
        Index("idx_activities_milestone_position", "milestone_id", "position"),
        Index("idx_activities_project_live", "project_id", "deleted_at"),
        # One LIVE activity per (milestone_id, position) — same rationale
        # as the milestones uniqueness index. Source of truth for the rank
        # used by display labels (A{m}.{a}).
        Index(
            "uq_activities_milestone_position_live",
            "milestone_id", "position",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<ActivityModel(id='{self.id}', milestone_id='{self.milestone_id}', name='{self.name}', type='{self.type}')>"
