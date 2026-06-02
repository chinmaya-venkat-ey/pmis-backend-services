"""pytest fixtures for pmis-user-management.

Provides:
  - `app` / `client` — fresh FastAPI app + TestClient per test
  - `fake_db_session` — MagicMock standing in for a SQLAlchemy Session
  - `anonymous_client` — TestClient with no logged-in user (user_id=None)
  - `reader_client` — TestClient logged in as a non-admin holding `users:read`
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.permissions import ALL_PERMISSIONS

# A1 (2026-06-02 audit): after the `_is_admin` route bypass was removed,
# admins now pass gates only if they explicitly hold the code (granted by
# r005). The default test admin fixture must mirror that runtime state.
_ALL_PERMISSIONS_SET = frozenset(ALL_PERMISSIONS)


class _TestAuthMiddleware(BaseHTTPMiddleware):
    """Test-only middleware that hard-codes request.state to a logged-in admin.

    Mirrors masters-svc's test middleware. Switch behavior per test by setting
    `app.state.test_user_id` / `.test_permissions` / `.test_scoped_permissions`
    / `.test_is_admin`.
    """

    async def dispatch(self, request, call_next):
        app_state = request.app.state
        request.state.user_id = getattr(app_state, "test_user_id", "test-admin-id")
        request.state.user_login = "test-admin"
        request.state.user_email = "admin@example.com"
        request.state.token_jti = "test-jti"
        perms = getattr(app_state, "test_permissions", None)
        if perms is None:
            perms = set(_ALL_PERMISSIONS_SET)
        request.state.user_permissions = perms
        scoped = getattr(app_state, "test_scoped_permissions", None)
        if scoped is None:
            scoped = {("global", None): set(_ALL_PERMISSIONS_SET)}
        request.state.scoped_permissions = scoped
        request.state.is_admin = getattr(app_state, "test_is_admin", True)
        request.state.request_id = "test-rid"
        return await call_next(request)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
def app():
    """Fresh FastAPI app per test, with AuthMiddleware swapped for the test
    middleware that defaults to a logged-in admin."""
    from app.main import create_app
    from app.middleware.auth_middleware import AuthMiddleware as RealAuthMiddleware

    app = create_app()

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
    return MagicMock(name="FakeSession")


@pytest.fixture
def anonymous_client(app):
    """No logged-in user — used to verify 401 on protected endpoints and
    that the public allow-list (login, refresh, OTP, forgot-password) still
    works without a token."""
    app.state.test_user_id = None
    app.state.test_is_admin = False
    app.state.test_permissions = set()
    app.state.test_scoped_permissions = {}
    return TestClient(app)


@pytest.fixture
def reader_client(app):
    """Non-admin holding only USERS_READ. Used to confirm granular gates."""
    app.state.test_user_id = "non-admin-test-user"
    app.state.test_is_admin = False
    app.state.test_permissions = {"users:read"}
    app.state.test_scoped_permissions = {}
    return TestClient(app)
