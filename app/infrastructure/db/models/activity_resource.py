"""Activity Resource SQLAlchemy model (1-to-1 with activities)."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Numeric, Index, text,
)
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ActivityResourceModel(Base):
    __tablename__ = "activity_resources"

    id = Column(
        String(36), primary_key=True, index=True,
        default=lambda: str(uuid4()),
    )
    activity_id = Column(String(36), ForeignKey("activities.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)

    resource_name = Column(String(255), nullable=False)

    onboard_date = Column(DateTime, nullable=True)
    actual_onboard_date = Column(DateTime, nullable=True)
    offboard_date = Column(DateTime, nullable=True)
    actual_offboard_date = Column(DateTime, nullable=True)

    position = Column(String(255), nullable=True)
    designation = Column(String(255), nullable=True)
    job_role = Column(String(255), nullable=True)
    qualification = Column(String(255), nullable=True)
    experience_years = Column(Numeric(4, 1), nullable=True)

    # Resource classification — references resource_types.id (a UUID).
    # NULL allowed for legacy rows; required on new inserts via schema validator.
    type_of_resource_id = Column(
        String(36),
        ForeignKey("resource_types.id"),
        nullable=True,
        index=True,
    )
    # Division: one of DIVISION_CHOICES ('tmd1', 'tmd2', 'others'). Stored
    # lowercase. When ``division == 'others'`` a free-text label is required
    # and stored in ``division_other``; NULL otherwise.
    division = Column(String(32), nullable=True)
    division_other = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index(
            "uq_activity_resources_activity_live",
            "activity_id",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_activity_resources_project_live", "project_id", "deleted_at"),
    )

    def __repr__(self) -> str:
        return f"<ActivityResourceModel(id='{self.id}', activity_id='{self.activity_id}')>"
