"""MilestoneService._autogenerate_quarter_activities tiles a resource-based
milestone into one activity per anchored quarter (named Q1, Q2 …), and is an
idempotent no-op when the milestone is not resource-based, is undated, or
already has activities — so SLA-mapped rows are never regenerated."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.milestone_service import MilestoneService

IST = timezone(timedelta(hours=5, minutes=30))


class _FakeActivityRepo:
    def __init__(self, existing=None):
        self._existing = existing or {}
        self.created = []

    def list_by_milestone_ids(self, ids):
        return {k: v for k, v in self._existing.items() if k in ids}

    def next_position_for_milestone(self, milestone_id):
        return 1

    def create(self, **kwargs):
        row = SimpleNamespace(id=f"a{len(self.created) + 1}", **kwargs)
        self.created.append(row)
        return row


class _FakeAudit:
    def __init__(self):
        self.writes = []

    def write(self, **kwargs):
        self.writes.append(kwargs)


def _svc(existing=None):
    svc = MilestoneService.__new__(MilestoneService)  # skip DB wiring
    svc.activities = _FakeActivityRepo(existing)
    svc.audit = _FakeAudit()
    return svc


def _ms(**overrides):
    base = dict(
        id="m1", project_id="p1", is_resource_based=True,
        start_date=datetime(2026, 1, 7, tzinfo=IST),
        end_date=datetime(2026, 8, 8, tzinfo=IST),
        category="original", ccn_value=0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_tiles_into_one_activity_per_quarter():
    svc = _svc()
    created = svc._autogenerate_quarter_activities(_ms(), caller_user_id="u1")

    assert [a.name for a in created] == ["Q1", "Q2", "Q3"]
    assert [a.position for a in created] == [1, 2, 3]
    # Windows anchored on the milestone start, last clamped to the end.
    assert [(a.start_date.date(), a.end_date.date()) for a in created] == [
        (datetime(2026, 1, 7).date(), datetime(2026, 4, 6).date()),
        (datetime(2026, 4, 7).date(), datetime(2026, 7, 6).date()),
        (datetime(2026, 7, 7).date(), datetime(2026, 8, 8).date()),
    ]
    # No resource allocations are seeded — the user fills those in later.
    assert all(a.vendor_id is None for a in created)
    assert all(a.status == "not_completed" for a in created)
    assert all(a.milestone_id == "m1" and a.project_id == "p1" for a in created)
    assert len(svc.audit.writes) == 3


def test_noop_when_not_resource_based():
    svc = _svc()
    assert svc._autogenerate_quarter_activities(
        _ms(is_resource_based=False), caller_user_id="u1") == []
    assert svc.activities.created == []


def test_noop_when_missing_date():
    svc = _svc()
    assert svc._autogenerate_quarter_activities(
        _ms(end_date=None), caller_user_id="u1") == []
    assert svc.activities.created == []


def test_idempotent_when_activities_exist():
    svc = _svc(existing={"m1": [SimpleNamespace(id="pre")]})
    assert svc._autogenerate_quarter_activities(_ms(), caller_user_id="u1") == []
    assert svc.activities.created == []
