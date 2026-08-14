"""F (Planned Quarterly Payment) is now computed from the project's per-activity
resource plan (project.activity_planned_resources — the finance source), summing
computed_cost over allocations whose planned_deployment_date falls in the quarter.

These unit-test the row-processing logic with a mocked DB; the actual cross-schema
SQL is verified end-to-end against real data (F reconciles with the finance total
₹2,64,30,002 and is project-anchored per quarter)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.npqp_service import NpqpService
from app.utilities.quarter import quarter_of

_ANCHOR = date(2025, 1, 1)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDb:
    """Returns the given rows for any execute() — stands in for the cross-schema
    activity_planned_resources query."""
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *a, **k):
        return _FakeResult(self._rows)


def _alloc(designation, qty, rate, dur, cost, dep):
    return SimpleNamespace(
        designation=designation, quantity=qty, monthly_rate=rate,
        duration=dur, computed_cost=cost, planned_deployment_date=dep,
    )


def _svc(rows):
    # leave_client is unused by the F path; pass a sentinel so no real client is built.
    return NpqpService(_FakeDb(rows), leave_client=object())


def test_f_sums_computed_cost_snapshot():
    rows = [
        _alloc("Program Manager", 1, Decimal("576000"), Decimal("3"), Decimal("1728000"), date(2026, 4, 10)),
        _alloc("Developer", 2, Decimal("384000"), Decimal("3"), Decimal("2304000"), date(2026, 5, 1)),
    ]
    f, per = _svc(rows)._compute_planned_f("p", quarter_of(date(2026, 4, 15), _ANCHOR))
    assert f == Decimal("4032000")                      # 1,728,000 + 2,304,000
    assert len(per) == 2
    assert per[0].employee_name == "Program Manager"    # designation surfaces as the label
    assert per[0].cost == Decimal("1728000")
    assert (per[0].year, per[0].month) == (2026, 4)     # from planned_deployment_date
    assert per[0].resource_id == ""                     # planned = by designation, no named resource


def test_f_falls_back_to_product_when_snapshot_null():
    rows = [_alloc("PM", 2, Decimal("100000"), Decimal("3"), None, date(2026, 4, 10))]
    f, per = _svc(rows)._compute_planned_f("p", quarter_of(date(2026, 4, 15), _ANCHOR))
    assert f == Decimal("600000")                       # 100000 × 2 × 3
    assert per[0].cost == Decimal("600000")


def test_f_zero_when_no_allocations_in_quarter():
    f, per = _svc([])._compute_planned_f("p", quarter_of(date(2026, 7, 15), _ANCHOR))
    assert f == Decimal("0")
    assert per == []
