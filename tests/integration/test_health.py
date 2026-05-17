"""Integration tests for /health, /ready, /.

Pattern: TestClient call → assert status + envelope shape.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "pmis-notification-management"
    assert "version" in body


def test_root_returns_service_info(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "pmis-notification-management"
    assert "docs_url" in body


def test_ready_returns_503_when_db_unreachable(client, app, fake_db_session):
    """ /ready does a SELECT 1; if it raises, we expect 503."""
    from app.db import get_db

    fake_db_session.execute.side_effect = RuntimeError("DB down")

    def _override():
        yield fake_db_session

    app.dependency_overrides[get_db] = _override
    try:
        resp = client.get("/ready")
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_ready_returns_ok_when_db_responds(client, app, fake_db_session):
    from app.db import get_db

    fake_db_session.execute.return_value = MagicMock()  # SELECT 1 succeeds

    def _override():
        yield fake_db_session

    app.dependency_overrides[get_db] = _override
    try:
        resp = client.get("/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready"
        assert body["db"] == "ok"
    finally:
        app.dependency_overrides.pop(get_db, None)
