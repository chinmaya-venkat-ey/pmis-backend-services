"""Unit tests for UserService — Doc-44 caller-vs-target gate, last-super-admin
lockout, and the basic CRUD error paths. No DB."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.errors import (
    CallerCannotModifyTargetError,
    LastSuperAdminLockoutError,
    UserEmailAlreadyInUseError,
    UserLoginAlreadyInUseError,
    UserNotFoundError,
)


def _make_user(*, user_id="u-1", login="alice", email="a@example.com", vendor_id=None):
    row = MagicMock(name=f"User({user_id})")
    row.id = user_id
    row.login = login
    row.email = email
    row.vendor_id = vendor_id
    row.status = "active"
    row.deleted_at = None
    row.hashed_password = "argon2-hash"
    return row


def test_get_by_id_not_found():
    from app.services.user_service import UserService

    svc = UserService(MagicMock())
    svc.repo.get_by_id = MagicMock(return_value=None)

    with pytest.raises(UserNotFoundError):
        svc.get_by_id("missing")


def test_doc44_gate_self_edit_allowed():
    """A caller editing themselves never needs admin or vendor match."""
    from app.services.user_service import UserService

    svc = UserService(MagicMock())
    target = _make_user(user_id="u-1", vendor_id="vend-A")
    # Should not raise.
    svc._assert_caller_can_modify("u-1", target, caller_is_admin=False)


def test_doc44_gate_admin_allowed():
    from app.services.user_service import UserService

    svc = UserService(MagicMock())
    target = _make_user(user_id="u-2", vendor_id="vend-A")
    svc._assert_caller_can_modify("u-9", target, caller_is_admin=True)


def test_doc44_gate_cross_vendor_blocked():
    """Non-admin caller in a different vendor can't modify the target."""
    from app.services.user_service import UserService

    svc = UserService(MagicMock())
    target = _make_user(user_id="u-2", vendor_id="vend-A")
    caller = _make_user(user_id="u-9", vendor_id="vend-B")
    svc.repo.get_by_id = MagicMock(return_value=caller)

    with pytest.raises(CallerCannotModifyTargetError) as exc_info:
        svc._assert_caller_can_modify("u-9", target, caller_is_admin=False)
    assert exc_info.value.details["target_user_id"] == "u-2"


def test_doc44_gate_same_vendor_allowed():
    from app.services.user_service import UserService

    svc = UserService(MagicMock())
    target = _make_user(user_id="u-2", vendor_id="vend-A")
    caller = _make_user(user_id="u-9", vendor_id="vend-A")
    svc.repo.get_by_id = MagicMock(return_value=caller)

    # Should not raise.
    svc._assert_caller_can_modify("u-9", target, caller_is_admin=False)


def test_delete_blocks_last_super_admin():
    """If the target is the only super_admin remaining, delete must raise."""
    from app.services.user_service import UserService

    svc = UserService(MagicMock())
    target = _make_user(user_id="u-super")
    svc.repo.get_by_id = MagicMock(return_value=target)
    svc._assert_caller_can_modify = MagicMock()  # bypass Doc-44
    svc._is_only_super_admin = MagicMock(return_value=True)

    with pytest.raises(LastSuperAdminLockoutError):
        svc.delete("u-super", caller_user_id="u-super", caller_is_admin=True)


def test_delete_proceeds_when_other_super_admins_exist():
    from app.services.user_service import UserService

    svc = UserService(MagicMock())
    target = _make_user(user_id="u-super")
    svc.repo.get_by_id = MagicMock(return_value=target)
    svc._assert_caller_can_modify = MagicMock()
    svc._is_only_super_admin = MagicMock(return_value=False)
    svc.repo.soft_delete = MagicMock()
    svc.repo.rotate_refresh_token = MagicMock()

    result = svc.delete("u-super", caller_user_id="u-other-admin", caller_is_admin=True)
    assert result is target
    svc.repo.soft_delete.assert_called_once()
    svc.db.commit.assert_called_once()
