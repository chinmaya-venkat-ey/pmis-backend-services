"""pytest fixtures for pmis-project-management.

Mirrors masters-svc / user-svc fixture conventions.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware


class _TestAuthMiddleware(BaseHTTPMiddleware):
    """Hard-codes request.state to a logged-in admin by default.

    Per-test overrides via:
      app.state.test_user_id           : Optional[str]
      app.state.test_permissions       : Set[str]
      app.state.test_scoped_permissions: Dict[(kind, id), Set[str]]
      app.state.test_is_admin          : bool
      app.state.test_caller_role_name  : Optional[str]
    """

    async def dispatch(self, request, call_next):
        app_state = request.app.state
        request.state.user_id = getattr(app_state, "test_user_id", "test-admin-id")
        request.state.user_login = "test-admin"
        request.state.user_email = "admin@example.com"
        request.state.token_jti = "test-jti"
        request.state.user_permissions = getattr(app_state, "test_permissions", set())
        request.state.scoped_permissions = getattr(app_state, "test_scoped_permissions", {})
        request.state.is_admin = getattr(app_state, "test_is_admin", True)
        request.state.caller_role_name = getattr(app_state, "test_caller_role_name", None)
        request.state.request_id = "test-rid"
        return await call_next(request)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
def app():
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
    app.state.test_user_id = None
    app.state.test_is_admin = False
    app.state.test_permissions = set()
    app.state.test_scoped_permissions = {}
    return TestClient(app)


@pytest.fixture
def reader_client(app):
    """Non-admin holding only `projects:read`. Used to confirm granular gates."""
    app.state.test_user_id = "non-admin-test-user"
    app.state.test_is_admin = False
    app.state.test_permissions = {"projects:read"}
    app.state.test_scoped_permissions = {("global", None): {"projects:read"}}
    return TestClient(app)
