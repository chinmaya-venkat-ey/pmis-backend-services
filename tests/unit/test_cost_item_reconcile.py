"""Per-phase 100% headroom guard in the payment-term reconcile.

`_percent_fits_phase` is the rule that decides whether a milestone keeps its
saved percent when it lands in a phase (via rename / reassign / refill) — it
mirrors the per-phase cap the direct term-PATCH enforces, closing the path where
cost-item edits could push a phase over 100%.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.errors import ValidationError
from app.schemas.payment import CostItemCreateRequest
from app.services import project_cost_item_service as cim
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


def _create_svc(monkeypatch):
    svc = ProjectCostItemService(MagicMock())
    svc._require_project = MagicMock(return_value=SimpleNamespace(id="p1", status="new"))
    monkeypatch.setattr(cim, "assert_payment_writable", lambda *a, **k: None)
    monkeypatch.setattr(cim, "validate_cost_type_code", lambda db, code: code)
    return svc


def test_fixed_cost_row_requires_a_milestone(monkeypatch):
    # A fixed (delivery) row with no milestone is a phase with value but nothing
    # to pay it out — the phantom/stranding case — so it is rejected.
    svc = _create_svc(monkeypatch)
    with pytest.raises(ValidationError):
        svc.create("p1", CostItemCreateRequest(
            cost_type_code="fixed", phase="A", cost=Decimal("100000"), milestone_ids=[]),
            caller_user_id="u", caller_is_admin=True)


def test_resource_cost_needs_an_existing_fixed_phase(monkeypatch):
    # A1: resource/transaction can only attach to a phase that already has fixed cost.
    svc = _create_svc(monkeypatch)
    svc.repo = MagicMock()
    svc.repo.list_all_live = MagicMock(return_value=[])   # no fixed rows anywhere
    with pytest.raises(ValidationError):
        svc.create("p1", CostItemCreateRequest(
            cost_type_code="resource_cost", phase="A", cost=Decimal("5000"), line_label="R"),
            caller_user_id="u", caller_is_admin=True)
