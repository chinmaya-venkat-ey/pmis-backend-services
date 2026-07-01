"""The final phase must be fully utilised (100%).

The last-phase auto-fill only covers NULL milestones; this guard rejects a term
update that leaves the terminal phase all-explicit and != 100 (it can't carry a
shortfall forward). Non-last phases may be under 100 freely.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.errors import ValidationError
from app.schemas.payment import PaymentTermUpdateRequest
from app.services import project_payment_term_service as pts
from app.services.project_payment_term_service import ProjectPaymentTermService


def _term(tid, pct):
    return SimpleNamespace(id=tid, project_id="p1", phase="LAST",
                           percent_of_payment=(None if pct is None else Decimal(str(pct))),
                           frequency_code=None)


def _svc(monkeypatch, row, phase_terms, others_sum, is_last=True):
    svc = ProjectPaymentTermService(MagicMock())
    svc.get_by_id = MagicMock(return_value=row)
    svc._require_project = MagicMock(return_value=SimpleNamespace(id="p1"))
    svc._is_last_phase = MagicMock(return_value=is_last)
    svc.repo = MagicMock()
    svc.repo.list_all_live = MagicMock(return_value=phase_terms)
    svc.repo.sum_percent_for_phase = MagicMock(return_value=Decimal(str(others_sum)))
    svc.repo.update = MagicMock(return_value=row)
    svc.audit = MagicMock()
    monkeypatch.setattr(pts, "assert_payment_writable", lambda *a, **k: None)
    return svc


def test_last_phase_all_explicit_under_100_rejected(monkeypatch):
    row = _term("t2", None)
    svc = _svc(monkeypatch, row, [_term("t1", 60), row], others_sum=60)
    with pytest.raises(ValidationError):
        svc.update("t2", PaymentTermUpdateRequest(percentOfPayment=Decimal("20")),
                   caller_user_id="u", caller_is_admin=True)  # 60 + 20 = 80 != 100


def test_last_phase_reaches_100_allowed(monkeypatch):
    row = _term("t2", None)
    svc = _svc(monkeypatch, row, [_term("t1", 60), row], others_sum=60)
    svc.update("t2", PaymentTermUpdateRequest(percentOfPayment=Decimal("40")),
               caller_user_id="u", caller_is_admin=True)  # 60 + 40 = 100 -> ok
    svc.repo.update.assert_called_once()


def test_last_phase_with_a_null_term_allowed(monkeypatch):
    # a still-null milestone will auto-fill the remainder, so under-100 is fine.
    row = _term("t2", None)
    svc = _svc(monkeypatch, row, [_term("t1", 60), row, _term("t3", None)], others_sum=60)
    svc.update("t2", PaymentTermUpdateRequest(percentOfPayment=Decimal("20")),
               caller_user_id="u", caller_is_admin=True)  # t3 null -> allowed
    svc.repo.update.assert_called_once()


def test_non_last_phase_under_100_allowed(monkeypatch):
    row = _term("t2", None)
    svc = _svc(monkeypatch, row, [_term("t1", 60), row], others_sum=60, is_last=False)
    svc.update("t2", PaymentTermUpdateRequest(percentOfPayment=Decimal("20")),
               caller_user_id="u", caller_is_admin=True)  # non-last: 80 < 100 fine
    svc.repo.update.assert_called_once()


def test_clearing_to_null_on_last_phase_allowed(monkeypatch):
    row = _term("t1", 60)
    svc = _svc(monkeypatch, row, [row, _term("t2", 40)], others_sum=40)
    svc.update("t1", PaymentTermUpdateRequest(percentOfPayment=None),
               caller_user_id="u", caller_is_admin=True)  # null auto-fills -> allowed
    svc.repo.update.assert_called_once()
