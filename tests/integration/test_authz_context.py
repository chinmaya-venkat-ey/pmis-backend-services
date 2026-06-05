"""Integration tests for GET /api/v3/authz/context.

Confirms the endpoint is a normal protected route (401 anonymous) and that
an authenticated caller receives the HAL-wrapped resolved context.
"""
from __future__ import annotations

from unittest.mock import MagicMock


def test_authz_context_anonymous_401(anonymous_client):
    resp = anonymous_client.get("/api/v3/authz/context")
    assert resp.status_code == 401
    assert resp.json()["error"]["errorIdentifier"] in {"AUTH_REQUIRED", "auth_required"}


def test_authz_context_authenticated_returns_resolved(client, app):
    from app.controllers.authz_controller import AuthzController
    from app.dependencies import get_authz_controller
    from app.schemas.authz import AuthzContextResponse

    fake = MagicMock(spec=AuthzController)
    fake.get_context.return_value = AuthzContextResponse(
        user_id="test-admin-id",
        vendor_id=None,
        permissions=["users:read"],
        scoped={"global": ["users:read"], "project:P1": ["projects:close"]},
    )

    app.dependency_overrides[get_authz_controller] = lambda: fake
    try:
        resp = client.get("/api/v3/authz/context")
        assert resp.status_code == 200
        # Response middleware HAL-wraps the model under `data`.
        data = resp.json()["data"]
        assert data["user_id"] == "test-admin-id"
        assert data["permissions"] == ["users:read"]
        assert data["scoped"]["project:P1"] == ["projects:close"]
        assert data["scoped"]["global"] == ["users:read"]
        # No admin flag leaks into the decision surface.
        assert "is_admin" not in data
        assert "is_super_admin" not in data
    finally:
        app.dependency_overrides.pop(get_authz_controller, None)
