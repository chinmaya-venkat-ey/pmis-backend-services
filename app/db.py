"""pmis-notification-management — SQLAlchemy engine + session + Base.

Per PLAN.md §2.5 and Q3 + Q13:
  - Base.metadata is INTENTIONALLY EMPTY (this service owns no tables).
  - MirrorBase.metadata = read-only mirrors of:
      masters.notification_templates  (Q3: moved out of notification)
      users.users, users.role_permissions, users.user_roles, users.permissions,
      users.user_permissions, users.revoked_tokens, users.user_role_assignments
        (for auth middleware and daily-digest cron)
      project.projects, project.project_vendors, project.milestones, project.activities
        (for daily-digest cron)
  - MirrorBase is NOT included in alembic autogenerate.
"""
from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False,
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
    """Metadata for tables owned by pmis-notification-management.

    EMPTY post-refactor (Q3 + Q13): this service is stateless.
    The alembic chain exists for symmetry and version-table bookkeeping only.
    """
    pass


class MirrorBase(DeclarativeBase):
    """READ-ONLY mirror declarations for tables owned by user-svc, masters-svc,
    project-svc. Used by auth middleware and daily-digest cron.

    NOT included in alembic autogenerate.
    """
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
