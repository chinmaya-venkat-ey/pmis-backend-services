"""Unit tests for create-side required-field parity with the UI.

Backend now enforces, on CREATE only, the fields the UI marks mandatory:
  * Activity (non-meeting): ownerDivision, vendorId, priority, concernedDivision
  * Project: startDate, endDate, vendorIds

Behaviour preserved: meeting/governance activities are exempt; the
update/PATCH path is untouched (stays partial); existing optional fields
elsewhere are unaffected.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.core.errors import ValidationError
from app.schemas.activity import ActivityCreateRequest
from app.schemas.project import ProjectCreateRequest
from app.services.activity_service import ActivityService
from app.services.project_service import ProjectService


IST = timezone(timedelta(hours=5, minutes=30))
START = datetime(2026, 5, 1, tzinfo=IST)
END = datetime(2026, 6, 1, tzinfo=IST)


def _activity_payload(**over) -> ActivityCreateRequest:
    base = dict(name="A1", start_date=START, end_date=END)
    base.update(over)
    return ActivityCreateRequest(**base)


def _project_payload(**over) -> ProjectCreateRequest:
    base = dict(name="P1", owner="o1")
    base.update(over)
    return ProjectCreateRequest(**base)


# ---------------------------------------------------------------- Activity ---

def test_activity_required_all_missing_lists_all():
    svc = ActivityService(MagicMock())
    with pytest.raises(ValidationError) as exc:
        svc._assert_activity_create_required(_activity_payload())
    assert set(exc.value.details["missing"]) == {
        "ownerDivision", "vendorId", "priority", "concernedDivision",
    }


def test_activity_required_passes_when_all_present():
    svc = ActivityService(MagicMock())
    svc._assert_activity_create_required(_activity_payload(
        owner_division="d1", vendor_id="v1", priority="P2",
        concerned_divisions=["d2"],
    ))  # must not raise


def test_activity_required_empty_concerned_list_blocks():
    svc = ActivityService(MagicMock())
    with pytest.raises(ValidationError) as exc:
        svc._assert_activity_create_required(_activity_payload(
            owner_division="d1", vendor_id="v1", priority="P2",
            concerned_divisions=[],
        ))
    assert exc.value.details["missing"] == ["concernedDivision"]


def test_activity_required_blank_strings_blocked():
    svc = ActivityService(MagicMock())
    with pytest.raises(ValidationError) as exc:
        svc._assert_activity_create_required(_activity_payload(
            owner_division="   ", vendor_id="v1", priority="P2",
            concerned_divisions=["d2"],
        ))
    assert exc.value.details["missing"] == ["ownerDivision"]


def _activity_svc_for_create(monkeypatch, *, is_meeting: bool) -> ActivityService:
    """ActivityService wired so create() runs in-process without a DB."""
    svc = ActivityService(MagicMock())
    milestone = MagicMock()
    milestone.id = "m1"
    milestone.project_id = "p1"
    milestone.start_date = START
    milestone.is_meeting = is_meeting
    project = MagicMock()
    project.status = "published"
    svc.milestones.get_by_id = MagicMock(return_value=milestone)
    svc.projects.get_by_id = MagicMock(return_value=project)
    svc.repo = MagicMock()
    svc.repo.next_position_for_milestone.return_value = 1
    row = MagicMock()
    row.id = "a1"
    row.project_id = "p1"
    row.milestone_id = "m1"
    row.name = "A1"
    row.category = "original"
    row.status = "not_completed"
    svc.repo.create.return_value = row
    svc.audit = MagicMock()
    svc.comments = MagicMock()
    svc._validate_priority = MagicMock()
    svc._validate_owner_division = MagicMock()
    svc._validate_concerned_divisions = MagicMock()
    svc._resolve_create_category = MagicMock(return_value=("original", 0))
    svc._prepare_meeting_attachments = MagicMock(return_value=[])
    svc._cascade_revert_from_new_child = MagicMock()
    monkeypatch.setattr(
        "app.services.activity_service.assert_milestone_activity_writable",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.activity_service.validate_entity_dates",
        lambda *a, **k: None,
    )
    return svc


def test_meeting_activity_create_skips_required_fields(monkeypatch):
    """Meeting/governance activities create fine without the business fields."""
    svc = _activity_svc_for_create(monkeypatch, is_meeting=True)
    row = svc.create("m1", _activity_payload(), caller_user_id="u1")
    assert row.id == "a1"  # no ValidationError despite missing business fields


def test_non_meeting_activity_create_enforces_required_fields(monkeypatch):
    svc = _activity_svc_for_create(monkeypatch, is_meeting=False)
    with pytest.raises(ValidationError) as exc:
        svc.create("m1", _activity_payload(), caller_user_id="u1")
    assert "ownerDivision" in exc.value.details["missing"]


# ----------------------------------------------------------------- Project ---

def test_project_required_all_missing_lists_all():
    svc = ProjectService(MagicMock())
    with pytest.raises(ValidationError) as exc:
        svc._assert_project_create_required(
            _project_payload(start_date=None, end_date=None, vendor_ids=[]),
        )
    assert set(exc.value.details["missing"]) == {"startDate", "endDate", "vendorIds"}


def test_project_required_passes_when_all_present():
    svc = ProjectService(MagicMock())
    svc._assert_project_create_required(
        _project_payload(start_date=START, end_date=END, vendor_ids=["v1"]),
    )  # must not raise


def test_project_create_enforces_required_after_owner_validation(monkeypatch):
    """create() calls the required gate (right after owner validation)."""
    svc = ProjectService(MagicMock())
    monkeypatch.setattr(
        "app.services.project_service.validate_owner_pair",
        lambda *a, **k: None,
    )
    with pytest.raises(ValidationError) as exc:
        svc.create(
            _project_payload(start_date=None, end_date=None, vendor_ids=[]),
            caller_user_id="u1",
        )
    assert "startDate" in exc.value.details["missing"]
