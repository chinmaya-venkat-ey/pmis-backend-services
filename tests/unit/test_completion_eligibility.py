"""Unit tests for the activity dependency completion-eligibility logic.

Covers the shared ``dependency_completion_status`` helper, the public
``completion_eligibility`` method, and confirms the refactored
``_assert_deps_completed`` gate preserves its original raise/no-raise
behaviour (so the existing status-flip gate on PATCH is unchanged).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.errors import ValidationError
from app.services.activity_service import ActivityService


def _svc_with_deps(dep_ids, rows):
    """ActivityService whose repo returns ``dep_ids`` and whose
    ``db.execute(...).all()`` returns ``rows`` (each ``(id, name, status)``)."""
    svc = ActivityService(MagicMock())
    svc.repo.list_dependencies_for = MagicMock(return_value=dep_ids)
    svc.db.execute.return_value.all.return_value = rows
    return svc


def test_no_dependencies_is_eligible():
    svc = _svc_with_deps([], [])
    assert svc.dependency_completion_status("a-1") == {"eligible": True, "blockers": []}
    # Short-circuits before touching the DB when there are no dependencies.
    svc.db.execute.assert_not_called()


def test_all_dependencies_completed_is_eligible():
    svc = _svc_with_deps(
        ["a-2", "a-3"],
        [("a-2", "Act 2", "completed"), ("a-3", "Act 3", "completed")],
    )
    result = svc.dependency_completion_status("a-1")
    assert result["eligible"] is True
    assert result["blockers"] == []


def test_incomplete_dependency_blocks():
    svc = _svc_with_deps(
        ["a-2", "a-3"],
        [("a-2", "Act 2", "completed"), ("a-3", "Act 3", "not_completed")],
    )
    result = svc.dependency_completion_status("a-1")
    assert result["eligible"] is False
    assert result["blockers"] == [
        {"id": "a-3", "name": "Act 3", "status": "not_completed"},
    ]


def test_assert_deps_completed_passes_when_eligible():
    svc = _svc_with_deps(["a-2"], [("a-2", "Act 2", "completed")])
    svc._assert_deps_completed("a-1")  # must not raise


def test_assert_deps_completed_no_deps_passes():
    svc = _svc_with_deps([], [])
    svc._assert_deps_completed("a-1")  # must not raise


def test_assert_deps_completed_raises_with_blocker_names():
    """Preserves the original 422 message shape (names quoted, first 3)."""
    svc = _svc_with_deps(
        ["a-2", "a-3"],
        [("a-2", "Act 2", "not_completed"), ("a-3", "Act 3", "not_completed")],
    )
    with pytest.raises(ValidationError) as exc:
        svc._assert_deps_completed("a-1")
    msg = str(exc.value)
    assert "not yet completed" in msg
    assert "'Act 2'" in msg and "'Act 3'" in msg


def test_assert_deps_completed_truncates_to_three_with_more_suffix():
    svc = _svc_with_deps(
        ["a-2", "a-3", "a-4", "a-5"],
        [
            ("a-2", "Act 2", "not_completed"),
            ("a-3", "Act 3", "not_completed"),
            ("a-4", "Act 4", "not_completed"),
            ("a-5", "Act 5", "not_completed"),
        ],
    )
    with pytest.raises(ValidationError) as exc:
        svc._assert_deps_completed("a-1")
    assert "(+1 more)" in str(exc.value)


def test_completion_eligibility_validates_existence_and_shapes_result():
    svc = _svc_with_deps(["a-2"], [("a-2", "Act 2", "not_completed")])
    svc.get_by_id = MagicMock()  # exists -> no 404
    result = svc.completion_eligibility("a-1")
    svc.get_by_id.assert_called_once_with("a-1")
    assert result == {
        "activity_id": "a-1",
        "eligible": False,
        "blocking_dependencies": [
            {"id": "a-2", "name": "Act 2", "status": "not_completed"},
        ],
    }
