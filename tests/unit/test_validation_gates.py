"""Unit tests for the monolith-parity validation gates added across the
project / milestone / activity / task / subtask services.

Covers:
  * Project-lock (tasks / subtasks require ``status='published'``).
  * Priority catalog rejection.
  * Same-project dependency check.
  * Doc-31 dep-date outlasting rule (forward, milestone-style).
  * Children-completion gate (parent cannot complete while child pending).
  * Parent-revert gate (cannot revert to not_completed while parent completed).
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.core.errors import ValidationError


# --------------------------------------------------- project-lock gate -----


def test_task_create_requires_published_project():
    """A draft / new project must reject task creation with the monolith's
    ``publish_required`` error (HTTP 409)."""
    from app.utilities.project_lock import assert_task_subtask_writable

    draft = MagicMock(status="draft", deleted_at=None)
    with pytest.raises(Exception) as exc:
        assert_task_subtask_writable(draft)
    msg = str(exc.value).lower()
    assert "published" in msg


def test_task_create_passes_on_published_project():
    from app.utilities.project_lock import assert_task_subtask_writable

    pub = MagicMock(status="published", deleted_at=None)
    assert_task_subtask_writable(pub)  # should not raise


def test_milestone_writable_does_not_require_publish():
    """Milestones and activities can be authored on a draft project."""
    from app.utilities.project_lock import assert_milestone_activity_writable

    draft = MagicMock(status="draft", deleted_at=None)
    assert_milestone_activity_writable(draft)  # should not raise


# ------------------------------------------ dep existence check (xproj) -----
# Cross-project dependencies are now allowed: the gate only rejects targets
# that don't resolve to a real (non-deleted) row of the right type — it no
# longer rejects targets that merely live in another project.


def test_task_dep_rejects_unknown_target():
    """A task dependency on a non-existent task id is rejected as
    ``Unknown task dependency target(s)``."""
    from app.services.task_service import TaskService

    svc = TaskService(MagicMock())
    exec_mock = MagicMock()
    exec_mock.all.return_value = []  # id resolves to no task row
    svc.db.execute = MagicMock(return_value=exec_mock)

    with pytest.raises(ValidationError) as exc:
        svc._assert_deps_exist(["t-unknown"])
    assert "Unknown task dependency target" in str(exc.value)


def test_task_dep_allows_existing_cross_project_target():
    """An existing task in ANOTHER project is a valid dependency target now —
    the existence query returns the row, so no error is raised."""
    from app.services.task_service import TaskService

    svc = TaskService(MagicMock())
    exec_mock = MagicMock()
    exec_mock.all.return_value = [("t-other-project",)]  # row exists (any project)
    svc.db.execute = MagicMock(return_value=exec_mock)

    svc._assert_deps_exist(["t-other-project"])  # must not raise


def test_subtask_dep_rejects_unknown_target():
    from app.services.subtask_service import SubtaskService

    svc = SubtaskService(MagicMock())
    exec_mock = MagicMock()
    exec_mock.all.return_value = []
    svc.db.execute = MagicMock(return_value=exec_mock)

    with pytest.raises(ValidationError) as exc:
        svc._assert_deps_exist(["s-unknown"])
    assert "Unknown subtask dependency target" in str(exc.value)


def test_subtask_dep_allows_existing_cross_project_target():
    from app.services.subtask_service import SubtaskService

    svc = SubtaskService(MagicMock())
    exec_mock = MagicMock()
    exec_mock.all.return_value = [("s-other-project",)]
    svc.db.execute = MagicMock(return_value=exec_mock)

    svc._assert_deps_exist(["s-other-project"])  # must not raise


# ------------------------------------------- Doc-31 dep-date outlasting ----


def test_dep_dates_outlasting_rejects_equal_end():
    """Source end MUST be strictly after target end (equality is a violation)."""
    from app.utilities.dep_date_rules import (
        collect_forward_violations,
        raise_forward_if_violations,
    )

    starts, ends = collect_forward_violations(
        source_start=datetime(2026, 6, 1),
        source_end=datetime(2026, 6, 30),
        targets=[("Target-A", datetime(2026, 6, 1), datetime(2026, 6, 30))],
    )
    assert not starts
    assert len(ends) == 1
    with pytest.raises(ValidationError) as exc:
        raise_forward_if_violations(
            starts, ends,
            source_label="'src'",
            source_start=datetime(2026, 6, 1),
            source_end=datetime(2026, 6, 30),
            kind_singular="task",
        )
    assert "end strictly after" in str(exc.value)


def test_dep_dates_outlasting_allows_equal_start():
    """Source start may equal target start (start-floor is non-strict)."""
    from app.utilities.dep_date_rules import collect_forward_violations

    starts, ends = collect_forward_violations(
        source_start=datetime(2026, 6, 1),
        source_end=datetime(2026, 7, 1),
        targets=[("Target-A", datetime(2026, 6, 1), datetime(2026, 6, 30))],
    )
    assert not starts
    assert not ends


def test_dep_dates_outlasting_rejects_earlier_start():
    from app.utilities.dep_date_rules import collect_forward_violations

    starts, _ = collect_forward_violations(
        source_start=datetime(2026, 5, 20),
        source_end=datetime(2026, 7, 1),
        targets=[("Target-A", datetime(2026, 6, 1), datetime(2026, 6, 30))],
    )
    assert len(starts) == 1
    assert starts[0][0] == "Target-A"


# ------------------------------------------- children-completion gates -----


def test_task_complete_blocked_when_subtasks_pending():
    """A task can't transition to a terminal status while top-level
    subtasks remain non-terminal."""
    from app.services.task_service import TaskService

    svc = TaskService(MagicMock())
    exec_mock = MagicMock()
    exec_mock.all.return_value = [("Child-A", "in_progress"), ("Child-B", "in_progress")]
    svc.db.execute = MagicMock(return_value=exec_mock)

    with pytest.raises(ValidationError) as exc:
        svc._assert_all_child_subtasks_completed("t-1")
    assert "Child-A" in str(exc.value) and "Child-B" in str(exc.value)


def test_subtask_complete_blocked_when_nested_pending():
    from app.services.subtask_service import SubtaskService

    svc = SubtaskService(MagicMock())
    exec_mock = MagicMock()
    exec_mock.all.return_value = [("Nested-A", "in_progress")]
    svc.db.execute = MagicMock(return_value=exec_mock)

    with pytest.raises(ValidationError) as exc:
        svc._assert_all_nested_subtasks_completed("s-1")
    assert "Nested-A" in str(exc.value)


# ---------------------------------------------- parent-revert gate ---------


def test_task_revert_blocked_when_parent_activity_completed():
    from app.services.task_service import TaskService

    svc = TaskService(MagicMock())
    completed_activity = MagicMock(id="a-1", name="Parent-A", status="completed")
    svc.activities.get_by_id = MagicMock(return_value=completed_activity)

    with pytest.raises(ValidationError) as exc:
        svc._assert_parent_activity_not_completed("a-1")
    assert "Parent-A" in str(exc.value)


def test_subtask_revert_blocked_when_parent_task_completed():
    from app.services.subtask_service import SubtaskService

    svc = SubtaskService(MagicMock())
    completed_task = MagicMock(id="t-1", name="Parent-T", status="completed")
    svc.tasks.get_by_id = MagicMock(return_value=completed_task)

    # Top-level subtask: row.parent_subtask_id is None, row.task_id set.
    row = MagicMock(parent_subtask_id=None, task_id="t-1")
    with pytest.raises(ValidationError) as exc:
        svc._assert_parent_not_completed(row)
    assert "Parent-T" in str(exc.value)


# --------------------------------------------- REVERSE dep-date outlasting ----


def test_milestone_reverse_dep_rejects_date_move_breaking_dependent():
    """If milestone M1 has a downstream dependent M2 (M2 dependsOn M1) and
    we move M1's end forward past M2's end, the reverse check must reject."""
    from app.services.milestone_service import MilestoneService

    svc = MilestoneService(MagicMock())
    # One downstream source M2 with end 2026-06-30.
    exec_mock = MagicMock()
    exec_mock.all.return_value = [
        ("M2", datetime(2026, 6, 1), datetime(2026, 6, 30)),
    ]
    svc.db.execute = MagicMock(return_value=exec_mock)

    target = MagicMock(id="m-1", name="M1")
    # New target window: end pushed to 2026-07-15 — M2.end (06-30) no
    # longer strictly after target.end → reverse rule breaks.
    with pytest.raises(ValidationError) as exc:
        svc._assert_dep_dates_reverse(
            target,
            new_start=datetime(2026, 5, 1),
            new_end=datetime(2026, 7, 15),
        )
    assert "M2" in str(exc.value)


def test_task_reverse_dep_passes_when_no_dependents():
    """When no row points AT this target, reverse must be a no-op."""
    from app.services.task_service import TaskService

    svc = TaskService(MagicMock())
    exec_mock = MagicMock()
    exec_mock.all.return_value = []
    svc.db.execute = MagicMock(return_value=exec_mock)

    target = MagicMock(id="t-1", name="T1")
    svc._assert_dep_dates_reverse(
        target,
        new_start=datetime(2026, 6, 1),
        new_end=datetime(2026, 7, 1),
    )  # should not raise


def test_subtask_reverse_dep_rejects_start_break():
    from app.services.subtask_service import SubtaskService

    svc = SubtaskService(MagicMock())
    exec_mock = MagicMock()
    exec_mock.all.return_value = [
        ("S2", datetime(2026, 6, 1), datetime(2026, 7, 1)),
    ]
    svc.db.execute = MagicMock(return_value=exec_mock)

    target = MagicMock(id="s-1", name="S1")
    # Push target start AHEAD of dependent's start → S2.start < target.start.
    with pytest.raises(ValidationError) as exc:
        svc._assert_dep_dates_reverse(
            target,
            new_start=datetime(2026, 6, 15),
            new_end=datetime(2026, 6, 20),
        )
    assert "S2" in str(exc.value)
