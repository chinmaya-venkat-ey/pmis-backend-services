"""severity_from_ld_pct is the single source of truth for the LD%→severity
reverse bucket — previously duplicated byte-for-byte in the evaluator and the
compliance rollup."""
from __future__ import annotations

from decimal import Decimal

from app.services.ld_bands import severity_from_ld_pct
from app.services.sla_compliance_service import _severity_from_ld_pct as compliance_copy
from app.services.sla_evaluator.service import _severity_from_ld_pct as evaluator_copy


def test_thresholds():
    assert severity_from_ld_pct(Decimal("-1")) == 0
    assert severity_from_ld_pct(Decimal("0")) == 0
    assert severity_from_ld_pct(Decimal("0.5")) == 1
    assert severity_from_ld_pct(Decimal("1")) == 1
    assert severity_from_ld_pct(Decimal("2")) == 2
    assert severity_from_ld_pct(Decimal("5")) == 3
    assert severity_from_ld_pct(Decimal("5.01")) == 4
    assert severity_from_ld_pct(Decimal("10")) == 4


def test_both_call_sites_use_the_one_shared_helper():
    assert compliance_copy is severity_from_ld_pct
    assert evaluator_copy is severity_from_ld_pct
