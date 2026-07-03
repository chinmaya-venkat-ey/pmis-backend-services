"""Cost-row validation in the unified model.

Fixed, resource and transaction cost lines are all first-class phase lines now:
each needs a phase and at least one milestone (they pay out via their milestone
payment terms). The A1 "resource must attach to a fixed phase" rule and the
percent-preservation reconcile guard have been removed — a milestone's percent
simply resets to null whenever it is moved or re-added.
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


def test_resource_cost_requires_a_milestone(monkeypatch):
    # Resource / transaction are now first-class phase lines — they must carry a
    # phase and >= 1 milestone (no more A1 'must attach to a fixed phase' rule).
    svc = _create_svc(monkeypatch)
    with pytest.raises(ValidationError):
        svc.create("p1", CostItemCreateRequest(
            cost_type_code="resource_cost", phase="A", cost=Decimal("5000"),
            line_label="R", milestone_ids=[]),
            caller_user_id="u", caller_is_admin=True)


def test_resource_cost_requires_a_phase(monkeypatch):
    svc = _create_svc(monkeypatch)
    with pytest.raises(ValidationError):
        svc.create("p1", CostItemCreateRequest(
            cost_type_code="transaction_cost", phase=None,
            per_transaction_cost=Decimal("1000"), planned_transactions=5,
            milestone_ids=["m1"]),
            caller_user_id="u", caller_is_admin=True)
