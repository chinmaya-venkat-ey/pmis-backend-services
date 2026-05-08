"""Project SQLAlchemy mapping — owned by project-service / monolith.

Slim mapping, READ-ONLY from this service's perspective. We only ever
need it for:

  1. Validating that ``project_ids`` supplied to user-create reference
     existing non-deleted projects.
  2. Joining ``project_members → projects`` in the user-list / user-get
     paths so each user response embeds its mapped projects.

Only the columns that user-service queries are mapped — full schema
lives in project-service / monolith. Adding columns here is harmless
(they'll just go unused) but unnecessary.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text

from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ProjectModel(Base):
    """Project mapping — schema kept aligned with project-service."""

    __tablename__ = "projects"

    id = Column(
        String(36),
        primary_key=True,
        index=True,
        default=lambda: str(uuid4()),
    )
    project_code = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    public = Column(Boolean, default=False, nullable=False)
    status = Column(String(50), default="new", nullable=False, index=True)
    owner = Column(String(255), nullable=True, index=True)

    # Self-referential parent FK (kept nullable — projects can be roots).
    parent_id = Column(String(36), ForeignKey("projects.id"), nullable=True)

    # Soft-delete: non-NULL deleted_at hides the project from picker
    # validation and from the user's mapped-projects embed.
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        Index("idx_projects_status", "status"),
        Index("idx_projects_deleted_at", "deleted_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectModel(id='{self.id}', "
            f"project_code='{self.project_code}', name='{self.name}', "
            f"status='{self.status}')>"
        )
