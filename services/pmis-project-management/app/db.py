"""pmis-project-management — SQLAlchemy engine + session + Base.

Per PLAN.md §2.5:
  - Base.metadata = tables OWNED by this service (schema `project`).
  - MirrorBase.metadata = READ-ONLY mirror declarations of foreign schemas
    (users.*, masters.*). Excluded from alembic autogenerate.
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
    """Metadata for tables owned by pmis-project-management (schema `project`)."""
    pass


class MirrorBase(DeclarativeBase):
    """READ-ONLY mirror declarations for tables owned by user-svc, masters-svc.

    NOT included in alembic autogenerate.
    """
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
