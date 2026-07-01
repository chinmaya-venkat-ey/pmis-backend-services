"""Per-phase 100% headroom guard in the payment-term reconcile.

`_percent_fits_phase` is the rule that decides whether a milestone keeps its
saved percent when it lands in a phase (via rename / reassign / refill) — it
mirrors the per-phase cap the direct term-PATCH enforces, closing the path where
cost-item edits could push a phase over 100%.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from app.services.project_cost_item_service import ProjectCostItemService


def _svc(existing_sum):
    svc = ProjectCostItemService(MagicMock())
    svc.payment_terms = MagicMock()
    svc.payment_terms.sum_percent_for_phase = MagicMock(return_value=Decimal(str(existing_sum)))
    return svc


def test_none_percent_always_fits():
    assert _svc(100)._percent_fits_phase("p", "A", None) is True


def test_fits_within_headroom():
    assert _svc(30)._percent_fits_phase("p", "A", Decimal("70")) is True   # 30 + 70 = 100
    assert _svc(0)._percent_fits_phase("p", "A", Decimal("100")) is True


def test_rejected_when_over_headroom():
    # refill race: phase already at 100, a restored 60% no longer fits.
    assert _svc(100)._percent_fits_phase("p", "A", Decimal("60")) is False
    # reassign into a partly-full phase that would exceed 100.
    assert _svc(60)._percent_fits_phase("p", "A", Decimal("50")) is False
