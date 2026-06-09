"""Integration tests for RefreshTokenRepository — the multi-session refresh fix.

These pin the two failure modes that caused the long-standing "logged out for
no reason, every now and then" bug, proving they're gone:

  * Scenario A — a 2nd login/session must NOT invalidate the first.
  * Scenario B — rotating a token must NOT evict it within the grace window
    (the old single-slot model evicted on the 2nd rotation).

plus revoke-all (logout / deactivate / password-reset), expiry, and grace-expiry.

Runs against the real DB (DATABASE_URL); rows are rolled back per test.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.repositories.refresh_token_repository import RefreshTokenRepository

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


def _jti() -> str:
    return uuid4().hex


def _exp(days: int = 7) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def test_multiple_sessions_coexist(session):
    """Scenario A: two logins for the same user keep BOTH refresh tokens valid."""
    repo = RefreshTokenRepository(session)
    uid = "u-" + _jti()[:8]
    a, b = _jti(), _jti()
    repo.create(user_id=uid, jti=a, expires_at=_exp())   # login #1
    repo.create(user_id=uid, jti=b, expires_at=_exp())   # login #2 (other tab/device)
    assert repo.get_active_by_jti(a, grace_seconds=120) is not None
    assert repo.get_active_by_jti(b, grace_seconds=120) is not None


def test_rotate_keeps_old_valid_within_grace(session):
    """Scenario B: rotating mints a new token without evicting the old one
    inside the grace window — concurrent refreshes coexist."""
    repo = RefreshTokenRepository(session)
    uid = "u-" + _jti()[:8]
    a = _jti()
    row = repo.create(user_id=uid, jti=a, expires_at=_exp())
    b = _jti()
    repo.rotate(row, new_jti=b, new_expires_at=_exp())
    assert repo.get_active_by_jti(a, grace_seconds=120) is not None  # old still valid (grace)
    assert repo.get_active_by_jti(b, grace_seconds=120) is not None  # new valid
    # ...but once grace is exhausted the rotated token is rejected.
    assert repo.get_active_by_jti(a, grace_seconds=0) is None


def test_revoke_all_for_user(session):
    """logout / deactivate / password-reset kill every live session."""
    repo = RefreshTokenRepository(session)
    uid = "u-" + _jti()[:8]
    a, b = _jti(), _jti()
    repo.create(user_id=uid, jti=a, expires_at=_exp())
    repo.create(user_id=uid, jti=b, expires_at=_exp())
    revoked = repo.revoke_all_for_user(uid)
    assert revoked >= 2
    assert repo.get_active_by_jti(a, grace_seconds=120) is None
    assert repo.get_active_by_jti(b, grace_seconds=120) is None


def test_revoke_by_jti_is_per_session(session):
    """Revoking one session leaves the other usable."""
    repo = RefreshTokenRepository(session)
    uid = "u-" + _jti()[:8]
    a, b = _jti(), _jti()
    repo.create(user_id=uid, jti=a, expires_at=_exp())
    repo.create(user_id=uid, jti=b, expires_at=_exp())
    repo.revoke_by_jti(a)
    assert repo.get_active_by_jti(a, grace_seconds=120) is None
    assert repo.get_active_by_jti(b, grace_seconds=120) is not None


def test_expired_token_rejected(session):
    repo = RefreshTokenRepository(session)
    uid = "u-" + _jti()[:8]
    a = _jti()
    repo.create(
        user_id=uid, jti=a,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert repo.get_active_by_jti(a, grace_seconds=120) is None


def test_unknown_or_empty_jti_rejected(session):
    repo = RefreshTokenRepository(session)
    assert repo.get_active_by_jti(_jti(), grace_seconds=120) is None
    assert repo.get_active_by_jti("", grace_seconds=120) is None


def test_delete_stale_keeps_live_drops_dead(session):
    """Pruning (table-growth guard) drops expired + past-grace-rotated rows,
    keeps live ones."""
    repo = RefreshTokenRepository(session)
    uid = "u-" + _jti()[:8]
    live = _jti()
    repo.create(user_id=uid, jti=live, expires_at=_exp())
    repo.create(
        user_id=uid, jti=_jti(),
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),   # expired
    )
    rotated = _jti()
    row = repo.create(user_id=uid, jti=rotated, expires_at=_exp())
    repo.rotate(row, new_jti=_jti(), new_expires_at=_exp())              # rotated_at = now
    deleted = repo.delete_stale_for_user(uid, grace_seconds=0)           # past-grace immediately
    assert deleted >= 2                                                  # expired + rotated
    assert repo.get_active_by_jti(live, grace_seconds=120) is not None   # live survives


def test_session_cap_revokes_oldest(session):
    """enforce_session_cap bounds concurrent sessions per account."""
    repo = RefreshTokenRepository(session)
    uid = "u-" + _jti()[:8]
    jtis = [_jti() for _ in range(5)]
    for j in jtis:
        repo.create(user_id=uid, jti=j, expires_at=_exp())
    revoked = repo.enforce_session_cap(uid, max_active=3)
    assert revoked == 2
    survivors = [j for j in jtis if repo.get_active_by_jti(j, grace_seconds=120) is not None]
    assert len(survivors) == 3
