"""Integration tests for POST /notification/dispatch.

Verifies the template-render → provider-send orchestration. The template
repository is mocked so the test doesn't need a real masters.notification_templates row.
"""
from __future__ import annotations

from unittest.mock import MagicMock


def test_dispatch_email_renders_template_and_sends(
    client, app, fake_db_session, mock_email_service, mock_sms_service,
):
    """Happy-path: template found → renders → calls email_service.send."""
    from app.db import get_db
    from app.repositories.notification_template_repository import (
        NotificationTemplateRepository,
    )
    from app.services.email_service import get_email_service
    from app.services.sms_service import get_sms_service

    # Mock the template found in masters.notification_templates
    fake_template = MagicMock()
    fake_template.subject = "Your OTP code"
    fake_template.body = "Your code is {code}, valid for {ttl_minutes} min."
    fake_template.is_html = False

    original_find_active = NotificationTemplateRepository.find_active
    NotificationTemplateRepository.find_active = lambda self, *, template_kind, channel: fake_template

    def _db_override():
        yield fake_db_session

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[get_email_service] = lambda: mock_email_service
    app.dependency_overrides[get_sms_service] = lambda: mock_sms_service

    try:
        resp = client.post(
            "/notification/dispatch",
            json={
                "channel": "email",
                "recipient": "alice@example.com",
                "template_kind": "otp_login",
                "payload": {"code": "123456", "ttl_seconds": 300},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["channel"] == "email"
        assert body["template_kind"] == "otp_login"
        # Subject was rendered
        assert body["rendered_subject"] == "Your OTP code"

        # Verify the email body was format_map'd
        mock_email_service.send.assert_called_once()
        sent_body = mock_email_service.send.call_args.kwargs["body"]
        assert "123456" in sent_body
        assert "5" in sent_body  # ttl_minutes = 300/60 = 5
    finally:
        NotificationTemplateRepository.find_active = original_find_active
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_email_service, None)
        app.dependency_overrides.pop(get_sms_service, None)


def test_dispatch_validation_rejects_unknown_channel(client):
    resp = client.post(
        "/notification/dispatch",
        json={
            "channel": "telegram",  # not in Literal["email","sms"]
            "recipient": "x",
            "template_kind": "x",
            "payload": {},
        },
    )
    assert resp.status_code == 422


def test_dispatch_falls_back_when_no_template(
    client, app, fake_db_session, mock_email_service, mock_sms_service,
):
    """Missing template → falls back to generic PMIS notification, still sends."""
    from app.db import get_db
    from app.repositories.notification_template_repository import (
        NotificationTemplateRepository,
    )
    from app.services.email_service import get_email_service
    from app.services.sms_service import get_sms_service

    original = NotificationTemplateRepository.find_active
    NotificationTemplateRepository.find_active = lambda self, **kwargs: None

    def _db_override():
        yield fake_db_session

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[get_email_service] = lambda: mock_email_service
    app.dependency_overrides[get_sms_service] = lambda: mock_sms_service

    try:
        resp = client.post(
            "/notification/dispatch",
            json={
                "channel": "email",
                "recipient": "alice@example.com",
                "template_kind": "nonexistent_kind",
                "payload": {},
            },
        )
        assert resp.status_code == 200
        # Fallback subject was used
        assert resp.json()["rendered_subject"] == "PMIS notification"
        mock_email_service.send.assert_called_once()
    finally:
        NotificationTemplateRepository.find_active = original
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_email_service, None)
        app.dependency_overrides.pop(get_sms_service, None)
