"""Unit tests for the parent-floor + actual-date ordering rules used by
milestone / activity / task / subtask / nested-subtask creates and
updates.

Error messages MUST match the monolith verbatim (see
``PMIS-OpenProject/app/shared/date_rules.py``). The FE renders these
strings directly, so any drift would break the user-visible error UX.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.errors import ValidationError
from app.utilities.date_rules import (
    validate_entity_dates,
    validate_resource_dates,
)


IST = timezone(timedelta(hours=5, minutes=30))
PROJECT_START = datetime(2026, 6, 1, tzinfo=IST)
MS_START = datetime(2026, 6, 15, tzinfo=IST)
ACTIVITY_START = datetime(2026, 7, 1, tzinfo=IST)
TASK_START = datetime(2026, 7, 10, tzinfo=IST)
SUBTASK_START = datetime(2026, 7, 20, tzinfo=IST)


def _call(
    entity_start, entity_end, parent_start, parent_label,
    entity_label="milestone",
    actual_start=None, actual_end=None,
    project_start=PROJECT_START,
):
    validate_entity_dates(
        entity_start=entity_start,
        entity_end=entity_end,
        actual_start=actual_start,
        actual_end=actual_end,
        parent_start_date=parent_start,
        project_start_date=project_start,
        entity_label=entity_label,
        parent_label=parent_label,
    )


# ----- parent-floor equality is allowed ---------------------------------

def test_milestone_start_equals_project_start_allowed():
    _call(PROJECT_START, PROJECT_START + timedelta(days=10),
          PROJECT_START, "project")


def test_activity_start_equals_milestone_start_allowed():
    _call(MS_START, MS_START + timedelta(days=10),
          MS_START, "milestone", entity_label="activity")


def test_task_start_equals_activity_start_allowed():
    _call(ACTIVITY_START, ACTIVITY_START + timedelta(days=10),
          ACTIVITY_START, "activity", entity_label="task")


def test_subtask_start_equals_task_start_allowed():
    _call(TASK_START, TASK_START + timedelta(days=10),
          TASK_START, "task", entity_label="subtask")


def test_nested_subtask_start_equals_parent_subtask_start_allowed():
    _call(SUBTASK_START, SUBTASK_START + timedelta(days=10),
          SUBTASK_START, "subtask", entity_label="subtask")


# ----- parent-floor rejects start < parent_start, message verbatim -----

def test_milestone_start_before_project_rejected():
    with pytest.raises(ValidationError) as exc:
        _call(PROJECT_START - timedelta(days=1),
              PROJECT_START + timedelta(days=10),
              PROJECT_START, "project")
    assert exc.value.message == (
        "Milestone start date cannot be before the project start date "
        "(2026-06-01)."
    )


def test_activity_start_before_milestone_rejected():
    with pytest.raises(ValidationError) as exc:
        _call(MS_START - timedelta(days=1),
              MS_START + timedelta(days=10),
              MS_START, "milestone", entity_label="activity")
    assert exc.value.message == (
        "Activity start date cannot be before the milestone start date "
        "(2026-06-15)."
    )


def test_task_start_before_activity_rejected():
    with pytest.raises(ValidationError) as exc:
        _call(ACTIVITY_START - timedelta(days=1),
              ACTIVITY_START + timedelta(days=10),
              ACTIVITY_START, "activity", entity_label="task")
    assert exc.value.message == (
        "Task start date cannot be before the activity start date "
        "(2026-07-01)."
    )


def test_subtask_start_before_task_rejected():
    with pytest.raises(ValidationError) as exc:
        _call(TASK_START - timedelta(days=1),
              TASK_START + timedelta(days=10),
              TASK_START, "task", entity_label="subtask")
    assert exc.value.message == (
        "Subtask start date cannot be before the task start date "
        "(2026-07-10)."
    )


def test_nested_subtask_start_before_parent_subtask_rejected():
    with pytest.raises(ValidationError) as exc:
        _call(SUBTASK_START - timedelta(days=1),
              SUBTASK_START + timedelta(days=10),
              SUBTASK_START, "subtask", entity_label="subtask")
    assert exc.value.message == (
        "Subtask start date cannot be before the subtask start date "
        "(2026-07-20)."
    )


# ----- entity_end >= entity_start (no upper cap) ------------------------

def test_end_before_start_rejected():
    with pytest.raises(ValidationError) as exc:
        _call(MS_START, MS_START - timedelta(days=1),
              PROJECT_START, "project")
    assert exc.value.message == (
        "Milestone end date cannot be before its start date."
    )


def test_entity_end_past_parent_end_allowed():
    """No upper-bound check: activity end can extend past milestone end."""
    _call(MS_START, MS_START + timedelta(days=100),  # arbitrary far future
          MS_START, "milestone", entity_label="activity")


# ----- actual-date floor + ordering ------------------------------------

def test_actual_start_before_project_rejected():
    with pytest.raises(ValidationError) as exc:
        _call(MS_START, MS_START + timedelta(days=10),
              PROJECT_START, "project",
              actual_start=PROJECT_START - timedelta(days=1))
    assert exc.value.message == (
        "Milestone actual start date cannot be before the project start "
        "date (2026-06-01)."
    )


def test_actual_end_before_actual_start_rejected():
    with pytest.raises(ValidationError) as exc:
        _call(MS_START, MS_START + timedelta(days=10),
              PROJECT_START, "project",
              actual_start=MS_START,
              actual_end=MS_START - timedelta(days=1))
    assert exc.value.message == (
        "Milestone actual end date cannot be before the actual start date."
    )


def test_actual_end_before_project_start_when_no_actual_start_rejected():
    with pytest.raises(ValidationError) as exc:
        _call(MS_START, MS_START + timedelta(days=10),
              PROJECT_START, "project",
              actual_end=PROJECT_START - timedelta(days=1))
    assert exc.value.message == (
        "Milestone actual end date cannot be before the project start "
        "date (2026-06-01)."
    )


# ----- calendar-date semantics (IST normalization) ---------------------

def test_same_calendar_date_across_tz_encodings_allowed():
    """``2026-06-01T00:00:00Z`` (UTC midnight) and
    ``2026-06-01T00:00:00+05:30`` (IST midnight) both resolve to the
    same IST calendar date (Jun 1). The IST-midnight normalizer in
    ``date_rules`` lets the comparison succeed."""
    utc_midnight = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    _call(utc_midnight, datetime(2026, 6, 10, tzinfo=IST),
          PROJECT_START, "project")


# ----- resource sub-entity rules ---------------------------------------

def test_resource_offboard_before_onboard_rejected():
    with pytest.raises(ValidationError) as exc:
        validate_resource_dates(
            onboard=MS_START,
            actual_onboard=None,
            offboard=MS_START - timedelta(days=1),
            actual_offboard=None,
            project_start_date=PROJECT_START,
        )
    assert exc.value.message == (
        "Offboard date cannot be before the onboard date."
    )


def test_resource_actual_offboard_before_actual_onboard_rejected():
    with pytest.raises(ValidationError) as exc:
        validate_resource_dates(
            onboard=None,
            actual_onboard=MS_START,
            offboard=None,
            actual_offboard=MS_START - timedelta(days=1),
            project_start_date=PROJECT_START,
        )
    assert exc.value.message == (
        "Actual offboard date cannot be before the actual onboard date."
    )
