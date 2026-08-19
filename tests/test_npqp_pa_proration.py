"""PA (hard switch) — F prorated per ACTIVITY by the BINDING (worst) of the
completeness fractions SLA007 configures: HOURS (Σ working-hours ÷ (planned-
resource-months × hours-target)) and/or BUSINESS-DAYS (Σ days ÷ (… × days-
target)). Attendance is activity-linked (stubbed here via ``_activity_delivered``);
PA = Σ F_activity × fraction ≤ F. Missing attendance for an in-quarter activity
BLOCKS the quarter rather than under-paying."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.schemas.npqp import NpqpResourceCost
from app.services.npqp_service import NpqpService
from app.utilities.quarter import quarter_of

_ANCHOR = date(2025, 1, 1)
_QK = quarter_of(date(2026, 4, 15), _ANCHOR)

_PLAN_ROW = NpqpResourceCost(resource_id="", employee_name="PM", year=2026,
                             month=4, monthly_rate=Decimal("1000"), cost=Decimal("1000"))


def _act(f, months):
    return {"f": Decimal(str(f)), "months": Decimal(str(months))}


def _delivered(mapping):
    """mapping: {activity_id: (hours, days) | None}. None → attendance unreadable."""
    def fn(pid, aid, qk, bearer_token=None):
        v = mapping.get(aid)
        if v is None:
            return None
        return (Decimal(str(v[0])), Decimal(str(v[1])))
    return fn


def _svc(by_activity, delivered_fn, targets=(Decimal("144"), Decimal("16")),
         f_total=None, planned_rows=None):
    svc = NpqpService.__new__(NpqpService)   # skip __init__ (no DB / leave client)
    svc.db = None
    svc.leave_client = None
    if f_total is None:
        f_total = sum((a["f"] for a in by_activity.values()), Decimal("0"))
    if planned_rows is None:
        planned_rows = [_PLAN_ROW] if by_activity else []
    svc._compute_planned_f = lambda pid, qk: (f_total, planned_rows, by_activity)
    svc._resolve_availability_targets = lambda pid: targets
    svc._activity_delivered = delivered_fn
    svc._qgr_for = lambda pid, qend: Decimal("0")
    return svc


def test_pa_full_attendance_meets_both_targets():
    svc = _svc({"a1": _act(1000, 1)}, _delivered({"a1": (144, 16)}))
    r = svc.compute("p", _QK)
    assert r.f_amount == Decimal("1000")
    assert r.pa_amount == Decimal("1000.00")
    assert r.status == "ok"
    assert r.pa_amount <= r.f_amount


def test_pa_hours_bind_below_days():
    # 72h/144 = 0.5 (binds) vs 16d/16 = 1.0
    svc = _svc({"a1": _act(1000, 1)}, _delivered({"a1": (72, 16)}))
    assert svc.compute("p", _QK).pa_amount == Decimal("500.00")


def test_pa_days_bind_below_hours():
    # 144h/144 = 1.0 vs 8d/16 = 0.5 (binds) — the AND catches long-hours / few-days
    svc = _svc({"a1": _act(1000, 1)}, _delivered({"a1": (144, 8)}))
    assert svc.compute("p", _QK).pa_amount == Decimal("500.00")


def test_pa_clamped_to_f_when_over_delivered():
    svc = _svc({"a1": _act(1000, 1)}, _delivered({"a1": (200, 20)}))  # both > target
    assert svc.compute("p", _QK).pa_amount == Decimal("1000.00")


def test_pa_hours_only_target_ignores_days():
    svc = _svc({"a1": _act(1000, 1)}, _delivered({"a1": (72, 8)}),
               targets=(Decimal("144"), None))
    assert svc.compute("p", _QK).pa_amount == Decimal("500.00")   # 72/144


def test_pa_days_only_target_ignores_hours():
    svc = _svc({"a1": _act(1000, 1)}, _delivered({"a1": (999, 4)}),
               targets=(None, Decimal("16")))
    assert svc.compute("p", _QK).pa_amount == Decimal("250.00")   # 4/16


def test_pa_sums_across_activities():
    svc = _svc({"a1": _act(1000, 1), "a2": _act(2000, 1)},
               _delivered({"a1": (144, 16), "a2": (72, 16)}))     # 1.0 and 0.5
    assert svc.compute("p", _QK).pa_amount == Decimal("2000.00")  # 1000 + 1000


def test_pa_multi_month_activity_scales_denominator():
    # 2 resource-months → target scales: 216h/(2×144)=0.75
    svc = _svc({"a1": _act(1000, 2)}, _delivered({"a1": (216, 32)}))
    assert svc.compute("p", _QK).pa_amount == Decimal("750.00")   # 216/288 binds vs 32/32=1.0


def test_pa_zero_cost_activity_needs_no_attendance():
    # a2 has F=0 → skipped before any attendance fetch; only a1 pays
    svc = _svc({"a1": _act(1000, 1), "a2": _act(0, 0)},
               _delivered({"a1": (144, 16)}))       # a2 intentionally absent from map
    r = svc.compute("p", _QK)
    assert r.pa_amount == Decimal("1000.00")
    assert r.status == "ok"


def test_pa_blocks_when_attendance_missing():
    svc = _svc({"a1": _act(1000, 1)}, _delivered({"a1": None}))
    r = svc.compute("p", _QK)
    assert r.pa_amount == Decimal("0.00")
    assert r.status == "attendance_unavailable"


def test_pa_partial_block_blocks_whole_quarter():
    svc = _svc({"a1": _act(1000, 1), "a2": _act(2000, 1)},
               _delivered({"a1": (144, 16), "a2": None}))
    assert svc.compute("p", _QK).status == "attendance_unavailable"


def test_pa_no_resources_when_no_plan():
    svc = _svc({}, _delivered({}), f_total=Decimal("0"), planned_rows=[])
    assert svc.compute("p", _QK).status == "no_resources"
