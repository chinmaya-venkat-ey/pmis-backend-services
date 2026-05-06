"""Tests for the templated dispatch endpoint (doc 38 phase 2).

These cover the wire contract user-mgmt depends on. Render-detail tests
(placeholder substitution, ttl conversion, fallbacks) live in
``test_notification_templates.py::TestRenderer`` against the underlying
service-layer functions.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text


@pytest.fixture
def client_with_templates(monkeypatch):
    """TestClient + seeded templates + stubbed SMTP/SMS providers."""
    from app.db.session import Base, SessionLocal, engine, _seed_built_in_templates
    from app.db.models.notification_template import NotificationTemplateModel
    from app.services import email_service, sms_service, otp_service

    # Stub providers so tests don't open real sockets / hit real APIs.
    monkeypatch.setattr(
        email_service._SMTPProvider,
        "send",
        lambda self, to, subject, body, is_html, cc=None, bcc=None: "stub-email-id",
    )
    monkeypatch.setattr(
        sms_service._MockSMSProvider,
        "send",
        lambda self, to, message: "stub-sms-id",
    )
    # Force SMS provider to mock and reset cached singletons.
    monkeypatch.setattr("app.config.settings.sms_provider", "mock")
    email_service._email_service = None
    sms_service._sms_service = None
    otp_service._otp_service = None

    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=engine)
        # Wipe + reseed so each test starts clean.
        db.execute(text("DELETE FROM notification_templates"))
        _seed_built_in_templates(db, NotificationTemplateModel)
        db.commit()
    finally:
        db.close()

    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


class TestDispatch:
    def test_email_dispatch_renders_seeded_template(self, client_with_templates):
        resp = client_with_templates.post(
            "/api/v1/notifications/dispatch",
            json={
                "channel": "email",
                "recipient": "alice@example.com",
                "template_kind": "otp_login",
                "payload": {"code": "987654", "ttl_seconds": 300},
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["channel"] == "email"
        assert body["template_kind"] == "otp_login"
        assert body["message_id"] == "stub-email-id"
        assert body["rendered_subject"]

    def test_sms_dispatch_renders_seeded_template(self, client_with_templates):
        resp = client_with_templates.post(
            "/api/v1/notifications/dispatch",
            json={
                "channel": "sms",
                "recipient": "+919999999999",
                "template_kind": "otp_login",
                "payload": {"code": "112233", "ttl_seconds": 300},
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["channel"] == "sms"
        assert body["template_kind"] == "otp_login"
        assert body["message_id"] == "stub-sms-id"
        # SMS has no subject — field is omitted.
        assert body.get("rendered_subject") is None

    def test_dispatch_unknown_template_falls_back(self, client_with_templates):
        """No active row for the kind → fallback subject/body, never 500."""
        resp = client_with_templates.post(
            "/api/v1/notifications/dispatch",
            json={
                "channel": "email",
                "recipient": "alice@example.com",
                "template_kind": "totally_unknown_kind",
                "payload": {},
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        # Generic fallback subject from template_service.
        assert body["rendered_subject"] == "PMIS notification"

    def test_dispatch_rejects_unknown_channel(self, client_with_templates):
        resp = client_with_templates.post(
            "/api/v1/notifications/dispatch",
            json={
                "channel": "carrier-pigeon",
                "recipient": "alice@example.com",
                "template_kind": "otp_login",
                "payload": {},
            },
        )
        assert resp.status_code == 422, resp.text

    def test_dispatch_missing_required_fields(self, client_with_templates):
        resp = client_with_templates.post(
            "/api/v1/notifications/dispatch",
            json={"channel": "email"},
        )
        assert resp.status_code == 422, resp.text
