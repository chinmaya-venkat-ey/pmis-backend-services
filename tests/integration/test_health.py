"""Integration tests for /health, /ready, / on project-svc."""
from __future__ import annotations

from unittest.mock import MagicMock


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "pmis-project-management"


def test_root_returns_service_info(client):
    resp = client.get("/")
    assert resp.status_code == 200
    # ``/`` is HAL-wrapped; data carries the service-info dict with
    # camelCased keys (snake_case -> camelCase happens in the HAL layer).
    data = resp.json()["data"]
    assert data["service"] == "pmis-project-management"
    assert "docsUrl" in data


def test_ready_503_when_db_unreachable(client, app, fake_db_session):
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


def test_ready_200_when_db_responds(client, app, fake_db_session):
    from app.db import get_db

    fake_db_session.execute.return_value = MagicMock()

    def _override():
        yield fake_db_session

    app.dependency_overrides[get_db] = _override
    try:
        resp = client.get("/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
    finally:
        app.dependency_overrides.pop(get_db, None)
