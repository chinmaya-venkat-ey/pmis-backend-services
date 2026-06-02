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

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generator
from uuid import UUID

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime) or isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def _json_serializer(value: Any) -> str:
    return json.dumps(value, default=_json_default)


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False,
    json_serializer=_json_serializer,
)


@event.listens_for(engine, "connect")
def _set_session_timezone(dbapi_connection, _connection_record):
    """Pin every connection's session TZ to IST so timestamptz reads/writes
    round-trip in IST. Postgres still stores in UTC under the hood (timestamptz
    is offset-normalized), but reads come back as ``+05:30`` and API responses
    serialize as IST without per-schema conversion."""
    cur = dbapi_connection.cursor()
    try:
        cur.execute("SET TIME ZONE 'Asia/Kolkata'")
    finally:
        cur.close()

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
