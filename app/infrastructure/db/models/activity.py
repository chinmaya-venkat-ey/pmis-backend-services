"""Activity SQLAlchemy model."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Text, Index, CheckConstraint,
)
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

    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    actual_start_date = Column(DateTime, nullable=True)
    actual_end_date = Column(DateTime, nullable=True)

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

    # Lineage pointer: when a version project is created from a baseline,
    # each cloned activity records the id of its source baseline activity
    # here. Baseline activities have cloned_from_id=NULL. Used by the
    # baseline-to-versions propagation cascade.
    cloned_from_id = Column(
        String(36), ForeignKey("activities.id"), nullable=True, index=True,
    )

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)

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
    )

    def __repr__(self) -> str:
        return f"<ActivityModel(id='{self.id}', milestone_id='{self.milestone_id}', name='{self.name}', type='{self.type}')>"
