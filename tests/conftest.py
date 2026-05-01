"""Shared test fixtures for pmis-user-service.

Mirrors the monolith's conftest.py so tests look the same across repos.
Uses in-memory SQLite per test — fast, isolated, no external Postgres
dependency. Real Postgres behaviour is covered in the monolith's own
test suite and in E2E smoke runs.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.main as main_module
from app.core.security import create_access_token, hash_password
from app.infrastructure.db import session as db_session_module
from app.infrastructure.db.models import (  # noqa: F401 — register on Base
    ProjectMemberModel,
    ProjectModel,
    RevokedTokenModel,
    RoleModel,
    UserModel,
    VendorModel,
)
from app.infrastructure.db.session import Base, get_db
from app.main import app


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_engine():
    """Fresh in-memory SQLite engine per test.

    `cache=shared` + `uri=true` lets all connections in the same process
    see the same in-memory database (required for TestClient → lifespan
    → dependency-override flow).
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
    # Tables were already created in the db_engine fixture — skip
    # init_db (which would run alembic against Postgres).
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
# Seed-data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def admin_user(db_session: Session):
    user = UserModel(
        login="admin",
        email="admin@example.com",
        hashed_password=hash_password("admin123"),
        first_name="Admin",
        last_name="User",
        admin=True,
        status="active",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def member_user(db_session: Session):
    user = UserModel(
        login="member",
        email="member@example.com",
        hashed_password=hash_password("member123"),
        first_name="Member",
        last_name="User",
        admin=False,
        status="active",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def vendor_row(db_session: Session):
    """A live (non-deleted) vendor for create-user / update-user tests."""
    from uuid import uuid4
    v = VendorModel(
        id=str(uuid4()),
        name=f"Vendor-{uuid4().hex[:6]}",
        active=True,
    )
    db_session.add(v)
    db_session.commit()
    db_session.refresh(v)
    return v


@pytest.fixture(scope="function")
def project_row(db_session: Session):
    """A live (non-deleted) project for create-user tests."""
    from uuid import uuid4
    p = ProjectModel(
        id=str(uuid4()),
        project_code=f"UIDAI-PR{uuid4().hex[:14].upper()}",
        name=f"Proj-{uuid4().hex[:6]}",
        active=True,
        public=False,
        status="new",
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


@pytest.fixture(scope="function")
def admin_token(admin_user):
    return create_access_token({
        "sub": admin_user.login,
        "user_id": admin_user.id,
        "email": admin_user.email,
        "role": "admin",
        "is_admin": True,
    })


@pytest.fixture(scope="function")
def member_token(member_user):
    return create_access_token({
        "sub": member_user.login,
        "user_id": member_user.id,
        "email": member_user.email,
        "role": "member",
        "is_admin": False,
    })


@pytest.fixture(scope="function")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="function")
def member_headers(member_token):
    return {"Authorization": f"Bearer {member_token}"}
