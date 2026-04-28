from app.services.otp_service import get_otp_service


def _peek_otp(channel: str, destination: str) -> str:
    svc = get_otp_service()
    key = f"{channel}:{destination.lower()}"
    return svc._store[key].otp


def test_otp_sms_flow(client):
    dest = "+919999000001"
    r = client.post(
        "/api/v1/notifications/otp/send",
        json={"channel": "sms", "destination": dest, "purpose": "login"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True
    assert r.json()["channel"] == "sms"

    otp = _peek_otp("sms", dest)
    v = client.post(
        "/api/v1/notifications/otp/verify",
        json={"channel": "sms", "destination": dest, "otp": otp},
    )
    assert v.status_code == 200
    assert v.json()["verified"] is True


def test_otp_email_flow(client):
    dest = "user@example.com"
    r = client.post(
        "/api/v1/notifications/otp/send",
        json={"channel": "email", "destination": dest, "purpose": "signup"},
    )
    assert r.status_code == 200, r.text
    otp = _peek_otp("email", dest)
    v = client.post(
        "/api/v1/notifications/otp/verify",
        json={"channel": "email", "destination": dest, "otp": otp},
    )
    assert v.status_code == 200
    assert v.json()["verified"] is True


def test_otp_invalid(client):
    dest = "+919999000002"
    client.post(
        "/api/v1/notifications/otp/send",
        json={"channel": "sms", "destination": dest},
    )
    v = client.post(
        "/api/v1/notifications/otp/verify",
        json={"channel": "sms", "destination": dest, "otp": "000000"},
    )
    assert v.status_code == 200
    assert v.json()["verified"] is False


def test_otp_unknown_destination(client):
    v = client.post(
        "/api/v1/notifications/otp/verify",
        json={"channel": "sms", "destination": "+910000000000", "otp": "123456"},
    )
    assert v.status_code == 404


def test_otp_invalid_email_destination(client):
    r = client.post(
        "/api/v1/notifications/otp/send",
        json={"channel": "email", "destination": "not-an-email"},
    )
    assert r.status_code == 422
