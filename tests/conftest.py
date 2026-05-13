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
    PermissionModel,
    RolePermissionModel,
    UserRoleModel,
    UserPermissionModel,
    NotificationLogModel,
    OtpCodeModel,
    PasswordResetTokenModel,
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

    Doc 49: also seeds the three built-in divisions (tmd1/tmd2/others)
    into the read-only ``divisions`` table. In production these rows
    are seeded by the monolith's ``init_db``; for user-mgmt tests we
    seed them here so the catalog-membership check on User.division
    finds the built-ins.
    """
    engine = create_engine(
        "sqlite:///file:test.db?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)

    # Seed built-in divisions.
    from app.infrastructure.db.models.division import DivisionModel
    seed_session = sessionmaker(bind=engine)()
    try:
        for code, label, requires_other in (
            ("tmd1", "TMD1", False),
            ("tmd2", "TMD2", False),
            ("others", "Others", True),
        ):
            if seed_session.query(DivisionModel).filter_by(code=code).first() is None:
                seed_session.add(DivisionModel(
                    code=code, label=label,
                    is_builtin=True, requires_other=requires_other, active=True,
                ))
        seed_session.commit()
    finally:
        seed_session.close()

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


# Doc 43 round 4: legacy 'member' role retired. The ``member_user``
# fixture no longer attaches to a seeded role bundle — instead we
# grant a small baseline of direct user_permissions so the tests
# that depended on a non-admin user with ``projects:create`` and
# task perms keep passing without resurrecting the legacy seed.
_TEST_MEMBER_DIRECT_PERMISSIONS: tuple[str, ...] = (
    "projects:read", "projects:create", "projects:update",
    "milestones:read", "activities:read",
    "tasks:read", "tasks:create", "tasks:update",
    "subtasks:read", "comments:read", "attachments:download",
)


def _grant_direct_permissions(db: Session, user_id: str, codes: tuple[str, ...]):
    from app.infrastructure.db.models.user_permission import UserPermissionModel
    for code in codes:
        existing = (
            db.query(UserPermissionModel)
            .filter(
                UserPermissionModel.user_id == user_id,
                UserPermissionModel.permission_code == code,
            )
            .first()
        )
        if existing is None:
            db.add(UserPermissionModel(user_id=user_id, permission_code=code))
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
    """Create a non-admin user with a baseline of project / task / comment
    permissions granted directly (post-doc-43-round-4 the 'member' role
    bundle is gone — direct grants reproduce the same surface for tests
    without resurrecting the legacy seed)."""
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
    _grant_direct_permissions(
        db_session, user.id, _TEST_MEMBER_DIRECT_PERMISSIONS,
    )
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
def second_admin_user(db_session):
    """A second admin so peer / lockout tests don't have to bootstrap
    one inline. Active, not deleted, holds the seeded ``admin`` role."""
    from app.core.security import hash_password as _hp

    u = UserModel(
        login="admin2",
        email="admin2@example.com",
        hashed_password=_hp("admin123"),
        first_name="Admin",
        last_name="Two",
        status="active",
        two_factor_enabled=False,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    admin_role = (
        db_session.query(RoleModel).filter(RoleModel.name == "admin").first()
    )
    if admin_role is not None:
        db_session.add(UserRoleModel(user_id=u.id, role_id=admin_role.id))
        db_session.commit()
    return u


@pytest.fixture(scope="function")
def second_admin_headers(second_admin_user):
    return {"Authorization": f"Bearer " + create_access_token({
        "sub": second_admin_user.login,
        "user_id": second_admin_user.id,
        "email": second_admin_user.email,
    })}


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
