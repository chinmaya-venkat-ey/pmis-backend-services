"""recurring_cost — the project-level, frequency-scheduled cost type.

A recurring cost carries a total amount + a frequency and NO phase / milestones.
Its amount is distributed across the frequency periods (via cf_pool.build_schedule)
from the milestone-timeline start over the project duration — a payment schedule,
the way carry-forward pools installments.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.errors import ValidationError
from app.schemas.payment import CostItemCreateRequest
from app.services import project_cost_item_service as cim
from app.services.project_cost_item_service import ProjectCostItemService
from app.utilities import cf_pool


# ------------------------------------------------------------ schedule builder

def test_schedule_splits_evenly_and_spans_inclusive():
    # 1.2M yearly across 2026..2029 inclusive → 4 installments of 300k.
    sched = cf_pool.build_schedule(Decimal("1200000"), date(2026, 1, 1), date(2029, 12, 31), "yearly")
    assert len(sched) == 4
    assert [x["amount"] for x in sched] == [Decimal("300000.00")] * 4
    assert sum(x["amount"] for x in sched) == Decimal("1200000.00")


def test_schedule_last_installment_absorbs_rounding():
    sched = cf_pool.build_schedule(Decimal("1000000"), date(2026, 1, 1), date(2028, 12, 31), "yearly")
    assert [x["amount"] for x in sched] == [
        Decimal("333333.33"), Decimal("333333.33"), Decimal("333333.34"),
    ]
    assert sum(x["amount"] for x in sched) == Decimal("1000000.00")


def test_schedule_empty_when_unusable():
    assert cf_pool.build_schedule(Decimal("0"), date(2026, 1, 1), date(2029, 1, 1), "yearly") == []
    assert cf_pool.build_schedule(Decimal("100"), None, date(2029, 1, 1), "yearly") == []
    assert cf_pool.build_schedule(Decimal("100"), date(2026, 1, 1), date(2029, 1, 1), "one_time") == []


# ----------------------------------------------------------- service validation

def _svc(monkeypatch):
    svc = ProjectCostItemService(MagicMock())
    svc._require_project = MagicMock(return_value=SimpleNamespace(id="p1", status="new"))
    monkeypatch.setattr(cim, "assert_payment_writable", lambda *a, **k: None)
    monkeypatch.setattr(cim, "validate_cost_type_code", lambda db, code: code)
    return svc


def test_recurring_requires_a_cost(monkeypatch):
    svc = _svc(monkeypatch)
    with pytest.raises(ValidationError):
        svc.create("p1", CostItemCreateRequest(
            cost_type_code="recurring_cost", cost=None, frequency_code="yearly"),
            caller_user_id="u", caller_is_admin=True)


def test_recurring_requires_a_frequency(monkeypatch):
    svc = _svc(monkeypatch)
    with pytest.raises(ValidationError):
        svc.create("p1", CostItemCreateRequest(
            cost_type_code="recurring_cost", cost=Decimal("1200000"), frequency_code=None),
            caller_user_id="u", caller_is_admin=True)
