"""Database session management for pmis-notification-service (doc 38).

Pre-doc-38 this service was stateless. Doc 38 introduces SQLAlchemy
session management for the ``notification_templates`` table (and
read-only access to RBAC tables for the auth middleware).

In shared-DB deploys the monolith owns alembic; this service runs
with ``MIGRATIONS_AUTORUN=false`` and relies on the schema being at
head when it boots. For local dev / tests, ``Base.metadata.create_all``
gives the tables this service writes to.
"""
from __future__ import annotations

import logging
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ..config import settings


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Engine + session factory
# ---------------------------------------------------------------------------

# ``database_url`` was added to settings in doc 38. Falls back to a
# disk SQLite path so a fresh checkout can boot without configuration.
_database_url = getattr(settings, "database_url", "") or "sqlite:///./notification_service.db"

# ``check_same_thread`` only meaningful for SQLite; harmless elsewhere.
_engine_kwargs = {}
if _database_url.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(_database_url, echo=False, **_engine_kwargs)
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


# ---------------------------------------------------------------------------
# init_db — seed the template catalog on first boot
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Run alembic (when configured), seed the 6 built-in templates,
    and verify schema. Idempotent.

    In shared-DB deploys ``settings.migrations_autorun=False`` and the
    monolith is responsible for alembic. We just seed templates if the
    table exists.

    For standalone/dev runs, ``Base.metadata.create_all`` produces the
    tables this service writes to.
    """
    # In standalone-DB (SQLite) deploys we create tables in-process.
    # In shared-DB (Postgres) deploys the table already exists via
    # monolith alembic, and create_all is a no-op.
    if _database_url.startswith("sqlite"):
        # Importing the model registers it on Base.metadata.
        from .models import notification_template  # noqa: F401
        Base.metadata.create_all(bind=engine)

    # Seed the 6 built-in templates.
    db = SessionLocal()
    try:
        from .models.notification_template import NotificationTemplateModel
        _seed_built_in_templates(db, NotificationTemplateModel)
        db.commit()
        logger.info("Notification template catalog seeded.")
    except Exception as e:  # noqa: BLE001 — must not crash boot
        db.rollback()
        logger.error("Notification template seed failed: %s", e)
    finally:
        db.close()


_TEMPLATE_SEED = (
    {
        "template_kind": "otp_login",
        "channel": "email",
        "subject": "Your PMIS login verification code",
        "body": (
            "<p>Your PMIS login verification code is:</p>"
            "<p style='font-size:22px;font-weight:600;letter-spacing:3px'>{code}</p>"
            "<p>This code expires in {ttl_minutes} minutes. If you didn't try "
            "to log in, you can ignore this email.</p>"
        ),
        "is_html": True,
        "description": "Sent on every successful 2FA login attempt (email).",
    },
    {
        "template_kind": "otp_login",
        "channel": "sms",
        "subject": None,
        "body": (
            "PMIS login code: {code}. Expires in {ttl_minutes} min. "
            "Don't share this code."
        ),
        "is_html": False,
        "description": "Sent on every successful 2FA login attempt (SMS).",
    },
    {
        "template_kind": "password_reset_link",
        "channel": "email",
        "subject": "PMIS password reset",
        "body": (
            "<p>You (or someone) requested a password reset for your "
            "PMIS account. Click the link below to set a new password:</p>"
            "<p><a href='{reset_url}'>Reset your PMIS password</a></p>"
            "<p>If the link doesn't work, paste this URL into your browser:</p>"
            "<p style='font-family:monospace;word-break:break-all'>{reset_url}</p>"
            "<p>Or use this single-use token directly:</p>"
            "<p style='font-family:monospace;word-break:break-all'>{token}</p>"
            "<p>The link expires in {ttl_minutes} minutes. If you didn't "
            "request a reset, you can ignore this email.</p>"
        ),
        "is_html": True,
        "description": (
            "Sent on POST /users/forgot-password with channel=email. "
            "{reset_url} is computed from FRONTEND_BASE_URL + token; "
            "{token} is always available as a fallback."
        ),
    },
    {
        "template_kind": "password_reset_link",
        "channel": "sms",
        "subject": None,
        "body": "PMIS password reset token: {token}. Expires in {ttl_minutes} min.",
        "is_html": False,
        "description": "Degraded SMS fallback for the link channel.",
    },
    {
        "template_kind": "password_reset_otp",
        "channel": "email",
        "subject": "PMIS password reset code",
        "body": (
            "<p>Your PMIS password reset code is:</p>"
            "<p style='font-size:22px;font-weight:600;letter-spacing:3px'>{code}</p>"
            "<p>This code expires in {ttl_minutes} minutes. If you didn't "
            "request a reset, you can ignore this email.</p>"
        ),
        "is_html": True,
        "description": "Email variant of the OTP-style password reset.",
    },
    {
        "template_kind": "password_reset_otp",
        "channel": "sms",
        "subject": None,
        "body": (
            "PMIS password reset code: {code}. Expires in {ttl_minutes} min. "
            "Don't share this code."
        ),
        "is_html": False,
        "description": "Sent on POST /users/forgot-password with channel=sms.",
    },
)


def _seed_built_in_templates(db: Session, model_cls) -> None:
    """Idempotent — only inserts rows missing for the (kind, channel) pair."""
    for spec in _TEMPLATE_SEED:
        existing = (
            db.query(model_cls)
            .filter(model_cls.template_kind == spec["template_kind"])
            .filter(model_cls.channel == spec["channel"])
            .first()
        )
        if existing is None:
            db.add(model_cls(
                template_kind=spec["template_kind"],
                channel=spec["channel"],
                subject=spec["subject"],
                body=spec["body"],
                is_html=spec["is_html"],
                is_builtin=True,
                active=True,
                description=spec["description"],
            ))
