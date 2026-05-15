"""Integration tests for POST /notification/cron/daily-digest.

Tests the X-Cron-Secret gating + the empty-result happy path.
The full digest orchestration is tested at the unit level (test_digest_service)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _set_cron_secret(value: str | None):
    """Mutate the cached settings singleton's cron_shared_secret for the test."""
    from app.config import settings
    settings.cron_shared_secret = value or ""


def test_cron_requires_secret_to_be_configured(client):
    _set_cron_secret(None)
    resp = client.post("/notification/cron/daily-digest", json={})
    # CRON_NOT_CONFIGURED uses the UnauthorizedError default (401)
    assert resp.status_code == 401
    assert resp.json()["code"] in {"CRON_NOT_CONFIGURED", "CRON_UNAUTHORIZED"}


def test_cron_rejects_missing_header(client):
    _set_cron_secret("supersecret")
    try:
        resp = client.post("/notification/cron/daily-digest", json={})
        assert resp.status_code == 401
        assert resp.json()["code"] == "CRON_SECRET_MISMATCH"
    finally:
        _set_cron_secret(None)


def test_cron_rejects_wrong_header(client):
    _set_cron_secret("supersecret")
    try:
        resp = client.post(
            "/notification/cron/daily-digest",
            headers={"X-Cron-Secret": "wrong"},
            json={},
        )
        assert resp.status_code == 401
    finally:
        _set_cron_secret(None)


def test_cron_runs_with_correct_secret_no_items(
    client, app, fake_db_session, mock_email_service,
):
    """Happy path with no qualifying milestones/activities → summary zeros."""
    from app.db import get_db
    from app.repositories.digest_repository import DigestRepository
    from app.services.email_service import get_email_service

    _set_cron_secret("supersecret")

    # Mock the repository methods to return no items.
    DigestRepository.find_due_milestones = lambda self, today, window_days: []
    DigestRepository.find_due_activities = lambda self, today, window_days: []

    def _db_override():
        yield fake_db_session

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[get_email_service] = lambda: mock_email_service
    try:
        resp = client.post(
            "/notification/cron/daily-digest",
            headers={"X-Cron-Secret": "supersecret"},
            json={},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["usersNotified"] == 0
        assert body["emailsSent"] == 0
        assert body["itemsAggregated"] == 0
        # No emails should have been sent
        mock_email_service.send.assert_not_called()
    finally:
        _set_cron_secret(None)
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_email_service, None)


def test_cron_validates_today_format(client, fake_db_session):
    _set_cron_secret("supersecret")
    try:
        resp = client.post(
            "/notification/cron/daily-digest",
            headers={"X-Cron-Secret": "supersecret"},
            json={"today": "not-a-date"},
        )
        # Pydantic catches the pattern mismatch first → 422
        assert resp.status_code == 422
    finally:
        _set_cron_secret(None)
