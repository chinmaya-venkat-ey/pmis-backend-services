"""Integration tests for OTP session resumability (Bug #240).

The login-attempt SESSION (anchored on ``generated_at``, ``otp_session_ttl``)
must outlive an individual OTP CODE (``expires_at``, ``otp_ttl``), so a user can
resend a fresh code after the current one expires — without re-entering
credentials — up to the session cap.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.user import User  # noqa: F401 — registers users.users so OtpCode's FK resolves
from app.repositories.otp_code_repository import OtpCodeRepository

DB_URL = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="DATABASE_URL not set")


@pytest.fixture
def session():
    engine = create_engine(DB_URL)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def uid(session):
    """A real user id — otp_codes.user_id is a FK to users.users."""
    from sqlalchemy import text
    row = session.execute(
        text("SELECT id FROM users.users WHERE deleted_at IS NULL LIMIT 1")
    ).first()
    if not row:
        pytest.skip("no seeded users in the DB")
    return row[0]


def _h() -> str:
    return uuid4().hex


def _mk(repo, uid):
    eph = _h()
    row = repo.create(
        user_id=uid, channel="email", code_hash=None,
        ephemeral_token_hash=eph, ttl_seconds=300,
    )
    return eph, row


def test_resumable_after_code_expiry(session, uid):
    """The code expired but the session is still alive -> resend can proceed,
    even though the old code-window lookup rejects it."""
    repo = OtpCodeRepository(session)
    eph, row = _mk(repo, uid)
    now = datetime.now(timezone.utc)
    row.expires_at = now - timedelta(seconds=60)      # code expired a minute ago
    row.generated_at = now - timedelta(seconds=360)   # session started 6 min ago (< 15 cap)
    session.flush()
    assert repo.get_active_by_ephemeral_token(eph) is None            # code window: rejected
    assert repo.get_resumable_by_ephemeral_token(eph, session_ttl_seconds=900) is not None  # session: ok


def test_resumable_rejects_past_session_cap(session, uid):
    """Beyond the session cap, even resend is refused -> user must re-login."""
    repo = OtpCodeRepository(session)
    eph, row = _mk(repo, uid)
    row.generated_at = datetime.now(timezone.utc) - timedelta(seconds=1000)  # > 900 cap
    session.flush()
    assert repo.get_resumable_by_ephemeral_token(eph, session_ttl_seconds=900) is None


def test_resumable_rejects_consumed(session, uid):
    """A consumed (already-used) session can't be resumed."""
    repo = OtpCodeRepository(session)
    eph, row = _mk(repo, uid)
    repo.consume(row)
    assert repo.get_resumable_by_ephemeral_token(eph, session_ttl_seconds=900) is None


def test_fresh_session_resumable_and_active(session, uid):
    """A fresh session is found by both lookups (sanity)."""
    repo = OtpCodeRepository(session)
    eph, _ = _mk(repo, uid)
    assert repo.get_active_by_ephemeral_token(eph) is not None
    assert repo.get_resumable_by_ephemeral_token(eph, session_ttl_seconds=900) is not None
