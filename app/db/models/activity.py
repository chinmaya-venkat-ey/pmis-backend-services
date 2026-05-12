"""Read-only mirror of the monolith's ``activities`` table."""
from sqlalchemy import Column, DateTime, ForeignKey, String

from ..session import Base


class ActivityModel(Base):
    __tablename__ = "activities"

    id = Column(String(36), primary_key=True, index=True)
    # Denormalised project_id on the row — same as in the monolith.
    project_id = Column(
        String(36), ForeignKey("projects.id"), nullable=False, index=True,
    )
    milestone_id = Column(
        String(36), ForeignKey("milestones.id"), nullable=False, index=True,
    )
    name = Column(String(255), nullable=False, index=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    status = Column(String(32), nullable=True, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
