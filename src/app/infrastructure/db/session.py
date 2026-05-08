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
  - Bootstrap admin gets two_factor_enabled=True forced on every
    boot — matches the monolith's doc-35 behavior. With the live
    HttpNotificationClient + universal-OTP break-glass available,
    the bootstrap admin can safely run with 2FA on.
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

    # ---- 3. Bootstrap admin removed (doc 42b) -------------------------
    # Pre-doc-42b an `admin` user was auto-created here on every boot.
    # Post-doc-42b the only system-bootstrapped user is `super_admin`
    # (below). `admin` is now created on-demand by the operator via
    # the API — POST /api/v3/users/create as super_admin, then
    # POST /api/v3/users/{id}/role-assignments granting the admin role.
    # This makes admin "just another user" with no special bootstrap
    # treatment.
    from ...core.security import hash_password
    from .models.user import UserModel
    from .models.role import RoleModel
    from .models.user_role import UserRoleModel

    # ---- 4. Bootstrap super_admin (doc 42b) ---------------------------
    # Separate account from the legacy `admin` login. After doc 42b's
    # demotion, `admin` cannot grant super_admin or admin — only
    # super_admin can. Without bootstrapping a super_admin user, no
    # one would ever be able to grant super_admin (chicken-and-egg).
    # Idempotent: skips if the user already exists; only ensures the
    # global super_admin assignment is present.
    from .models.user_role_assignment import UserRoleAssignmentModel

    db = SessionLocal()
    try:
        sa_user = (
            db.query(UserModel)
            .filter(UserModel.login == settings.BOOTSTRAP_SUPERADMIN_LOGIN)
            .first()
        )
        if sa_user is None:
            sa_user = UserModel(
                login=settings.BOOTSTRAP_SUPERADMIN_LOGIN,
                email=settings.BOOTSTRAP_SUPERADMIN_EMAIL,
                hashed_password=hash_password(
                    settings.BOOTSTRAP_SUPERADMIN_PASSWORD
                ),
                first_name="Super",
                last_name="Admin",
                status="active",
                # 2FA on by default; universal-OTP break-glass available.
                two_factor_enabled=True,
            )
            db.add(sa_user)
            db.flush()
            logging.info(
                "Bootstrap super_admin '%s' created.",
                settings.BOOTSTRAP_SUPERADMIN_LOGIN,
            )

        sa_role = (
            db.query(RoleModel)
            .filter(RoleModel.name == "super_admin")
            .first()
        )
        if sa_role is not None:
            existing = (
                db.query(UserRoleAssignmentModel)
                .filter(
                    UserRoleAssignmentModel.user_id == sa_user.id,
                    UserRoleAssignmentModel.role_id == sa_role.id,
                    UserRoleAssignmentModel.organization_id.is_(None),
                    UserRoleAssignmentModel.project_id.is_(None),
                )
                .first()
            )
            if existing is None:
                db.add(UserRoleAssignmentModel(
                    user_id=sa_user.id,
                    role_id=sa_role.id,
                ))
                logging.info(
                    "Granted super_admin role to bootstrap user '%s'.",
                    settings.BOOTSTRAP_SUPERADMIN_LOGIN,
                )

        db.commit()
    except Exception as e:
        db.rollback()
        logging.error("Bootstrap super_admin seed failed: %s", e)
    finally:
        db.close()

