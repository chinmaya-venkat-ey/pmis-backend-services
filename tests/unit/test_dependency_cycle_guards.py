"""Unit tests for the dependency-cycle guards across milestone / activity /
task / subtask services.

The pattern is the same in each: a frontier walk through the existing
dependency edges checks whether the new dependsOn list (directly or
transitively) reaches back to the row itself.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.errors import DependencyCycleError, ValidationError


def test_milestone_cycle_self_rejected():
    """Monolith parity: milestone cycle is rejected as ``ValidationError``
    (422) with message ``"Adding milestone dependency on <uuid> would
    create a cycle."`` — NOT the generic ``DependencyCycleError`` (409)
    used for other entities."""
    from app.services.milestone_service import MilestoneService

    svc = MilestoneService(MagicMock())
    svc.repo.list_dependencies_for = MagicMock(return_value=[])

    with pytest.raises(ValidationError) as exc:
        svc._guard_dependency_cycle("m-1", ["m-1"])
    assert "would create a cycle" in str(exc.value)


def test_milestone_cycle_transitive_rejected():
    """m-1 depends on m-2 which depends on m-3 which depends on m-1 → reject."""
    from app.services.milestone_service import MilestoneService

    svc = MilestoneService(MagicMock())
    edges = {"m-2": ["m-3"], "m-3": ["m-1"]}
    svc.repo.list_dependencies_for = MagicMock(side_effect=lambda mid: edges.get(mid, []))

    with pytest.raises(ValidationError) as exc:
        svc._guard_dependency_cycle("m-1", ["m-2"])
    assert "would create a cycle" in str(exc.value)


def test_milestone_no_cycle_allowed():
    from app.services.milestone_service import MilestoneService

    svc = MilestoneService(MagicMock())
    edges = {"m-2": ["m-3"], "m-3": []}
    svc.repo.list_dependencies_for = MagicMock(side_effect=lambda mid: edges.get(mid, []))

    svc._guard_dependency_cycle("m-1", ["m-2"])  # Should not raise


def test_activity_cycle_self_rejected():
    """Monolith parity: activity cycle is rejected as ``ValidationError``
    (422) — same per-module casing as milestone."""
    from app.services.activity_service import ActivityService

    svc = ActivityService(MagicMock())
    svc.repo.list_dependencies_for = MagicMock(return_value=[])

    with pytest.raises(ValidationError) as exc:
        svc._guard_dependency_cycle("a-1", ["a-1"])
    assert "would create a cycle" in str(exc.value)


def test_task_cycle_self_rejected():
    from app.services.task_service import TaskService

    svc = TaskService(MagicMock())
    svc.repo.list_dependencies_for = MagicMock(return_value=[])

    with pytest.raises(DependencyCycleError):
        svc._guard_dependency_cycle("t-1", ["t-1"])


def test_subtask_cycle_self_rejected():
    """Monolith parity: subtask cycle is rejected as ``ValidationError``
    (422) with message ``"Adding dependency on '<uuid>' would create a
    cycle."`` — same shape as Activity, NOT the generic
    ``DependencyCycleError`` (409) that Task still uses."""
    from app.services.subtask_service import SubtaskService

    svc = SubtaskService(MagicMock())
    svc.repo.list_dependencies_for = MagicMock(return_value=[])

    with pytest.raises(ValidationError) as exc:
        svc._guard_dependency_cycle("s-1", ["s-1"])
    assert "would create a cycle" in str(exc.value)
