"""pytest fixtures for pmis-masters-management.

Provides:
  - `app` / `client` — fresh FastAPI app + TestClient per test
  - `fake_db_session` — MagicMock standing in for a SQLAlchemy Session
  - `mock_admin_request_state` — helper to inject request.state.user_id +
    user_permissions + is_admin via a test-only middleware override
"""
from __future__ import annotations

from typing import Set
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware


class _TestAuthMiddleware(BaseHTTPMiddleware):
    """Test-only middleware that hard-codes request.state to a logged-in admin.

    Replaces the real AuthMiddleware in tests so we don't need to mint JWTs
    and run cross-schema RBAC reads. Switch behavior per test by setting
    `app.state.test_user_id` / `.test_permissions` / `.test_is_admin`.
    """

    async def dispatch(self, request, call_next):
        app_state = request.app.state
        request.state.user_id = getattr(app_state, "test_user_id", "test-admin-id")
        request.state.user_login = "test-admin"
        request.state.user_email = "admin@example.com"
        request.state.token_jti = "test-jti"
        request.state.user_permissions = getattr(
            app_state, "test_permissions", set()
        )
        request.state.is_admin = getattr(app_state, "test_is_admin", True)
        request.state.request_id = "test-rid"
        return await call_next(request)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
def app():
    """Fresh FastAPI app per test. Replaces the real AuthMiddleware with a
    test-only one that injects a logged-in admin by default."""
    from app.main import create_app
    from app.middleware.auth_middleware import AuthMiddleware as RealAuthMiddleware

    app = create_app()

    # Find the user_middleware tuple for AuthMiddleware and replace it.
    new_middleware = []
    for mw in app.user_middleware:
        if mw.cls is RealAuthMiddleware:
            new_middleware.append(
                type(mw)(_TestAuthMiddleware, **getattr(mw, "kwargs", {}))
            )
        else:
            new_middleware.append(mw)
    app.user_middleware = new_middleware
    app.middleware_stack = app.build_middleware_stack()
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def fake_db_session():
    """A MagicMock standing in for a SQLAlchemy Session."""
    return MagicMock(name="FakeSession")


@pytest.fixture
def anonymous_client(app):
    """Client where the auth middleware does NOT set a user_id — used to
    test 401 behavior on RBAC-gated endpoints."""
    app.state.test_user_id = None
    app.state.test_is_admin = False
    app.state.test_permissions = set()
    return TestClient(app)


@pytest.fixture
def reader_client(app):
    """Client logged in as a NON-admin user holding only `divisions:read`.
    Used to verify granular permission gates work."""
    app.state.test_user_id = "non-admin-test-user"
    app.state.test_is_admin = False
    app.state.test_permissions = {"divisions:read"}
    return TestClient(app)
