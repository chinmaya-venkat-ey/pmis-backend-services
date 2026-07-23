"""#188 — Start Activity API guard logic (unit).

The happy path + workflow round-trip is covered E2E; these lock the validation
gates: already-started, already-completed, closed project, and incomplete
predecessors all raise before any mutation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.errors import ValidationError
from app.services.activity_service import ActivityService


def _service():
    svc = ActivityService(MagicMock())
    svc.projects = MagicMock()
    svc.repo = MagicMock()
    svc.audit = MagicMock()
    svc.db = MagicMock()
    return svc


def _activity(**kw):
    base = dict(
        id="a1", project_id="p1", status="not_completed",
        activity_started=False, actual_start_date=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_start_rejects_already_started():
    svc = _service()
    svc.get_by_id = MagicMock(return_value=_activity(activity_started=True))
    svc.projects.get_by_id.return_value = SimpleNamespace(status="published")
    with pytest.raises(ValidationError, match="already started"):
        svc.start("a1", caller_user_id="u1")
    svc.repo.update.assert_not_called()


def test_start_rejects_completed_activity():
    svc = _service()
    svc.get_by_id = MagicMock(return_value=_activity(status="completed"))
    svc.projects.get_by_id.return_value = SimpleNamespace(status="published")
    with pytest.raises(ValidationError, match="already completed"):
        svc.start("a1", caller_user_id="u1")
    svc.repo.update.assert_not_called()


def test_start_rejects_closed_project():
    svc = _service()
    svc.get_by_id = MagicMock(return_value=_activity())
    svc.projects.get_by_id.return_value = SimpleNamespace(status="closed")
    with pytest.raises(ValidationError, match="closed project"):
        svc.start("a1", caller_user_id="u1")
    svc.repo.update.assert_not_called()


def test_start_rejects_incomplete_predecessors():
    svc = _service()
    svc.get_by_id = MagicMock(return_value=_activity())
    svc.projects.get_by_id.return_value = SimpleNamespace(status="published")
    svc.dependency_completion_status = MagicMock(return_value={
        "eligible": False,
        "blockers": [{"id": "dep1", "name": "Upstream Work", "status": "not_completed"}],
    })
    with pytest.raises(ValidationError, match="not yet completed"):
        svc.start("a1", caller_user_id="u1")
    svc.repo.update.assert_not_called()


def test_start_happy_path_sets_started_and_commits():
    svc = _service()
    row = _activity()
    svc.get_by_id = MagicMock(return_value=row)
    svc.projects.get_by_id.return_value = SimpleNamespace(status="published")
    svc.dependency_completion_status = MagicMock(return_value={"eligible": True, "blockers": []})
    out = svc.start("a1", caller_user_id="u1")
    assert out is row
    # activity_started + actual_start_date written, audited, committed.
    _, kwargs = svc.repo.update.call_args
    assert kwargs["activity_started"] is True
    assert kwargs["actual_start_date"] is not None
    svc.audit.write.assert_called_once()
    svc.db.commit.assert_called_once()
