"""Integration tests for POST /notification/email/send."""
from __future__ import annotations


def test_send_email_happy_path(client, app, mock_email_service):
    from app.services.email_service import get_email_service

    app.dependency_overrides[get_email_service] = lambda: mock_email_service
    try:
        resp = client.post(
            "/notification/email/send",
            json={
                "to": ["alice@example.com"],
                "subject": "Hello",
                "body": "<p>Hi</p>",
                "is_html": True,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["provider"] == "mock"
        mock_email_service.send.assert_called_once()
        call_kwargs = mock_email_service.send.call_args.kwargs
        assert call_kwargs["to"] == ["alice@example.com"]
        assert call_kwargs["subject"] == "Hello"
        assert call_kwargs["is_html"] is True
    finally:
        app.dependency_overrides.pop(get_email_service, None)


def test_send_email_validation_rejects_empty_to(client):
    resp = client.post(
        "/notification/email/send",
        json={"to": [], "subject": "x", "body": "y"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"


def test_send_email_validation_rejects_invalid_email(client):
    resp = client.post(
        "/notification/email/send",
        json={"to": ["not-an-email"], "subject": "x", "body": "y"},
    )
    assert resp.status_code == 422
