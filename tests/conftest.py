"""Shared test fixtures for pmis-project-service.

Uses in-memory SQLite per test — fast, isolated, no external Postgres
dependency. Auth fixtures mint JWTs locally via
``core.security.create_access_token`` so authenticated endpoints can
be exercised without spinning up user-service.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main as main_module
from app.core.security import create_access_token
from app.infrastructure.db import session as db_session_module
# Importing models registers every model on Base.metadata.
from app.infrastructure.db import models  # noqa: F401
from app.infrastructure.db.session import Base, get_db
from app.main import app


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_engine():
    """Fresh in-memory SQLite engine per test.

    `cache=shared` + `uri=true` lets all connections in the same process
    see the same in-memory database (required for TestClient ->
    lifespan -> dependency-override flow).

    Doc 49: also seeds the three built-in divisions (tmd1/tmd2/others)
    into the ``divisions`` master table, mirroring what init_db does in
    production — the new doc-49 catalog check on Activity.ownerDivision
    needs at least one matching row.
    """
    engine = create_engine(
        "sqlite:///file:test.db?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)

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
                    email="tests@example.com", phone_number="+910000000000",
                ))
        seed_session.commit()
    finally:
        seed_session.close()

    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    """ORM session bound to the in-memory engine."""
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=db_engine,
    )
    session = TestingSessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(db_engine, db_session):
    """FastAPI TestClient with dependency + module-level overrides so
    every session opened during a request hits the same in-memory DB.
    """
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=db_engine,
    )

    def _override_get_db():
        s = TestingSessionLocal()
        try:
            yield s
        finally:
            s.close()

    # Swap module-level engine/SessionLocal/init_db so code opening its
    # own session (e.g. the auth middleware's blacklist lookup) also
    # hits the in-memory DB, not prod Postgres.
    original_engine = db_session_module.engine
    original_session_local = db_session_module.SessionLocal
    original_init_db = db_session_module.init_db

    db_session_module.engine = db_engine
    db_session_module.SessionLocal = TestingSessionLocal
    # Tables were already created — skip init_db (would try alembic).
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
# Auth fixtures
# ---------------------------------------------------------------------------

# Doc 26: ``users.id`` is a UUID String(36). The auth middleware's doc-27
# hotfix rejects non-UUID user_id claims as anonymous (matches user-service's
# mint shape).
#
# Doc 21B: tokens carry NO ``role`` or ``is_admin`` claim — the auth middleware
# queries the DB on each authenticated request. Test fixtures must seed
# the RBAC tables (built-in permissions + admin/member/viewer roles) AND
# assign the test user to a role so the lookup succeeds.

_ADMIN_UUID = "00000000-0000-0000-0000-000000000001"
_MEMBER_UUID = "00000000-0000-0000-0000-000000000002"


def _ensure_rbac_seed(db):
    """Idempotent test-side bootstrap of the RBAC tables (doc 21 part B).

    Mirrors what user-service's init_db does at startup: upserts the
    built-in permissions and the seeded admin/member/viewer roles.
    """
    from app.infrastructure.db.repositories.rbac_repository import RbacRepository

    RbacRepository(db).sync_builtin_permissions()
    db.commit()


def _assign_role(db, user_id: str, role_name: str):
    from app.infrastructure.db.models.role import RoleModel
    from app.infrastructure.db.models.user_role import UserRoleModel

    role = db.query(RoleModel).filter(RoleModel.name == role_name).first()
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


def _seed_user_with_role(db, user_id: str, login: str, email: str, role_name: str):
    """Create a minimal user row and assign it the named role.

    project-service treats UserModel as a read-only reference (user-service
    owns writes), but we still need a row in the shared in-memory DB for
    FK validity + the RBAC join in the auth middleware.
    """
    from app.infrastructure.db.models.user import UserModel

    _ensure_rbac_seed(db)

    existing = db.query(UserModel).filter(UserModel.id == user_id).first()
    if existing is None:
        user = UserModel(
            id=user_id,
            login=login,
            email=email,
            hashed_password="not-used-in-project-service-tests",
            status="active",
        )
        db.add(user)
        db.commit()

    _assign_role(db, user_id, role_name)


@pytest.fixture(scope="function")
def admin_token(db_session):
    _seed_user_with_role(
        db_session, _ADMIN_UUID, "admin", "admin@example.com", "admin",
    )
    return create_access_token({
        "sub": "admin",
        "user_id": _ADMIN_UUID,
        "email": "admin@example.com",
    })


@pytest.fixture(scope="function")
def member_token(db_session):
    _seed_user_with_role(
        db_session, _MEMBER_UUID, "member", "member@example.com", "member",
    )
    return create_access_token({
        "sub": "member",
        "user_id": _MEMBER_UUID,
        "email": "member@example.com",
    })


@pytest.fixture(scope="function")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="function")
def member_headers(member_token):
    return {"Authorization": f"Bearer {member_token}"}
