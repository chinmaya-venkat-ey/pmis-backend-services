def test_send_sms_success(client):
    r = client.post(
        "/api/v1/notifications/sms/send",
        json={"to": "+919999999999", "message": "Hello from PIMS"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["provider"] == "mock"
    assert body["message_id"].startswith("mock-")


def test_send_sms_validation(client):
    r = client.post(
        "/api/v1/notifications/sms/send",
        json={"to": "+919999999999", "message": ""},
    )
    assert r.status_code == 422
