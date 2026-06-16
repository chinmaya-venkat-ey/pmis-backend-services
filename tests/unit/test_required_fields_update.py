"""Unit tests for the update-side required-field protection.

The invariant: a PATCH may OMIT a required field (no change), but may not
CLEAR it to empty (None / blank / empty list). Upsert (PUT) is full-replace,
so it requires the create-fields on both branches. Meeting/governance
activities stay exempt from the activity business fields, exactly like
create. Partial updates and all existing flows keep working.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.core.errors import ValidationError
from app.utilities.required_fields import (
    assert_required_not_cleared,
    is_empty_value,
)


IST = timezone(timedelta(hours=5, minutes=30))
START = datetime(2026, 5, 1, tzinfo=IST)
END = datetime(2026, 6, 1, tzinfo=IST)


# ----------------------------------------------------- helper logic ----------

@pytest.mark.parametrize("value,expected", [
    (None, True), ("", True), ("   ", True), ([], True), ({}, True), ((), True),
    ("x", False), (["a"], False), ("  x ", False), (0, False), (False, False),
])
def test_is_empty_value(value, expected):
    assert is_empty_value(value) is expected


def test_omitted_field_is_ignored():
    # Field not in the updates dict => no change => never flagged.
    assert_required_not_cleared({"description": "d"}, {"name": "name"}, entity="x")


def test_present_but_empty_is_rejected():
    with pytest.raises(ValidationError) as exc:
        assert_required_not_cleared({"name": None}, {"name": "name"}, entity="x")
    assert exc.value.details["cleared"] == ["name"]


def test_present_and_valid_passes():
    assert_required_not_cleared({"name": "ok"}, {"name": "name"}, entity="x")


def test_multiple_cleared_are_all_listed():
    with pytest.raises(ValidationError) as exc:
        assert_required_not_cleared(
            {"name": "", "start_date": None, "end_date": END},
            {"name": "name", "start_date": "startDate", "end_date": "endDate"},
            entity="x",
        )
    assert set(exc.value.details["cleared"]) == {"name", "startDate"}


# --------------------------------------------------- Activity update ---------

def _activity_update_svc(monkeypatch, *, is_meeting):
    from app.services.activity_service import ActivityService
    svc = ActivityService(MagicMock())
    row = MagicMock()
    row.id = "a1"
    row.milestone_id = "m1"
    row.project_id = "p1"
    row.status = "not_completed"
    svc.get_by_id = MagicMock(return_value=row)
    svc._resolve_update_finance_fields = MagicMock(return_value=(None, None))
    milestone = MagicMock()
    milestone.is_meeting = is_meeting
    svc.milestones.get_by_id = MagicMock(return_value=milestone)
    svc.repo = MagicMock()
    svc.audit = MagicMock()
    svc._validate_owner_division = MagicMock()
    svc._validate_priority = MagicMock()
    svc._validate_concerned_divisions = MagicMock()
    return svc


def test_activity_update_non_meeting_clearing_owner_rejected(monkeypatch):
    from app.schemas.activity import ActivityUpdateRequest
    svc = _activity_update_svc(monkeypatch, is_meeting=False)
    with pytest.raises(ValidationError) as exc:
        svc.update("a1", ActivityUpdateRequest(owner_division=None), caller_user_id="u1")
    assert "ownerDivision" in exc.value.details["cleared"]


def test_activity_update_meeting_clearing_owner_allowed(monkeypatch):
    from app.schemas.activity import ActivityUpdateRequest
    svc = _activity_update_svc(monkeypatch, is_meeting=True)
    # Meeting activity: business fields exempt -> clearing owner is allowed,
    # update runs to completion and returns the row.
    row = svc.update("a1", ActivityUpdateRequest(owner_division=None), caller_user_id="u1")
    assert row.id == "a1"


def test_activity_update_clearing_date_rejected_even_for_meeting(monkeypatch):
    from app.schemas.activity import ActivityUpdateRequest
    svc = _activity_update_svc(monkeypatch, is_meeting=True)
    with pytest.raises(ValidationError) as exc:
        svc.update("a1", ActivityUpdateRequest(start_date=None), caller_user_id="u1")
    assert "startDate" in exc.value.details["cleared"]


# ---------------------------------------------------- Project update ---------

def test_project_update_clearing_owner_rejected():
    from app.services.project_service import ProjectService
    from app.schemas.project import ProjectUpdateRequest
    svc = ProjectService(MagicMock())
    svc.get_by_id = MagicMock(return_value=MagicMock(status="draft"))
    with pytest.raises(ValidationError) as exc:
        svc.update("p1", ProjectUpdateRequest(owner=None), caller_user_id="u1")
    assert "owner" in exc.value.details["cleared"]


def test_project_update_clearing_vendors_rejected():
    from app.services.project_service import ProjectService
    from app.schemas.project import ProjectUpdateRequest
    svc = ProjectService(MagicMock())
    svc.get_by_id = MagicMock(return_value=MagicMock(status="draft"))
    with pytest.raises(ValidationError) as exc:
        svc.update("p1", ProjectUpdateRequest(vendor_ids=[]), caller_user_id="u1")
    assert exc.value.details["cleared"] == ["vendorIds"]


# ------------------------------------------------- Milestone update ----------

def test_milestone_update_clearing_start_rejected():
    from app.services.milestone_service import MilestoneService
    from app.schemas.milestone import MilestoneUpdateRequest
    svc = MilestoneService(MagicMock())
    svc.get_by_id = MagicMock(return_value=MagicMock())
    svc._assert_not_meeting_milestone = MagicMock()
    svc._resolve_update_finance_fields = MagicMock(return_value=(None, None))
    with pytest.raises(ValidationError) as exc:
        svc.update("m1", MilestoneUpdateRequest(start_date=None), caller_user_id="u1")
    assert "startDate" in exc.value.details["cleared"]


# ------------------------------------------------------- Task update ---------

def test_task_update_clearing_start_rejected(monkeypatch):
    from app.services.task_service import TaskService
    from app.schemas.task import TaskUpdateRequest
    monkeypatch.setattr(
        "app.services.task_service.assert_task_subtask_writable", lambda *a, **k: None,
    )
    svc = TaskService(MagicMock())
    svc.get_by_id = MagicMock(return_value=MagicMock(project_id="p1"))
    svc.projects.get_by_id = MagicMock(return_value=MagicMock(status="published"))
    with pytest.raises(ValidationError) as exc:
        svc.update("t1", TaskUpdateRequest(start_date=None), caller_user_id="u1")
    assert "startDate" in exc.value.details["cleared"]


# ---------------------------------------------------- Subtask update ---------

def test_subtask_update_clearing_name_rejected(monkeypatch):
    from app.services.subtask_service import SubtaskService
    from app.schemas.subtask import SubtaskUpdateRequest
    monkeypatch.setattr(
        "app.services.subtask_service.assert_task_subtask_writable", lambda *a, **k: None,
    )
    svc = SubtaskService(MagicMock())
    svc.get_by_id = MagicMock(return_value=MagicMock(project_id="p1"))
    svc.projects.get_by_id = MagicMock(return_value=MagicMock(status="published"))
    # name="" is blocked by the schema's min_length=1; the hole is name=null.
    with pytest.raises(ValidationError) as exc:
        svc.update("s1", SubtaskUpdateRequest(name=None), caller_user_id="u1")
    assert "name" in exc.value.details["cleared"]


# --------------------------------------------------- Project upsert ----------

def test_upsert_requires_create_fields(monkeypatch):
    from app.services.project_service import ProjectService
    from app.schemas.project import ProjectUpsertRequest
    monkeypatch.setattr(
        "app.services.project_service.validate_owner_pair", lambda *a, **k: None,
    )
    svc = ProjectService(MagicMock())
    with pytest.raises(ValidationError) as exc:
        svc.upsert("p1", ProjectUpsertRequest(name="P", owner="o1"), caller_user_id="u1")
    assert set(exc.value.details["missing"]) == {"startDate", "endDate", "vendorIds"}
