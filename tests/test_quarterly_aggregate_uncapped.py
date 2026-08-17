"""quarterly-aggregate.total_ld_percent_uncapped must be the RFP §5.28.1.d.f
"Sum of %LD applicable to all the SLs" — ONE %LD per SLA (its worst across its
per-mapping rows), NOT the raw per-mapping sum which double-counts an SLA mapped
to several activities. It shares the settlement's _collapse_ld_by_sla so the
audit total matches sum_ld_percent in the money math.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.quarterly_settlement_service import _collapse_ld_by_sla


def _row(sla_id, ld_percent):
    return SimpleNamespace(sla_id=sla_id, ld_percent=Decimal(str(ld_percent)))


def test_collapses_per_sla_then_sums_matches_settlement():
    # d1a547ef Y1-Q2 shape: three breaching SLAs, each mapped to 2-3 activities.
    # Per-mapping raw sum = 4+3+4+3+2+1 = 17 (the OLD, wrong uncapped total).
    # Per-SLA collapse (max each) = 4 + 4 + 2 = 10 (the RFP figure, = sum_ld).
    rows = [
        _row("SLA005", 4), _row("SLA005", 3), _row("SLA005", 0),
        _row("SLA006", 4), _row("SLA006", 3),
        _row("SLA008", 2), _row("SLA008", 1),
        _row("SLA007", 0), _row("SLA009", 0),
    ]
    collapsed = _collapse_ld_by_sla(rows)
    assert collapsed == {
        "SLA005": Decimal("4"), "SLA006": Decimal("4"),
        "SLA008": Decimal("2"), "SLA007": Decimal("0"), "SLA009": Decimal("0"),
    }
    uncapped = sum(collapsed.values(), Decimal("0"))
    assert uncapped == Decimal("10")           # not the per-mapping 17


def test_single_mapping_per_sla_is_unchanged():
    rows = [_row("A", 4), _row("B", 2)]
    assert sum(_collapse_ld_by_sla(rows).values(), Decimal("0")) == Decimal("6")


def test_empty_is_zero():
    assert sum(_collapse_ld_by_sla([]).values(), Decimal("0")) == Decimal("0")
