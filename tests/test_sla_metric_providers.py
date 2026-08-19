"""SLA auto-evaluation providers — registry resolution, response mapping, and
the worst-(resource,month) reduction. Pure unit tests (fake feed client, no DB)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.sla_metric_providers import ProviderContext, resolve_provider
from app.services.sla_metric_providers.base import months_of_quarter
from app.services.sla_metric_providers.leave_availability_provider import (
    LeaveAvailabilityProvider,
)
from app.services.sla_metric_providers.leave_replacement_provider import (
    LeaveReplacementProvider,
)
from app.utilities.quarter import QuarterKey


# ---- fixtures -------------------------------------------------------------

def _qk() -> QuarterKey:
    return QuarterKey(fiscal_year=1, quarter=2,
                      quarter_start=date(2026, 2, 10), quarter_end=date(2026, 5, 9),
                      anchored=True)


class _Mapping:
    """Minimal stand-in for SlaActivityMapping — the provider only reads
    ``activity_id`` off it."""
    def __init__(self, activity_id="a1"):
        self.activity_id = activity_id


_UNSET = object()


def _ctx(project_id="p1", bearer="jwt", quarter=None, mapping=_UNSET) -> ProviderContext:
    return ProviderContext(db=None,
                           mapping=_Mapping() if mapping is _UNSET else mapping,
                           sla=None, activity={},
                           project_id=project_id, quarter=quarter or _qk(),
                           bearer_token=bearer)


def _cycle(fromDate, resourceCount, totalBusinessDays, totalWorkingHours,
           totalPresentDays=None):
    """One MonthlyAvailability entry (only the fields the provider reads)."""
    return {"fromDate": fromDate, "resourceCount": resourceCount,
            "totalBusinessDays": totalBusinessDays,
            "totalPresentDays": totalPresentDays if totalPresentDays is not None
            else totalBusinessDays,
            "totalWorkingHours": totalWorkingHours}


def _report(*cycles):
    return {"projectId": "p1", "activityId": "a1", "months": list(cycles)}


class _FakeLeaveClient:
    """Stand-in for LeaveManagementClient with canned responses."""
    def __init__(self, report=None, replacements=None):
        self._report = report                      # ActivityAvailabilityReport or None
        self._replacements = replacements
        self.availability_calls = []

    def get_activity_availability(self, project_id, activity_id, bearer_token=None):
        self.availability_calls.append((project_id, activity_id, bearer_token))
        return self._report

    def get_replacements(self, project_id, from_date, to_date, bearer_token=None):
        return self._replacements


# ---- months_of_quarter ----------------------------------------------------

def test_months_of_quarter_covers_touched_months():
    # anchored quarter 2026-02-10..2026-05-09 touches Feb, Mar, Apr, May
    assert months_of_quarter(_qk()) == [(2026, 2), (2026, 3), (2026, 4), (2026, 5)]


def test_months_of_quarter_year_wrap():
    qk = QuarterKey(1, 1, date(2025, 11, 10), date(2026, 2, 9), True)
    assert months_of_quarter(qk) == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]


# ---- registry -------------------------------------------------------------

def test_registry_resolves_availability_for_sla007_metrics():
    p = resolve_provider({"resource_business_days", "resource_logged_hours"})
    assert isinstance(p, LeaveAvailabilityProvider)


def test_registry_resolves_replacement_for_sla005_metric():
    p = resolve_provider({"resource_replacements_count"})
    assert isinstance(p, LeaveReplacementProvider)


def test_registry_no_match_for_unrelated_metric():
    # BSP-SLA007 measures operator_error_pct — must NOT get the availability provider.
    assert resolve_provider({"operator_error_pct"}) is None
    assert resolve_provider(set()) is None


def test_registry_requires_all_metrics_present():
    # only one of SLA007's two metrics present → availability provider does NOT apply
    assert not isinstance(resolve_provider({"resource_business_days"}),
                          LeaveAvailabilityProvider)


# ---- availability provider (SLA007) --------------------------------------

def test_availability_team_average_worst_cycle():
    # quarter window 2026-02-10..2026-05-09; team average = cycle total ÷ resourceCount.
    report = _report(
        _cycle("2026-02-10", resourceCount=2, totalBusinessDays=42, totalWorkingHours=352),  # avg 21 / 176
        _cycle("2026-03-10", resourceCount=2, totalBusinessDays=30, totalWorkingHours=260),  # avg 15 / 130 (worst)
        _cycle("2026-04-10", resourceCount=1, totalBusinessDays=19, totalWorkingHours=150),  # avg 19 / 150
    )
    p = LeaveAvailabilityProvider(client=_FakeLeaveClient(report=report))
    val = p.provide(_ctx())
    assert val == {"resource_business_days": Decimal("15"),
                   "resource_logged_hours": Decimal("130")}


def test_availability_all_meeting_target_returns_worst_cycle():
    report = _report(
        _cycle("2026-02-10", resourceCount=1, totalBusinessDays=22, totalWorkingHours=180),  # 22 / 180
        _cycle("2026-03-10", resourceCount=2, totalBusinessDays=40, totalWorkingHours=340),  # 20 / 170 (worst)
        _cycle("2026-04-10", resourceCount=1, totalBusinessDays=21, totalWorkingHours=176),  # 21 / 176
    )
    p = LeaveAvailabilityProvider(client=_FakeLeaveClient(report=report))
    val = p.provide(_ctx())
    assert val == {"resource_business_days": Decimal("20"),
                   "resource_logged_hours": Decimal("170")}  # worst cycle still >= target


def test_availability_ignores_cycles_outside_the_quarter():
    # a wretched cycle before the quarter window must not drag the observation down.
    report = _report(
        _cycle("2025-12-10", resourceCount=1, totalBusinessDays=3, totalWorkingHours=20),   # out of window
        _cycle("2026-03-10", resourceCount=2, totalBusinessDays=40, totalWorkingHours=340),  # 20 / 170
    )
    p = LeaveAvailabilityProvider(client=_FakeLeaveClient(report=report))
    val = p.provide(_ctx())
    assert val == {"resource_business_days": Decimal("20"),
                   "resource_logged_hours": Decimal("170")}


def test_availability_inert_without_bearer_project_or_activity():
    good = _report(_cycle("2026-03-10", resourceCount=1, totalBusinessDays=20, totalWorkingHours=170))
    p = LeaveAvailabilityProvider(client=_FakeLeaveClient(report=good))
    assert p.provide(_ctx(bearer=None)) is None
    assert p.provide(_ctx(project_id=None)) is None
    assert p.provide(_ctx(mapping=None)) is None                 # no mapping → no activity id
    assert p.provide(_ctx(mapping=_Mapping(activity_id=None))) is None


def test_availability_inert_when_feed_unavailable():
    # client returns None (activity unknown / base-url unset / unreachable) → provider inert
    p = LeaveAvailabilityProvider(client=_FakeLeaveClient(report=None))
    assert p.provide(_ctx()) is None


def test_availability_none_when_no_cycles():
    # empty months, and a resourceCount==0 cycle, both yield no real figure
    assert LeaveAvailabilityProvider(client=_FakeLeaveClient(report=_report())).provide(_ctx()) is None
    zero = _report(_cycle("2026-03-10", resourceCount=0, totalBusinessDays=0, totalWorkingHours=0))
    assert LeaveAvailabilityProvider(client=_FakeLeaveClient(report=zero)).provide(_ctx()) is None


# ---- replacement provider (SLA005) ---------------------------------------

def test_replacement_count_from_dict():
    p = LeaveReplacementProvider(client=_FakeLeaveClient(replacements={"count": 3}))
    assert p.provide(_ctx()) == 3


def test_replacement_count_from_list():
    p = LeaveReplacementProvider(client=_FakeLeaveClient(replacements=[{}, {}]))
    assert p.provide(_ctx()) == 2


def test_replacement_inert_cases():
    assert LeaveReplacementProvider(client=_FakeLeaveClient(replacements=None)).provide(_ctx()) is None
    assert LeaveReplacementProvider(client=_FakeLeaveClient(replacements={"count": 1})).provide(_ctx(bearer=None)) is None
