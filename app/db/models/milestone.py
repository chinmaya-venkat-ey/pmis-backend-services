"""Read-only mirror of the monolith's ``milestones`` table."""
from sqlalchemy import Column, DateTime, ForeignKey, String

from ..session import Base


class MilestoneModel(Base):
    __tablename__ = "milestones"

    id = Column(String(36), primary_key=True, index=True)
    project_id = Column(
        String(36), ForeignKey("projects.id"), nullable=False, index=True,
    )
    name = Column(String(255), nullable=False, index=True)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    status = Column(String(32), nullable=False, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
