"""Smoke tests that verify the Option C granular RBAC gates are wired correctly.

Doesn't exercise full CRUD per catalog — that's a Phase 4 follow-up against
a real Postgres. Here we just confirm:
  - Anonymous callers get 401 on every protected endpoint
  - A non-admin reader with only `<catalog>:read` can list but can't create
  - An admin (test default) can do everything

If any of these break, every catalog is suspect.
"""
from __future__ import annotations

from unittest.mock import MagicMock


def test_anonymous_cannot_list_divisions(anonymous_client):
    resp = anonymous_client.get("/api/v3/master/divisions")
    assert resp.status_code == 401
    assert resp.json()["error"]["errorIdentifier"] in {"AUTH_REQUIRED", "auth_required"}


def test_anonymous_cannot_list_vendors(anonymous_client):
    resp = anonymous_client.get("/api/v3/master/vendors")
    assert resp.status_code == 401


def test_anonymous_cannot_create_division(anonymous_client):
    resp = anonymous_client.post(
        "/api/v3/master/divisions/create",
        json={
            "code": "test_div",
            "label": "Test",
            "email": "test@example.com",
            "phone_number": "+910000000000",
        },
    )
    assert resp.status_code == 401


def test_reader_can_list_divisions(reader_client, app, fake_db_session):
    """Reader holds divisions:read → list_divisions passes the gate.
    DB session is mocked to return an empty list."""
    from app.db import get_db
    from sqlalchemy.engine import Result

    # Mock the session's execute().scalars().all() chain
    result = MagicMock(spec=Result)
    result.scalars.return_value.all.return_value = []
    fake_db_session.execute.return_value = result

    def _override():
        yield fake_db_session

    app.dependency_overrides[get_db] = _override
    try:
        resp = reader_client.get("/api/v3/master/divisions")
        assert resp.status_code == 200
        assert resp.json() == []
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_reader_cannot_create_division(reader_client):
    """Reader does NOT hold divisions:manage → 403 on create."""
    resp = reader_client.post(
        "/api/v3/master/divisions/create",
        json={
            "code": "test_div",
            "label": "Test",
            "email": "test@example.com",
            "phone_number": "+910000000000",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["errorIdentifier"] in {"PERMISSION_DENIED", "permission_denied"}


def test_reader_cannot_list_vendors(reader_client):
    """Reader holds divisions:read only, NOT vendors:read → 403."""
    resp = reader_client.get("/api/v3/master/vendors")
    assert resp.status_code == 403


def test_admin_can_list_vendors(client, app, fake_db_session):
    """Admin (test default) bypasses per-permission check."""
    from app.db import get_db
    from sqlalchemy.engine import Result

    result = MagicMock(spec=Result)
    result.scalars.return_value.all.return_value = []
    fake_db_session.execute.return_value = result

    def _override():
        yield fake_db_session

    app.dependency_overrides[get_db] = _override
    try:
        resp = client.get("/api/v3/master/vendors")
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)
