"""
Shared test fixtures for the PMIS test suite.

Provides:
- In-memory SQLite database per test function
- FastAPI TestClient with dependency override
- Pre-created admin and member users with tokens
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

import app.main as main_module
from app.main import app
from app.infrastructure.db import session as db_session_module
from app.infrastructure.db.session import Base, get_db

# Import every model user-mgmt owns/maps so Base.metadata is complete.
# (User-mgmt doesn't have monolith-only models like meetings or
# work_packages — drop those imports here.)
from app.infrastructure.db.models import (  # noqa: F401
    UserModel,
    RoleModel,
    ProjectModel,
    ProjectMemberModel,
    PermissionModel,
    RolePermissionModel,
    UserRoleModel,
    UserPermissionModel,
    NotificationLogModel,
    OtpCodeModel,
    PasswordResetTokenModel,
    NotificationTemplateModel,
    VendorModel,
    RevokedTokenModel,
)

from app.core.security import hash_password, create_access_token


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_engine():
    """Create a fresh in-memory SQLite engine per test.

    Uses shared cache so all connections see the same database.
    """
    engine = create_engine(
        "sqlite:///file:test.db?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Create a database session bound to the in-memory engine."""
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=db_engine
    )
    session = TestingSessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(db_engine, db_session):
    """
    FastAPI TestClient with the database dependency overridden
    to use the in-memory test session.

    Also patches the module-level SessionLocal and engine so that
    any code creating its own sessions (e.g., init_db) uses the
    test database.
    """
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=db_engine
    )

    def _override_get_db():
        s = TestingSessionLocal()
        try:
            yield s
        finally:
            s.close()

    # Patch module-level objects so init_db and any direct SessionLocal()
    # calls also hit the in-memory database
    original_engine = db_session_module.engine
    original_session_local = db_session_module.SessionLocal
    original_init_db = db_session_module.init_db

    db_session_module.engine = db_engine
    db_session_module.SessionLocal = TestingSessionLocal
    # Prevent init_db from running during test lifespan (tables already created)
    db_session_module.init_db = lambda: None
    main_module.init_db = lambda: None

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    db_session_module.engine = original_engine
    db_session_module.SessionLocal = original_session_local
    db_session_module.init_db = original_init_db
    main_module.init_db = original_init_db


# ---------------------------------------------------------------------------
# Seed data fixtures
# ---------------------------------------------------------------------------

def _ensure_rbac_seed(db: Session):
    """Idempotent test-side bootstrap of the RBAC tables (doc 21 part B).

    Mirrors what ``init_db`` does at app startup: upserts the built-in
    permissions and the seeded admin/member/viewer roles. Called by the
    user fixtures so ``admin_user`` can be assigned the admin role
    without depending on the production startup hook (which the test
    client lifecycle short-circuits)."""
    from app.infrastructure.db.repositories.rbac_repository import (
        RbacRepository,
    )
    RbacRepository(db).sync_builtin_permissions()
    db.commit()


def _ensure_notification_template_seed(db: Session):
    """Idempotent test-side bootstrap of the notification_templates table (doc 36).

    Mirrors the init_db seed loop. The HttpNotificationClient renderer
    now looks up templates from this table; without seeded rows it
    falls back to a generic body, which breaks the renderer-output
    assertions in test_doc33_2fa_and_password_reset.py.
    """
    from app.infrastructure.db.models.notification_template import (
        NotificationTemplateModel,
    )
    seeds = (
        ("otp_login", "email", "Your PMIS login verification code", (
            "<p>Your PMIS login verification code is:</p>"
            "<p style='font-size:22px;font-weight:600;letter-spacing:3px'>{code}</p>"
            "<p>This code expires in {ttl_minutes} minutes. If you didn't try "
            "to log in, you can ignore this email.</p>"
        ), True),
        ("otp_login", "sms", None,
         "PMIS login code: {code}. Expires in {ttl_minutes} min. Don't share this code.",
         False),
        ("password_reset_link", "email", "PMIS password reset", (
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
        ), True),
        ("password_reset_link", "sms", None,
         "PMIS password reset token: {token}. Expires in {ttl_minutes} min.",
         False),
        ("password_reset_otp", "email", "PMIS password reset code", (
            "<p>Your PMIS password reset code is:</p>"
            "<p style='font-size:22px;font-weight:600;letter-spacing:3px'>{code}</p>"
            "<p>This code expires in {ttl_minutes} minutes. If you didn't "
            "request a reset, you can ignore this email.</p>"
        ), True),
        ("password_reset_otp", "sms", None,
         "PMIS password reset code: {code}. Expires in {ttl_minutes} min. Don't share this code.",
         False),
    )
    for kind, channel, subject, body, is_html in seeds:
        existing = (
            db.query(NotificationTemplateModel)
            .filter(NotificationTemplateModel.template_kind == kind)
            .filter(NotificationTemplateModel.channel == channel)
            .first()
        )
        if existing is None:
            db.add(NotificationTemplateModel(
                template_kind=kind,
                channel=channel,
                subject=subject,
                body=body,
                is_html=is_html,
                is_builtin=True,
                active=True,
            ))
    db.commit()


