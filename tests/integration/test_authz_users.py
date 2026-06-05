"""Integration tests for GET /api/v3/authz/users (discovery query)."""
from __future__ import annotations

from unittest.mock import MagicMock


def test_authz_users_anonymous_401(anonymous_client):
    resp = anonymous_client.get("/api/v3/authz/users?project_id=P1")
    assert resp.status_code == 401
    assert resp.json()["error"]["errorIdentifier"] in {"AUTH_REQUIRED", "auth_required"}


def test_authz_users_no_selector_422(client, app, fake_db_session):
    """Selector validation runs before any DB access, so a mocked session is
    enough to reach the 422."""
    from app.db import get_db

    def _override():
        yield fake_db_session

    app.dependency_overrides[get_db] = _override
    try:
        resp = client.get("/api/v3/authz/users")
        assert resp.status_code == 422
        assert resp.json()["error"]["errorIdentifier"] in {
            "VALIDATION_ERROR", "validation_error",
        }
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_authz_users_returns_collection(client, app):
    from app.controllers.authz_controller import AuthzController
    from app.dependencies import get_authz_controller
    from app.schemas.authz import AuthzUserSummary

    fake = MagicMock(spec=AuthzController)
    fake.list_users.return_value = [
        AuthzUserSummary(id="u1", login="alice", roles=["project_admin"]),
    ]

    app.dependency_overrides[get_authz_controller] = lambda: fake
    try:
        resp = client.get("/api/v3/authz/users?project_id=P1")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["_type"] == "Collection"
        assert data["total"] == 1
        assert data["_embedded"]["elements"][0]["login"] == "alice"
        assert data["_embedded"]["elements"][0]["roles"] == ["project_admin"]
    finally:
        app.dependency_overrides.pop(get_authz_controller, None)
