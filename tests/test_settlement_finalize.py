"""finalize (pre-billing lock), clear_override (revert to computed), the override
guards (blank reason / finalized / invoiced), and the SettlementItem
manuallyOverridden / finalized flags. Pure unit tests with a fake repo."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.errors import NotFoundError, ValidationError
from app.schemas.sla_settlement import SettlementItem
from app.services.quarterly_settlement_service import QuarterlySettlementService

_QK = SimpleNamespace(label=lambda: "Y1-Q1")


def _row(status, override_reason=None):
    return SimpleNamespace(
        status=status, override_reason=override_reason, contract_type="PMU",
        f_amount=Decimal("100"), qgr_amount=Decimal("0"), npqp=Decimal("100"),
        ld_amount=Decimal("5"), pa_amount=Decimal("100"), aqp_amount=Decimal("95"),
        sum_ld_percent=Decimal("5"), capped_ld_percent=Decimal("5"),
        source_aggregate_ids=[], consequence_flags={},
    )


class _Repo:
    def __init__(self, row):
        self._row = row
        self.upserted = None

    def get(self, *, project_id, qk):
        return self._row

    def upsert(self, **kw):
        self.upserted = kw
        return SimpleNamespace(**kw)


def _svc(row):
    svc = QuarterlySettlementService.__new__(QuarterlySettlementService)
    svc.repo = _Repo(row)
    return svc


# ---- finalize ------------------------------------------------------------

def test_finalize_locks_auto_closed():
    svc = _svc(_row("auto_closed"))
    out = svc.finalize("p", _QK, finalized_by="u1")
    assert out.status == "finalized"
    assert svc.repo.upserted["status"] == "finalized"


def test_finalize_idempotent():
    svc = _svc(_row("finalized"))
    out = svc.finalize("p", _QK, finalized_by="u1")
    assert out.status == "finalized"
    assert svc.repo.upserted is None            # no re-write


def test_finalize_rejects_invoiced():
    with pytest.raises(ValidationError):
        _svc(_row("invoiced")).finalize("p", _QK, finalized_by="u1")


def test_finalize_rejects_blocked():
    with pytest.raises(ValidationError):
        _svc(_row("blocked_missing_npqp")).finalize("p", _QK, finalized_by="u1")


def test_finalize_404_when_missing():
    with pytest.raises(NotFoundError):
        _svc(None).finalize("p", _QK, finalized_by="u1")


# ---- clear_override (revert) --------------------------------------------

def test_clear_override_recomputes_overridden():
    svc = _svc(_row("overridden", override_reason="testing"))
    svc.close = lambda *a, **k: SimpleNamespace(status="auto_closed", override_reason=None)
    out = svc.clear_override("p", _QK)
    assert out.status == "auto_closed"


def test_clear_override_rejects_locked():
    for st in ("invoiced", "finalized"):
        with pytest.raises(ValidationError):
            _svc(_row(st)).clear_override("p", _QK)


# ---- override guards -----------------------------------------------------

def test_override_rejects_blank_reason():
    with pytest.raises(ValidationError):
        _svc(_row("auto_closed")).override(
            "p", _QK, new_sum_ld_percent=Decimal("5"), override_reason="   ", closed_by="u",
        )


def test_override_rejects_finalized():
    with pytest.raises(ValidationError):
        _svc(_row("finalized")).override(
            "p", _QK, new_sum_ld_percent=Decimal("5"), override_reason="x", closed_by="u",
        )


def test_override_rejects_invoiced():
    with pytest.raises(ValidationError):
        _svc(_row("invoiced")).override(
            "p", _QK, new_sum_ld_percent=Decimal("5"), override_reason="x", closed_by="u",
        )


# ---- SettlementItem flags -----------------------------------------------

def _item(status, override_reason=None):
    now = datetime(2026, 1, 1)
    return SettlementItem.model_validate(SimpleNamespace(
        id="s1", project_id="p", contract_type="PMU", fiscal_year=1, quarter=1,
        quarter_start=now.date(), quarter_end=now.date(), sum_ld_percent=None,
        capped_ld_percent=None, f_amount=None, qgr_amount=None, npqp=None,
        ld_amount=None, pa_amount=None, aqp_amount=None, status=status,
        closed_at=None, closed_by=None, override_reason=override_reason,
        source_aggregate_ids=None, consequence_flags={}, created_at=now, updated_at=now,
    ))


def test_flags():
    assert _item("auto_closed").manually_overridden is False
    assert _item("overridden", "testing").manually_overridden is True
    assert _item("finalized", "testing").manually_overridden is True   # survives finalize
    assert _item("invoiced", "invoiced (ref=X)").manually_overridden is False  # billing note ≠ override
    assert _item("finalized").finalized is True
    assert _item("auto_closed").finalized is False
