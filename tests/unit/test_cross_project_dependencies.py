"""Cross-project dependency tests.

Same-type dependencies may now target an entity in ANY project. The existence
gate (`_assert_deps_exist`) only rejects targets that don't resolve to a real
row of the right type; it no longer rejects targets that merely live in
another project. Completion-blocking, cycle detection and the date-outlasting
rule are unchanged (they were never project-scoped) and keep working across
projects.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.errors import ValidationError


def _svc_db_returns(svc, rows):
    """Make svc.db.execute(...).all() return ``rows``."""
    exec_mock = MagicMock()
    exec_mock.all.return_value = rows
    svc.db.execute = MagicMock(return_value=exec_mock)
    return svc


# ---------------------------------------------------- existence gate ---------

def test_activity_dep_allows_cross_project_existing_target():
    from app.services.activity_service import ActivityService
    svc = _svc_db_returns(ActivityService(MagicMock()), [("a-other-proj",)])
    svc._assert_deps_exist(["a-other-proj"])  # must not raise


def test_activity_dep_rejects_unknown_target():
    from app.services.activity_service import ActivityService
    svc = _svc_db_returns(ActivityService(MagicMock()), [])
    with pytest.raises(ValidationError) as exc:
        svc._assert_deps_exist(["a-unknown"])
    assert "Unknown activity dependency target" in str(exc.value)


def test_milestone_dep_allows_cross_project_existing_target():
    from app.services.milestone_service import MilestoneService
    svc = _svc_db_returns(MilestoneService(MagicMock()), [("m-other-proj",)])
    svc._assert_deps_exist(["m-other-proj"])  # must not raise


def test_milestone_dep_rejects_unknown_or_meeting_target():
    """A meeting milestone is filtered out by the kept is_meeting guard, so it
    resolves to no row and is rejected just like an unknown target."""
    from app.services.milestone_service import MilestoneService
    svc = _svc_db_returns(MilestoneService(MagicMock()), [])
    with pytest.raises(ValidationError) as exc:
        svc._assert_deps_exist(["m-meeting-or-unknown"])
    assert "Unknown milestone dependency target" in str(exc.value)


def test_partial_unknown_among_cross_project_targets_rejected():
    """Mixed batch: one resolves (cross-project ok), one doesn't -> reject the
    missing one only."""
    from app.services.activity_service import ActivityService
    svc = _svc_db_returns(ActivityService(MagicMock()), [("a-real",)])
    with pytest.raises(ValidationError) as exc:
        svc._assert_deps_exist(["a-real", "a-missing"])
    assert "a-missing" in str(exc.value)
    assert "a-real" not in str(exc.value)


# ---------------------------------------- cycle detection (cross-project) ----

def test_cross_project_cycle_detected():
    """The cycle guard follows edges regardless of project: a cross-project
    edge that loops back to the source is still rejected."""
    from app.services.activity_service import ActivityService
    svc = ActivityService(MagicMock())
    # a-1 (project A) -> a-2 (project B); a-2 already depends back on a-1.
    edges = {"a-2": ["a-1"]}
    svc.repo.list_dependencies_for = MagicMock(
        side_effect=lambda i: edges.get(i, []),
    )
    with pytest.raises(ValidationError) as exc:
        svc._guard_dependency_cycle("a-1", ["a-2"])
    assert "would create a cycle" in str(exc.value)


# ------------------------------ completion gate (blocks across projects) -----

def test_completion_blocked_by_incomplete_cross_project_target():
    """dependency_completion_status queries the target by id with NO project
    filter, so an incomplete target in another project blocks completion."""
    from app.services.activity_service import ActivityService
    svc = ActivityService(MagicMock())
    svc.repo.list_dependencies_for = MagicMock(return_value=["a-other-proj"])
    _svc_db_returns(
        svc, [("a-other-proj", "Cross Proj Act", "not_completed")],
    )
    result = svc.dependency_completion_status("a-1")
    assert result["eligible"] is False
    assert result["blockers"][0]["id"] == "a-other-proj"


def test_completion_allowed_when_cross_project_target_completed():
    from app.services.activity_service import ActivityService
    svc = ActivityService(MagicMock())
    svc.repo.list_dependencies_for = MagicMock(return_value=["a-other-proj"])
    _svc_db_returns(svc, [("a-other-proj", "Cross Proj Act", "completed")])
    result = svc.dependency_completion_status("a-1")
    assert result["eligible"] is True
    assert result["blockers"] == []
