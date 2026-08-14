"""Per-SLA LD% collapse: an SLA mapped to N activities must contribute ONE LD%
per quarter (the worst across its mappings), not a per-mapping SUM.

RFP §5.28.1 scores each SLA once (Sev4 → ≤4%); Phase B writes one aggregate row
per (sla × activity), so summing them raw over-counts. Reconstructs the live
'Project For Attendance Policy' Q3 shape: each SLA on 5 activities, some
breaching."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.quarterly_settlement_service import _collapse_ld_by_sla


def _agg(sla_id, pct):
    return SimpleNamespace(sla_id=sla_id, ld_percent=pct)


def test_collapse_takes_max_per_sla_not_sum():
    # d1a547ef Q3: 5 SLAs × 5 activities. SLA005/006 have 2 breaching (4% each),
    # SLA008 has 2 breaching (2% each), SLA007/009 none.
    aggs = (
        [_agg("SLA005", 4), _agg("SLA005", 4)] + [_agg("SLA005", 0)] * 3
        + [_agg("SLA006", 4), _agg("SLA006", 4)] + [_agg("SLA006", 0)] * 3
        + [_agg("SLA007", 0)] * 5
        + [_agg("SLA008", 2), _agg("SLA008", 2)] + [_agg("SLA008", 0)] * 3
        + [_agg("SLA009", 0)] * 5
    )
    collapsed = _collapse_ld_by_sla(aggs)
    # one worst LD% per SLA
    assert collapsed == {
        "SLA005": Decimal("4"), "SLA006": Decimal("4"),
        "SLA007": Decimal("0"), "SLA008": Decimal("2"), "SLA009": Decimal("0"),
    }
    # quarter sum = 4+4+0+2+0 = 10 (the cap), NOT the raw per-mapping sum of 20.
    assert sum(collapsed.values(), Decimal("0")) == Decimal("10")
    raw_per_mapping = sum((Decimal(str(a.ld_percent)) for a in aggs), Decimal("0"))
    assert raw_per_mapping == Decimal("20")


def test_collapse_ignores_null_ld_percent():
    aggs = [_agg("A", None), _agg("A", 3), _agg("B", None)]
    # A resolves to its non-null max; B (all null) drops out entirely.
    assert _collapse_ld_by_sla(aggs) == {"A": Decimal("3")}


def test_collapse_sums_distinct_slas():
    aggs = [_agg("A", 4), _agg("B", 3), _agg("C", 1)]
    assert sum(_collapse_ld_by_sla(aggs).values(), Decimal("0")) == Decimal("8")


def test_collapse_empty():
    assert _collapse_ld_by_sla([]) == {}
