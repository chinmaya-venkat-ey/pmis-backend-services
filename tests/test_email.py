def test_send_email_success(client):
    payload = {
        "to": ["user@example.com"],
        "subject": "Hello",
        "body": "Hi there",
        "is_html": False,
    }
    r = client.post("/api/v1/notifications/email/send", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["provider"] == "smtp"
    assert body["message_id"] == "stub-msg-id"


def test_send_email_validation(client):
    r = client.post(
        "/api/v1/notifications/email/send",
        json={"to": ["not-an-email"], "subject": "x", "body": "y"},
    )
    assert r.status_code == 422
    assert r.json()["success"] is False
