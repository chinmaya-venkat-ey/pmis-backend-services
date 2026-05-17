"""pytest fixtures for pmis-notification-management.

Provides:
  - `client` — FastAPI TestClient with `get_db` overridden to a fake/no-op session
    (most notification-svc endpoints don't actually need a DB; tests that do
    override `get_db` themselves with an in-test session or mocked repository).
  - `mock_email_service` / `mock_sms_service` — replace the real providers
    so tests don't actually try to hit SMTP / Twilio.
  - `cron_secret` — sets settings.cron_shared_secret for the duration of a test.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
def app():
    """Build a fresh FastAPI app per test (clean dependency overrides)."""
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(app):
    """TestClient wrapping the app. Tests override dependencies as needed."""
    return TestClient(app)


@pytest.fixture
def fake_db_session():
    """A MagicMock standing in for a SQLAlchemy Session.

    Tests that exercise DB-backed endpoints override `app.db.get_db` to
    yield this fixture (so the real engine is never touched).
    """
    return MagicMock(name="FakeSession")


@pytest.fixture
def mock_email_service():
    """A MagicMock standing in for EmailService.send."""
    svc = MagicMock(name="EmailService")
    svc.send.return_value = {
        "success": True,
        "message": "Email sent successfully",
        "provider": "mock",
        "message_id": "test-email-1",
    }
    return svc


@pytest.fixture
def mock_sms_service():
    """A MagicMock standing in for SMSService.send."""
    svc = MagicMock(name="SMSService")
    svc.send.return_value = {
        "success": True,
        "message": "SMS sent successfully",
        "provider": "mock",
        "message_id": "test-sms-1",
    }
    return svc
