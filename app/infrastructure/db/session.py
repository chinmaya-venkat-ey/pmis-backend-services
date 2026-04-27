"""Database session management for pmis-user-service.

- One engine, one SessionLocal factory, one Base.
- init_db() runs alembic upgrade head as a subprocess on boot. Idempotent.
- No in-process create_all — Alembic is the single source of truth.
- Bootstrap admin seed runs after migrations. Idempotent.
"""
from datetime import datetime, timezone
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
    """Run Alembic migrations, then seed the bootstrap admin.

    Both steps are idempotent — safe to call on every boot.
    """
    # ---- 1. Migrations -------------------------------------------------
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

    # ---- 2. Bootstrap admin -------------------------------------------
    # Local imports to avoid circular import at module load.
    from ...core.security import hash_password
    from .models.user import UserModel

    db = SessionLocal()
    try:
        admin_exists = (
            db.query(UserModel)
            .filter(UserModel.login == settings.BOOTSTRAP_ADMIN_LOGIN)
            .first()
        )
        if admin_exists is None:
            db.add(UserModel(
                login=settings.BOOTSTRAP_ADMIN_LOGIN,
                email=settings.BOOTSTRAP_ADMIN_EMAIL,
                hashed_password=hash_password(settings.BOOTSTRAP_ADMIN_PASSWORD),
                first_name="Administrator",
                last_name="System",
                admin=True,
                status="active",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ))
            db.commit()
            logging.info("Bootstrap admin '%s' created.", settings.BOOTSTRAP_ADMIN_LOGIN)
        else:
            logging.info(
                "Bootstrap admin '%s' already exists — skipping.",
                settings.BOOTSTRAP_ADMIN_LOGIN,
            )
    finally:
        db.close()
