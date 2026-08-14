"""_snapshot_resource_rows resolves the contract-year rate PER ROW from that
row's planned_deployment_date (anchored on project start) — so a later-deploying
allocation is priced at its deployment year's card, not the project-start year."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services import activity_service


class _Item:
    def __init__(self, designation, quantity, duration, planned_deployment_date):
        self.designation = designation
        self.quantity = quantity
        self.duration = duration
        self.planned_deployment_date = planned_deployment_date


class _Proj:
    id = "p1"
    start_date = date(2025, 1, 1)  # project anchor → Year-1 starts here


def _patch_cards(monkeypatch, card):
    def _fake_fetch(self, project_id, vendor_id, bearer):
        return [{"role": "Program Manager", "rateCardByYear": card}]
    monkeypatch.setattr(
        "app.clients.leave_designation_rates_client.LeaveDesignationRatesClient.fetch_designation_rates",
        _fake_fetch,
    )


def test_rate_uses_deployment_year_not_project_start_year(monkeypatch):
    _patch_cards(monkeypatch, {"Year-1": "100", "Year-2": "200"})
    items = [
        _Item("Program Manager", 1, "2", date(2025, 3, 1)),   # deploys Year-1
        _Item("Program Manager", 1, "2", date(2026, 3, 1)),   # deploys Year-2 (>12mo from anchor)
    ]
    # activity_start is Year-1; pre-fix BOTH rows would have used Year-1 (=100).
    rows = activity_service._snapshot_resource_rows(
        _Proj(), date(2025, 2, 1), None, items, "jwt",
    )
    assert rows[0]["monthly_rate"] == Decimal("100")          # Year-1 row → Year-1 rate
    assert rows[0]["computed_cost"] == Decimal("200.00")      # 100 × 1 × 2
    assert rows[1]["monthly_rate"] == Decimal("200")          # Year-2 deploy → Year-2 rate (the fix)
    assert rows[1]["computed_cost"] == Decimal("400.00")      # 200 × 1 × 2


def test_falls_back_to_activity_start_when_no_deploy_date(monkeypatch):
    _patch_cards(monkeypatch, {"Year-1": "100", "Year-2": "200"})
    items = [_Item("Program Manager", 1, "1", None)]          # no deployment date
    rows = activity_service._snapshot_resource_rows(
        _Proj(), date(2026, 3, 1), None, items, "jwt",        # activity_start in Year-2
    )
    assert rows[0]["monthly_rate"] == Decimal("200")          # falls back to activity_start's year
