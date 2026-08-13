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


def _ctx(project_id="p1", bearer="jwt", quarter=None) -> ProviderContext:
    return ProviderContext(db=None, mapping=None, sla=None, activity={},
                           project_id=project_id, quarter=quarter or _qk(),
                           bearer_token=bearer)


class _FakeLeaveClient:
    """Stand-in for LeaveManagementClient with canned responses."""
    def __init__(self, availability=None, replacements=None):
        self._availability = availability          # {(year,month): rows} or None
        self._replacements = replacements
        self.availability_calls = []

    def get_availability(self, project_id, year, month, bearer_token=None):
        self.availability_calls.append((project_id, year, month, bearer_token))
        if self._availability is None:
            return None
        return self._availability.get((year, month), [])

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

def test_availability_worst_resource_month():
    avail = {
        (2026, 2): [{"resourceId": "r1", "businessDaysPresent": 21, "hoursLogged": 176},
                    {"resourceId": "r2", "businessDaysPresent": 20, "hoursLogged": 168}],
        (2026, 3): [{"resourceId": "r1", "businessDaysPresent": 14, "hoursLogged": 120},  # worst BD
                    {"resourceId": "r2", "businessDaysPresent": 22, "hoursLogged": 180}],
        (2026, 4): [{"resourceId": "r1", "businessDaysPresent": 19, "hoursLogged": 150}],
        (2026, 5): [{"resourceId": "r1", "businessDaysPresent": 18, "hoursLogged": 144}],
    }
    p = LeaveAvailabilityProvider(client=_FakeLeaveClient(availability=avail))
    val = p.provide(_ctx())
    assert val == {"resource_business_days": Decimal("14"),
                   "resource_logged_hours": Decimal("120")}


def test_availability_all_meeting_target_returns_best_worst():
    avail = {(2026, 2): [{"resourceId": "r1", "businessDaysPresent": 22, "hoursLogged": 180}],
             (2026, 3): [{"resourceId": "r1", "businessDaysPresent": 21, "hoursLogged": 176}],
             (2026, 4): [{"resourceId": "r1", "businessDaysPresent": 20, "hoursLogged": 170}],
             (2026, 5): [{"resourceId": "r1", "businessDaysPresent": 23, "hoursLogged": 184}]}
    p = LeaveAvailabilityProvider(client=_FakeLeaveClient(availability=avail))
    val = p.provide(_ctx())
    assert val == {"resource_business_days": Decimal("20"),
                   "resource_logged_hours": Decimal("170")}  # worst month still >= target


def test_availability_inert_without_bearer_or_project():
    p = LeaveAvailabilityProvider(client=_FakeLeaveClient(availability={}))
    assert p.provide(_ctx(bearer=None)) is None
    assert p.provide(_ctx(project_id=None)) is None


def test_availability_inert_when_feed_unavailable():
    # client returns None (endpoint unbuilt / base-url unset) → provider inert
    p = LeaveAvailabilityProvider(client=_FakeLeaveClient(availability=None))
    assert p.provide(_ctx()) is None


def test_availability_none_when_no_rows():
    p = LeaveAvailabilityProvider(client=_FakeLeaveClient(availability={(2026, 2): []}))
    assert p.provide(_ctx()) is None


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
