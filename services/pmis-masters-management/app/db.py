"""pmis-masters-management — SQLAlchemy engine + session + Base.

Per PLAN.md §2.5:
  - Base.metadata = tables OWNED by this service (schema `masters`):
    divisions, vendors, resource_types, project_categories, activity_types,
    activity_statuses, milestone_statuses, project_status_transitions,
    priorities, notification_templates (Q3 moved here).
  - MirrorBase.metadata = read-only mirrors of users.* and project.* for
    cross-schema reads (e.g. `/masters/vendors/{id}/projects/list`).
"""
from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=Session,
)


class Base(DeclarativeBase):
    """Metadata for tables owned by pmis-masters-management (schema `masters`)."""
    pass


class MirrorBase(DeclarativeBase):
    """READ-ONLY mirror declarations for tables owned by user-svc, project-svc.

    NOT included in alembic autogenerate.
    """
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
