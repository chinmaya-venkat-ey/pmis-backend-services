"""PA = F (activity plan) × attendance-ratio from leave (Σ actual ÷ Σ planned),
clamped to [0,1]. Leave is a different resource set than the plan, so it's used
only as an attendance FACTOR against F — never summed as an absolute cost — so PA
stays ≤ F and reconciles with finance."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.schemas.npqp import NpqpResourceCost
from app.services.npqp_service import NpqpService
from app.utilities.quarter import quarter_of

_ANCHOR = date(2025, 1, 1)


def _svc(f_total, plan_rows, month_cost_fn):
    svc = NpqpService.__new__(NpqpService)   # skip __init__ (no DB/leave client)
    svc.db = None
    svc.leave_client = None
    svc._compute_planned_f = lambda pid, qk: (f_total, plan_rows)
    svc._fetch_month_cost = month_cost_fn
    svc._qgr_for = lambda pid, qend: Decimal("0")
    return svc


def _plan_row():
    return NpqpResourceCost(
        resource_id="", employee_name="PM", year=2026, month=4,
        monthly_rate=Decimal("1000"), cost=Decimal("1000"),
    )


def _leave(cost, rate):
    def fn(pid, y, m, bearer_token=None):
        row = NpqpResourceCost(
            resource_id="r", employee_name="X", year=y, month=m,
            monthly_rate=(None if rate is None else Decimal(str(rate))),
            cost=Decimal(str(cost)),
        )
        return (Decimal(str(cost)), [row])
    return fn


_QK = quarter_of(date(2026, 4, 15), _ANCHOR)


def test_pa_is_f_times_attendance_ratio():
    svc = _svc(Decimal("1000"), [_plan_row()], _leave(90, 100))   # ratio 0.9
    r = svc.compute("p", _QK)
    assert r.f_amount == Decimal("1000")
    assert r.pa_amount == Decimal("900.00")     # 1000 × 0.9 — NOT the leave sum (270)
    assert r.status == "ok"
    assert r.pa_amount <= r.f_amount


def test_pa_clamped_to_f_when_actual_exceeds_planned():
    svc = _svc(Decimal("1000"), [_plan_row()], _leave(120, 100))  # ratio 1.2 → clamp 1.0
    assert svc.compute("p", _QK).pa_amount == Decimal("1000.00")


def test_pa_full_when_leave_has_no_rate_data():
    svc = _svc(Decimal("1000"), [_plan_row()], _leave(0, None))
    assert svc.compute("p", _QK).pa_amount == Decimal("1000.00")   # assume full attendance


def test_pa_zero_and_blocked_when_leave_unavailable():
    svc = _svc(Decimal("1000"), [_plan_row()],
               lambda pid, y, m, bearer_token=None: (None, []))
    r = svc.compute("p", _QK)
    assert r.pa_amount == Decimal("0")
    assert r.status == "leave_mgmt_unavailable"
