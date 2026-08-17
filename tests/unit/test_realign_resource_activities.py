"""MilestoneService.realign_resource_activities snaps existing activities onto
their anchored quarter windows (dates only), clamps out-of-window allocation
deployment dates, preserves ids/positions/allocations, and is idempotent."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import app.services.milestone_service as ms_mod
from app.services.milestone_service import MilestoneService

IST = timezone(timedelta(hours=5, minutes=30))


class _FakeActivityRepo:
    def __init__(self, activities, allocations):
        self._activities = activities            # {milestone_id: [act, ...]}
        self._allocations = allocations          # {activity_id: [alloc, ...]}

    def list_by_milestone_ids(self, ids):
        return {k: v for k, v in self._activities.items() if k in ids}

    def list_planned_resources(self, activity_id):
        return self._allocations.get(activity_id, [])


class _FakeAudit:
    def __init__(self):
        self.writes = []

    def write(self, **kwargs):
        self.writes.append(kwargs)


class _FakeDb:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def _milestone():
    return SimpleNamespace(
        id="m1", project_id="p1", is_resource_based=True,
        start_date=datetime(2026, 1, 7, tzinfo=IST),
        end_date=datetime(2026, 8, 8, tzinfo=IST),
    )


def _svc(activities, allocations, monkeypatch):
    svc = MilestoneService.__new__(MilestoneService)
    svc.db = _FakeDb()
    svc.activities = _FakeActivityRepo(activities, allocations)
    svc.audit = _FakeAudit()
    svc.projects = SimpleNamespace(get_by_id=lambda pid: SimpleNamespace(id=pid))
    monkeypatch.setattr(svc, "get_by_id", lambda mid: _milestone())
    monkeypatch.setattr(ms_mod, "assert_milestone_activity_writable", lambda project: None)
    return svc


def test_snaps_dates_and_clamps_deployment(monkeypatch):
    # Activity mid-Q2 (Apr 7 – Jul 6) window, with a stray start/end.
    act = SimpleNamespace(
        id="a1", name="Q2", position=2, project_id="p1",
        start_date=datetime(2026, 5, 15, tzinfo=IST),
        end_date=datetime(2026, 5, 20, tzinfo=IST),
        updated_by=None,
    )
    alloc_before = SimpleNamespace(designation="Dev", planned_deployment_date=date(2026, 3, 1))
    alloc_inside = SimpleNamespace(designation="QA", planned_deployment_date=date(2026, 5, 1))
    svc = _svc({"m1": [act]}, {"a1": [alloc_before, alloc_inside]}, monkeypatch)

    out = svc.realign_resource_activities("m1", caller_user_id="u1")

    # Snapped to the Apr 7 – Jul 6 quarter; id/position untouched.
    assert act.start_date.date() == date(2026, 4, 7)
    assert act.end_date.date() == date(2026, 7, 6)
    assert act.id == "a1" and act.position == 2
    # Deployment before the window is clamped to the window start; the inside
    # one is left alone.
    assert alloc_before.planned_deployment_date == date(2026, 4, 7)
    assert alloc_inside.planned_deployment_date == date(2026, 5, 1)
    assert svc.db.commits == 1
    assert out["realigned"][0]["allocations_clamped"] == 1
    assert out["realigned"][0]["dates_changed"] is True


def test_idempotent_when_already_aligned(monkeypatch):
    act = SimpleNamespace(
        id="a1", name="Q2", position=2, project_id="p1",
        start_date=datetime(2026, 4, 7, tzinfo=IST),
        end_date=datetime(2026, 7, 6, tzinfo=IST),
        updated_by="prev",
    )
    alloc = SimpleNamespace(designation="Dev", planned_deployment_date=date(2026, 5, 1))
    svc = _svc({"m1": [act]}, {"a1": [alloc]}, monkeypatch)

    out = svc.realign_resource_activities("m1", caller_user_id="u1")

    assert out["realigned"] == []          # nothing moved
    assert svc.audit.writes == []          # no audit noise
    assert alloc.planned_deployment_date == date(2026, 5, 1)
    assert svc.db.commits == 1
