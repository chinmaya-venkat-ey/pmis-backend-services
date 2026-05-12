"""Read-only mirror of the monolith's ``projects`` table.

Declared here so the daily-digest cron can join projects to milestones
+ activities + user_role_assignments without an HTTP hop. Notification-
service is on the shared ``pmis_db`` (monolith owns the schema); this
file declares only the columns the cron queries against. ``Base.
metadata.create_all`` builds the table for in-memory SQLite test DBs.
"""
from sqlalchemy import Column, DateTime, String

from ..session import Base


class ProjectModel(Base):
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, index=True)
    project_code = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    status = Column(String(50), nullable=False, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
