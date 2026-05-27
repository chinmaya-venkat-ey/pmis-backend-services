"""Integration tests for POST /notification/sms/send."""
from __future__ import annotations


def test_send_sms_happy_path(client, app, mock_sms_service):
    from app.services.sms_service import get_sms_service

    app.dependency_overrides[get_sms_service] = lambda: mock_sms_service
    try:
        resp = client.post(
            "/notification/sms/send",
            json={"to": "+919999999999", "message": "Test SMS"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["provider"] == "mock"
        mock_sms_service.send.assert_called_once_with(
            to="+919999999999",
            message="Test SMS",
        )
    finally:
        app.dependency_overrides.pop(get_sms_service, None)


def test_send_sms_validation_rejects_non_e164(client, app, mock_sms_service):
    """Phone numbers must match E.164-ish: optional + then 4-15 digits.

    Note: the SMS service dependency must be overridden even on validation
    tests because SMSService.__init__ raises ProviderError when
    settings.sms_provider is empty (e.g. in dev .env). Without the override
    the request fails 502 at dependency-resolution time before Pydantic
    validation runs."""
    from app.services.sms_service import get_sms_service

    app.dependency_overrides[get_sms_service] = lambda: mock_sms_service
    try:
        resp = client.post(
            "/notification/sms/send",
            json={"to": "not-a-number", "message": "x"},
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(get_sms_service, None)


def test_send_sms_validation_rejects_empty_message(client, app, mock_sms_service):
    from app.services.sms_service import get_sms_service

    app.dependency_overrides[get_sms_service] = lambda: mock_sms_service
    try:
        resp = client.post(
            "/notification/sms/send",
            json={"to": "+919999999999", "message": ""},
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(get_sms_service, None)
