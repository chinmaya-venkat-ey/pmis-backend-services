"""project_phase_end is the resource-phase END: the latest resource-based
milestone end, falling back to the project's own end when there is none, and
None when undated. Bounds the valid settlement-quarter span with project_anchor."""
from __future__ import annotations

from datetime import date, datetime, timezone

from app.utilities.project_anchor import project_phase_end


class _Result:
    def __init__(self, scalar=None, first=None):
        self._scalar, self._first = scalar, first

    def scalar(self):
        return self._scalar

    def first(self):
        return self._first


class _FakeDb:
    """Returns MAX(end_date) of RB milestones for the milestones query, and the
    project's end_date for the projects query."""
    def __init__(self, rb_end=None, proj_end=None):
        self.rb_end, self.proj_end = rb_end, proj_end

    def execute(self, stmt, params=None):
        if "milestones" in str(stmt).lower():
            return _Result(scalar=self.rb_end)
        return _Result(first=(self.proj_end,) if self.proj_end is not None else None)


def test_phase_end_is_latest_rb_milestone_end():
    db = _FakeDb(rb_end=date(2026, 8, 8), proj_end=date(2027, 1, 1))
    assert project_phase_end(db, "p") == date(2026, 8, 8)   # RB end, NOT project end


def test_phase_end_falls_back_to_project_end_when_no_rb_milestone():
    assert project_phase_end(_FakeDb(rb_end=None, proj_end=date(2027, 1, 1)), "p") == date(2027, 1, 1)


def test_phase_end_none_when_undated():
    assert project_phase_end(_FakeDb(rb_end=None, proj_end=None), "p") is None


def test_phase_end_none_for_missing_project_id():
    assert project_phase_end(_FakeDb(), None) is None


def test_rb_end_datetime_normalised_to_ist_date():
    # 2026-08-08 18:30 UTC == 2026-08-09 00:00 IST -> the IST day.
    db = _FakeDb(rb_end=datetime(2026, 8, 8, 18, 30, tzinfo=timezone.utc))
    assert project_phase_end(db, "p") == date(2026, 8, 9)
