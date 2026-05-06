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
# hotfix rejects non-UUID user_id claims as anonymous (matches
# pmis-user-service's mint shape). Use deterministic UUIDs in tests so
# fixtures referencing ``admin_token``'s identity stay stable.
_ADMIN_UUID = "00000000-0000-0000-0000-000000000001"
_MEMBER_UUID = "00000000-0000-0000-0000-000000000002"


@pytest.fixture(scope="function")
def admin_token():
    return create_access_token({
        "sub": "admin",
        "user_id": _ADMIN_UUID,
        "email": "admin@example.com",
        "role": "admin",
        "is_admin": True,
    })


@pytest.fixture(scope="function")
def member_token():
    return create_access_token({
        "sub": "member",
        "user_id": _MEMBER_UUID,
        "email": "member@example.com",
        "role": "member",
        "is_admin": False,
    })


@pytest.fixture(scope="function")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="function")
def member_headers(member_token):
    return {"Authorization": f"Bearer {member_token}"}
