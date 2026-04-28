def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["email_provider"] == "smtp"
    assert body["sms_provider"] == "mock"


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["docs"] == "/docs"


def test_openapi(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    paths = spec["paths"]
    assert "/api/v1/notifications/email/send" in paths
    assert "/api/v1/notifications/sms/send" in paths
    assert "/api/v1/notifications/otp/send" in paths
    assert "/api/v1/notifications/otp/verify" in paths


def test_swagger_ui(client):
    r = client.get("/docs")
    assert r.status_code == 200
    assert "swagger" in r.text.lower()
