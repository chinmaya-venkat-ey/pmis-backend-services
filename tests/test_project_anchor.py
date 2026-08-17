"""project_anchor is the SLA quarter anchor: the earliest resource-based
milestone start (the resource-phase start), falling back to the project's own
start when there is no resource-based milestone, and None when undated."""
from __future__ import annotations

from datetime import date, datetime, timezone

from app.utilities.project_anchor import project_anchor


class _Result:
    def __init__(self, scalar=None, first=None):
        self._scalar, self._first = scalar, first

    def scalar(self):
        return self._scalar

    def first(self):
        return self._first


class _FakeDb:
    """Returns the RB-milestone MIN(start_date) for the milestones query and the
    project's start_date for the projects query."""
    def __init__(self, rb_start=None, proj_start=None):
        self.rb_start, self.proj_start = rb_start, proj_start

    def execute(self, stmt, params=None):
        if "milestones" in str(stmt).lower():
            return _Result(scalar=self.rb_start)
        return _Result(first=(self.proj_start,) if self.proj_start is not None else None)


def test_anchor_is_earliest_resource_milestone_start():
    db = _FakeDb(rb_start=date(2026, 1, 7), proj_start=date(2024, 10, 9))
    assert project_anchor(db, "p") == date(2026, 1, 7)   # phase start, NOT project start


def test_anchor_falls_back_to_project_start_when_no_rb_milestone():
    db = _FakeDb(rb_start=None, proj_start=date(2024, 10, 9))
    assert project_anchor(db, "p") == date(2024, 10, 9)


def test_anchor_none_when_undated():
    assert project_anchor(_FakeDb(rb_start=None, proj_start=None), "p") is None


def test_anchor_none_for_missing_project_id():
    assert project_anchor(_FakeDb(), None) is None


def test_rb_milestone_datetime_normalised_to_ist_date():
    # 2026-01-06 18:30 UTC == 2026-01-07 00:00 IST → the IST day.
    db = _FakeDb(rb_start=datetime(2026, 1, 6, 18, 30, tzinfo=timezone.utc))
    assert project_anchor(db, "p") == date(2026, 1, 7)
