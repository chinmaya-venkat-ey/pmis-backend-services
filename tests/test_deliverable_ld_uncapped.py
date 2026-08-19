"""Track A (deliverable, RFP §5.28.2) LD is UNCAPPED; only Track B (quarterly,
§5.28.1) is clamped at ``quarterly_ld_cap_pct``. Regression for the bug where
``_per_unit_time`` capped BOTH rules identically at 10%."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.sla_evaluator.base import EvaluatedResult
from app.services.sla_evaluator.fixed_escalation import FixedEscalationEvaluator

_EV = FixedEscalationEvaluator()


def _ctx(sla_ref, rules):
    return SimpleNamespace(
        sla=SimpleNamespace(sla_ref=sla_ref, contract_type="PMU"),
        contract_ld_rules=rules,
    )


def _rate_pct(sla_ref, rules, units, rule):
    res = _EV._per_unit_time(
        _ctx(sla_ref, rules), EvaluatedResult(), "delay",
        Decimal(str(units)), rule,
    )
    assert res.breaches, "expected a breach detail"
    return res.breaches[0].rate_percent


def test_deliverable_ld_not_capped_above_10():
    # 2%/week × 8 weeks = 16% — Track A has NO quarterly cap → stays 16%.
    pct = _rate_pct(
        "PMU-SLA001",
        {"sla_001_rate_pct_per_week": Decimal("2"), "quarterly_ld_cap_pct": Decimal("10")},
        8, "PER_UNIT_TIME_DELIVERABLE",
    )
    assert pct == Decimal("16")


def test_quarterly_ld_still_capped_at_10():
    # 1%/day × 15 days = 15% — Track B IS capped at quarterly_ld_cap_pct → 10%.
    pct = _rate_pct(
        "PMU-SLA003",
        {"sla_003_rate_pct_per_day": Decimal("1"), "quarterly_ld_cap_pct": Decimal("10")},
        15, "PER_UNIT_TIME_QUARTERLY",
    )
    assert pct == Decimal("10")


def test_quarterly_below_cap_is_uncapped():
    pct = _rate_pct(
        "PMU-SLA003",
        {"sla_003_rate_pct_per_day": Decimal("1"), "quarterly_ld_cap_pct": Decimal("10")},
        8, "PER_UNIT_TIME_QUARTERLY",
    )
    assert pct == Decimal("8")


def test_deliverable_with_no_cap_config_surfaces_raw_no_error():
    # cap missing entirely — deliverable still surfaces the raw % and must NOT
    # raise (guards the old `raw_pct > None` TypeError).
    pct = _rate_pct(
        "PMU-SLA001",
        {"sla_001_rate_pct_per_week": Decimal("3")},
        9, "PER_UNIT_TIME_DELIVERABLE",
    )
    assert pct == Decimal("27")
