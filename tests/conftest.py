import os
import sys
import tempfile
from pathlib import Path

# Ensure repo root is on sys.path so `import app` works without install
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Force safe defaults BEFORE the app/settings module imports
os.environ.setdefault("EMAIL_PROVIDER", "smtp")
os.environ.setdefault("SMS_PROVIDER", "mock")
os.environ.setdefault("OTP_RESEND_COOLDOWN_SECONDS", "0")
os.environ.setdefault("OTP_LENGTH", "6")
os.environ.setdefault("OTP_TTL_SECONDS", "300")

# Doc 38: DB-backed templates need a real test DB. Use a tempfile-
# backed SQLite so multiple SessionLocal() calls (fixture seeding +
# auth middleware lookup) share the same data. Pure ``:memory:``
# would isolate each connection.
_TMPDB = os.path.join(tempfile.gettempdir(), f"notif_test_{os.getpid()}.db")
if os.path.exists(_TMPDB):
    os.remove(_TMPDB)
os.environ.setdefault(
    "DATABASE_URL", f"sqlite:///{_TMPDB.replace(os.sep, '/')}"
)
os.environ.setdefault(
    "SECRET_KEY", "shared-test-secret-key-32-chars-min-shared-test",
)
os.environ.setdefault("ALGORITHM", "HS256")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import email_service, otp_service


@pytest.fixture
def client(monkeypatch):
    # Stub out the SMTP provider so tests don't open a real socket
    def fake_send(self, to, subject, body, is_html, cc=None, bcc=None):
        return "stub-msg-id"

    monkeypatch.setattr(email_service._SMTPProvider, "send", fake_send)

    # Reset OTP store between tests
    otp_service._otp_service = None

    return TestClient(app)
