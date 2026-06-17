"""Admin-tier assignees are exempt from the task/subtask membership guard.

A task/subtask `assignedTo` is normally required to be a project member
(vendor mapped + role on the project). An admin/super_admin holds neither but
is implicitly a member of every project, so the guard must let them through.
See app/core/admin_tier.is_user_admin_tier + TaskService/SubtaskService
._validate_assignee.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.errors import CallerCannotModifyTargetError


# --------------------------------------------------- is_user_admin_tier ----

def _db_with_first(side_effect):
    db = MagicMock()
    db.execute.return_value.first.side_effect = side_effect
    return db


def test_is_user_admin_tier_legacy_global():
    from app.core.admin_tier import is_user_admin_tier
    # legacy user_roles query (first call) hits -> True, scoped never queried
    assert is_user_admin_tier(_db_with_first([("role",)]), "u1") is True


def test_is_user_admin_tier_global_assignment():
    from app.core.admin_tier import is_user_admin_tier
    # legacy miss, then global-scoped assignment hit -> True
    assert is_user_admin_tier(_db_with_first([None, (123,)]), "u1") is True


def test_is_user_admin_tier_false_when_neither():
    from app.core.admin_tier import is_user_admin_tier
    assert is_user_admin_tier(_db_with_first([None, None]), "u1") is False


def test_is_user_admin_tier_empty_user_id():
    from app.core.admin_tier import is_user_admin_tier
    db = MagicMock()
    assert is_user_admin_tier(db, "") is False
    db.execute.assert_not_called()  # short-circuits, no query


# --------------------------------------------- _validate_assignee exemption -

def _service(cls, assignee_row):
    svc = cls.__new__(cls)          # bypass __init__ (no real DB)
    svc.db = MagicMock()
    svc.db.execute.return_value.scalar_one_or_none.return_value = assignee_row
    return svc


@pytest.mark.parametrize("svc_path", [
    "app.services.task_service.TaskService",
    "app.services.subtask_service.SubtaskService",
])
def test_validate_assignee_exempts_admin_tier(svc_path):
    mod, cls_name = svc_path.rsplit(".", 1)
    import importlib
    cls = getattr(importlib.import_module(mod), cls_name)
    # live (not deleted) assignee, no vendor / no project role
    svc = _service(cls, MagicMock(deleted_at=None, vendor_id=None))
    with patch("app.core.admin_tier.is_user_admin_tier", return_value=True):
        # returns early — must NOT raise despite missing vendor/role
        assert svc._validate_assignee("admin-uid", "proj-1") is None


@pytest.mark.parametrize("svc_path", [
    "app.services.task_service.TaskService",
    "app.services.subtask_service.SubtaskService",
])
def test_validate_assignee_rejects_non_admin_non_member(svc_path):
    mod, cls_name = svc_path.rsplit(".", 1)
    import importlib
    cls = getattr(importlib.import_module(mod), cls_name)
    svc = _service(cls, MagicMock(deleted_at=None, vendor_id=None))
    with patch("app.core.admin_tier.is_user_admin_tier", return_value=False):
        with pytest.raises(CallerCannotModifyTargetError):
            svc._validate_assignee("user-uid", "proj-1")