@pytest.fixture(scope="function", autouse=True)
def _seed_notification_templates(db_session):
    """Autouse fixture (doc 36): seed the notification_templates table
    so the HttpNotificationClient renderer can look up active rows.

    Without this, every test that exercises the email/SMS renderer
    falls back to the generic body and renderer-output assertions fail.
    Idempotent — re-runs as a no-op if the rows already exist.
    """
    _ensure_notification_template_seed(db_session)
    yield


def _assign_role(db: Session, user_id: int, role_name: str):
    from app.infrastructure.db.models.role import RoleModel
    from app.infrastructure.db.models.user_role import UserRoleModel
    role = (
        db.query(RoleModel).filter(RoleModel.name == role_name).first()
    )
    if role is None:
        return
    existing = (
        db.query(UserRoleModel)
        .filter(
            UserRoleModel.user_id == user_id,
            UserRoleModel.role_id == role.id,
        )
        .first()
    )
    if existing is None:
        db.add(UserRoleModel(user_id=user_id, role_id=role.id))
        db.commit()


@pytest.fixture(scope="function")
def admin_user(db_session: Session):
    """Create an admin user (assigned to the seeded ``admin`` role).

    Doc 33 change 3: 2FA is mandatory by default at the global config
    layer. Test fixtures pre-set ``two_factor_enabled=False`` so the
    pre-existing single-stage /login flow keeps working — the 2FA
    flow has its own dedicated test file. Tests that exercise 2FA
    explicitly override this flag.
    """
    _ensure_rbac_seed(db_session)
    user = UserModel(
        login="admin",
        email="admin@example.com",
        hashed_password=hash_password("admin123"),
        first_name="Admin",
        last_name="User",
        status="active",
        two_factor_enabled=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    _assign_role(db_session, user.id, "admin")
    return user


@pytest.fixture(scope="function")
def member_user(db_session: Session):
    """Create a non-admin member user (assigned to the seeded ``member`` role)."""
    _ensure_rbac_seed(db_session)
    user = UserModel(
        login="member",
        email="member@example.com",
        hashed_password=hash_password("member123"),
        first_name="Member",
        last_name="User",
        status="active",
        two_factor_enabled=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    _assign_role(db_session, user.id, "member")
    return user


@pytest.fixture(scope="function")
def admin_token(admin_user):
    """JWT access token for the admin user (no role/is_admin claims; doc 21)."""
    return create_access_token({
        "sub": admin_user.login,
        "user_id": admin_user.id,
        "email": admin_user.email,
    })


@pytest.fixture(scope="function")
def member_token(member_user):
    """JWT access token for the member user (no role/is_admin claims; doc 21)."""
    return create_access_token({
        "sub": member_user.login,
        "user_id": member_user.id,
        "email": member_user.email,
    })


@pytest.fixture(scope="function")
def admin_headers(admin_token):
    """Authorization headers for admin user."""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="function")
def member_headers(member_token):
    """Authorization headers for member user."""
    return {"Authorization": f"Bearer {member_token}"}


@pytest.fixture(scope="function")
def sample_project(db_session: Session):
    """Create a sample project in the database.

    `id` is the UUID primary key. `project_code` uses the project_code
    generator so fixtures match production insert semantics.
    """
    from uuid import uuid4
    from app.shared.project_code import generate_project_code
    project = ProjectModel(
        id=str(uuid4()),
        project_code=generate_project_code(db_session),
        name="Test Project",
        description="A test project",
        active=True,
        public=False,
        status="new",
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)
    return project


@pytest.fixture(scope="function")
def builtin_wp_types(db_session: Session):
    """Create built-in work package types."""
    types = []
    for pos, (name, internal) in enumerate(
        [("Task", "task"), ("Bug", "bug"), ("Feature", "feature"),
         ("Milestone", "milestone"), ("Activity", "activity")], start=1
    ):
        wpt = WorkPackageTypeModel(
            name=name,
            internal_name=internal,
            is_builtin=True,
            is_active=True,
            position=pos,
        )
        db_session.add(wpt)
        types.append(wpt)
    db_session.commit()
    for t in types:
        db_session.refresh(t)
    return types
