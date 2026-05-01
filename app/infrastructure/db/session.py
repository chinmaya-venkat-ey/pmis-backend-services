"""Database session management for pmis-project-service.

- One engine, one SessionLocal factory, one Base.
- init_db() runs ``alembic upgrade head`` as a subprocess on boot —
  idempotent. Same pattern as user-service.
- No in-process create_all() in the production path. Alembic is the
  single source of truth for production schema. Tests use create_all()
  via the conftest fixture against an in-memory SQLite engine.
- This service does NOT seed users (user-service is the canonical
  owner of the users table).
"""
from typing import Generator
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from ...core.config import settings


engine = create_engine(settings.DATABASE_URL, echo=settings.DEBUG)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Declarative base for every model in this service."""
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a DB session, closes on request end."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Run Alembic migrations on boot.

    Idempotent — safe to call on every boot. Runs ``alembic upgrade head``
    as a subprocess, the same pattern user-service uses. Migrations are
    written with ``CREATE TABLE IF NOT EXISTS`` semantics so running
    against the shared (already-populated) Postgres is a no-op while
    running against a fresh DB creates everything this service owns.
    """
    import subprocess
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=120,
            env={**__import__("os").environ},
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("alembic upgrade head timed out after 120s") from e

    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade head failed (exit {result.returncode}):\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}"
        )
    logging.info("alembic upgrade head completed successfully")
