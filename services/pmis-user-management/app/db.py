"""pmis-user-management — SQLAlchemy engine + session + Base.

Per PLAN.md §2.5:
  - Base.metadata = tables OWNED by this service (schema `users`).
  - MirrorBase.metadata = READ-ONLY mirror declarations of foreign schemas.
    Excluded from alembic autogenerate via include_object filter in env.py.

WARNING: Models declared on Base are MIRRORED in other services' _cross_schema.py.
See app/models/<model>.py for the per-table list of mirror locations.
Q24 CI drift test catches divergence.
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
    """Metadata for tables owned by pmis-user-management (schema `users`).

    Alembic autogenerate uses Base.metadata only.
    """
    pass


class MirrorBase(DeclarativeBase):
    """READ-ONLY mirror declarations for tables owned by OTHER services.

    NOT included in alembic autogenerate (see alembic/env.py:include_object).
    """
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for per-request DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
