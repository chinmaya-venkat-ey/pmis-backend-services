"""Database session management for pmis-user-service.

- One engine, one SessionLocal factory, one Base.
- init_db() runs alembic (gated by MIGRATIONS_AUTORUN) and seeds RBAC,
  bootstrap admin, and notification templates. Idempotent.
- No in-process create_all — Alembic is the single source of truth in
  shared-DB mode.

Doc 37 part 2 brought init_db to monolith parity:
  - Honours MIGRATIONS_AUTORUN / MIGRATIONS_REQUIRED / DATABASE_URL_MIGRATIONS
    flags so deploys where the monolith owns migrations can opt out.
  - Seeds the doc-21B RBAC catalog (4 built-in roles: admin, member,
    viewer, vendor + their permission bundles + the canonical
    permission registry).
  - Seeds the 6 doc-36 notification templates (3 kinds × 2 channels).
  - Bootstrap admin gets two_factor_enabled=False forced on every
    boot so the always-reachable break-glass account never gets
    locked out.
"""
from datetime import datetime, timezone
from typing import Generator
import logging
import os

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


def _run_alembic_upgrade() -> None:
    """Run ``alembic upgrade head`` against DATABASE_URL_MIGRATIONS (if
    set) or DATABASE_URL otherwise. Honours MIGRATIONS_REQUIRED — when
    False, logs the failure and continues."""
    if not settings.MIGRATIONS_AUTORUN:
        logging.info("MIGRATIONS_AUTORUN=false — skipping alembic upgrade.")
        return

    import subprocess
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[3]
    env = {**os.environ}
    if settings.DATABASE_URL_MIGRATIONS:
        env["DATABASE_URL"] = settings.DATABASE_URL_MIGRATIONS
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        if settings.MIGRATIONS_REQUIRED:
            raise RuntimeError("alembic upgrade head timed out after 120s") from e
        logging.error("alembic upgrade timed out (continuing — MIGRATIONS_REQUIRED=false)")
        return

    if result.returncode != 0:
        msg = (
            f"alembic upgrade head failed (exit {result.returncode}):\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}"
        )
        if settings.MIGRATIONS_REQUIRED:
            raise RuntimeError(msg)
        logging.error("%s\n(continuing — MIGRATIONS_REQUIRED=false)", msg)
        return
    logging.info("alembic upgrade head completed successfully")


def init_db() -> None:
    """Run alembic, seed RBAC catalog, bootstrap admin, and notification
    templates. Every step is idempotent — safe to call on every boot."""

    # ---- 1. Migrations (optional) -------------------------------------
    _run_alembic_upgrade()

    # ---- 2. RBAC seed (doc 21B + doc 33 change 1) ---------------------
    from .repositories.rbac_repository import RbacRepository
    db = SessionLocal()
    try:
        RbacRepository(db).sync_builtin_permissions()
        db.commit()
        logging.info("RBAC catalog synced (permissions + 4 built-in roles).")
    except Exception as e:
        db.rollback()
        logging.error("RBAC seed failed: %s", e)
    finally:
        db.close()

    # ---- 3. Bootstrap admin -------------------------------------------
    from ...core.security import hash_password
    from .models.user import UserModel
    from .models.role import RoleModel
    from .models.user_role import UserRoleModel

    db = SessionLocal()
    try:
        admin_user = (
            db.query(UserModel)
            .filter(UserModel.login == settings.BOOTSTRAP_ADMIN_LOGIN)
            .first()
        )
        if admin_user is None:
            admin_user = UserModel(
                login=settings.BOOTSTRAP_ADMIN_LOGIN,
                email=settings.BOOTSTRAP_ADMIN_EMAIL,
                hashed_password=hash_password(settings.BOOTSTRAP_ADMIN_PASSWORD),
                first_name="Administrator",
                last_name="System",
                status="active",
                # Always two_factor_enabled=False on bootstrap admin —
                # break-glass account; never locked out by an
                # unconfigured notification channel.
                two_factor_enabled=False,
            )
            db.add(admin_user)
            db.flush()
            logging.info("Bootstrap admin '%s' created.", settings.BOOTSTRAP_ADMIN_LOGIN)
        else:
            # Force the break-glass invariant on every boot — even if
            # the admin row already exists, reset the flag.
            if admin_user.two_factor_enabled:
                admin_user.two_factor_enabled = False
                logging.info(
                    "Forcing bootstrap admin two_factor_enabled=False (break-glass guarantee).",
                )

        # Ensure the admin user has the 'admin' role.
        admin_role = (
            db.query(RoleModel)
            .filter(RoleModel.name == "admin")
            .first()
        )
        if admin_role is not None:
            assigned = (
                db.query(UserRoleModel)
                .filter(
                    UserRoleModel.user_id == admin_user.id,
                    UserRoleModel.role_id == admin_role.id,
                )
                .first()
            )
            if assigned is None:
                db.add(UserRoleModel(
                    user_id=admin_user.id,
                    role_id=admin_role.id,
                ))

        db.commit()
    except Exception as e:
        db.rollback()
        logging.error("Bootstrap admin seed failed: %s", e)
    finally:
        db.close()

    # ---- 4. Notification templates (doc 36) ---------------------------
    db = SessionLocal()
    try:
        from .models.notification_template import NotificationTemplateModel

        _tmpl_seed = (
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
                "description": "Sent on every successful 2FA login attempt (email channel).",
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
                "description": "Sent on every successful 2FA login attempt (SMS channel).",
            },
            {
                "template_kind": "password_reset_link",
                "channel": "email",
                "subject": "PMIS password reset",
                "body": (
                    "<p>You (or someone) requested a password reset for your "
                    "PMIS account. Click the link below to set a new "
                    "password:</p>"
                    "<p><a href='{reset_url}'>Reset your PMIS password</a></p>"
                    "<p>If the link doesn't work, paste this URL into your "
                    "browser:</p>"
                    "<p style='font-family:monospace;word-break:break-all'>{reset_url}</p>"
                    "<p>Or use this single-use token directly:</p>"
                    "<p style='font-family:monospace;word-break:break-all'>{token}</p>"
                    "<p>The link expires in {ttl_minutes} minutes. If you "
                    "didn't request a reset, you can ignore this email.</p>"
                ),
                "is_html": True,
                "description": "Sent on POST /users/forgot-password with channel=email.",
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
                    "PMIS password reset code: {code}. Expires in {ttl_minutes} "
                    "min. Don't share this code."
                ),
                "is_html": False,
                "description": "Sent on POST /users/forgot-password with channel=sms.",
            },
        )
        for spec in _tmpl_seed:
            existing = (
                db.query(NotificationTemplateModel)
                .filter(NotificationTemplateModel.template_kind == spec["template_kind"])
                .filter(NotificationTemplateModel.channel == spec["channel"])
                .first()
            )
            if existing is None:
                db.add(NotificationTemplateModel(
                    template_kind=spec["template_kind"],
                    channel=spec["channel"],
                    subject=spec["subject"],
                    body=spec["body"],
                    is_html=spec["is_html"],
                    is_builtin=True,
                    active=True,
                    description=spec["description"],
                ))
        db.commit()
        logging.info("Notification template catalog seeded.")
    except Exception as e:
        db.rollback()
        logging.error("Notification template seed failed: %s", e)
    finally:
        db.close()
