"""Subtask Resource SQLAlchemy model (1-to-1 with subtasks)."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Numeric, Index, text,
)
from ..utc_datetime import UtcDateTime
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class SubtaskResourceModel(Base):
    __tablename__ = "subtask_resources"

    id = Column(
        String(36), primary_key=True, index=True,
        default=lambda: str(uuid4()),
    )
    subtask_id = Column(String(36), ForeignKey("subtasks.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)

    resource_name = Column(String(255), nullable=False)
    onboard_date = Column(UtcDateTime, nullable=True)
    actual_onboard_date = Column(UtcDateTime, nullable=True)
    offboard_date = Column(UtcDateTime, nullable=True)
    actual_offboard_date = Column(UtcDateTime, nullable=True)
    position = Column(String(255), nullable=True)
    designation = Column(String(255), nullable=True)
    job_role = Column(String(255), nullable=True)
    qualification = Column(String(255), nullable=True)
    experience_years = Column(Numeric(4, 1), nullable=True)

    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    updated_at = Column(UtcDateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    deleted_at = Column(UtcDateTime, nullable=True, index=True)

    __table_args__ = (
        Index(
            "uq_subtask_resources_subtask_live",
            "subtask_id",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_subtask_resources_project_live", "project_id", "deleted_at"),
    )

    def __repr__(self) -> str:
        return f"<SubtaskResourceModel(id='{self.id}', subtask_id='{self.subtask_id}')>"
