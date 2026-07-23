"""#365 — SuperAdmin session admin service logic (unit).

The full lifecycle (list / revoke-all / revoke-one, instant access-token cut,
super_admin gating) is covered E2E; these lock the service behaviour with the
repos mocked: revoke denylists every live access jti AND revokes the refresh
sessions, and single-revoke refuses a session that isn't the target user's.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.errors import NotFoundError, UserNotFoundError
from app.services.auth_service import AuthService


def _service():
    svc = AuthService(MagicMock())
    svc.user_repo = MagicMock()
    svc.refresh_repo = MagicMock()
    svc.revoked = MagicMock()
    svc.db = MagicMock()
    svc.user_repo.get_by_id.return_value = SimpleNamespace(id="u1", deleted_at=None)
    return svc


def test_list_sessions_maps_rows():
    svc = _service()
    svc.refresh_repo.list_active_sessions.return_value = [
        SimpleNamespace(jti="s1", issued_at="t1", last_used_at="t2", expires_at="t3"),
    ]
    out = svc.list_user_sessions("u1")
    assert out == [{"session_id": "s1", "issued_at": "t1",
                    "last_used_at": "t2", "expires_at": "t3"}]


def test_list_sessions_404_for_missing_user():
    svc = _service()
    svc.user_repo.get_by_id.return_value = None
    with pytest.raises(UserNotFoundError):
        svc.list_user_sessions("ghost")


def test_revoke_all_denylists_every_access_jti_and_revokes_refresh():
    svc = _service()
    svc.refresh_repo.live_access_jtis.return_value = ["a1", "a2", "a3"]
    svc.refresh_repo.revoke_all_for_user.return_value = 3
    n = svc.revoke_all_user_sessions("u1")
    assert n == 3
    # every live access token denylisted (instant hard cut) ...
    assert svc.revoked.revoke.call_count == 3
    # ... and the refresh sessions revoked, then committed.
    svc.refresh_repo.revoke_all_for_user.assert_called_once_with("u1")
    svc.db.commit.assert_called_once()


def test_revoke_one_denylists_access_and_revokes_that_session():
    svc = _service()
    svc.refresh_repo.get_by_jti.return_value = SimpleNamespace(
        jti="s1", user_id="u1", access_jti="a1",
    )
    svc.revoke_user_session("u1", "s1")
    svc.revoked.revoke.assert_called_once()
    svc.refresh_repo.revoke_by_jti.assert_called_once_with("s1")
    svc.db.commit.assert_called_once()


def test_revoke_one_rejects_session_of_other_user():
    svc = _service()
    svc.refresh_repo.get_by_jti.return_value = SimpleNamespace(
        jti="s1", user_id="someone_else", access_jti="a1",
    )
    with pytest.raises(NotFoundError):
        svc.revoke_user_session("u1", "s1")
    svc.refresh_repo.revoke_by_jti.assert_not_called()


def test_revoke_one_404_when_session_missing():
    svc = _service()
    svc.refresh_repo.get_by_jti.return_value = None
    with pytest.raises(NotFoundError):
        svc.revoke_user_session("u1", "nope")
