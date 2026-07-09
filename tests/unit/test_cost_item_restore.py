"""Restore-path guards for cost rows.

A cost row keeps its milestone bindings through a soft-delete (so a restore can
bring them back). While the row is deleted, though, its milestones are free and
may be re-assigned to a NEW cost row. Restoring the old row must NOT silently
double-bind those milestones (two live cost rows on one milestone breaks the
one-cost-per-milestone invariant) — it must fail with a clear conflict.

Companion to the delete->recreate path (a deleted cost's milestones are freed
for re-assignment), which the live queries enforce by filtering
``project_cost_items.deleted_at``.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.errors import ValidationError
from app.services import project_cost_item_service as cim
from app.services.project_cost_item_service import ProjectCostItemService


def _restore_svc(monkeypatch):
    svc = ProjectCostItemService(MagicMock())
    svc.repo = MagicMock()
    svc.audit = MagicMock()
    svc._require_project = MagicMock(return_value=SimpleNamespace(id="p1", status="new"))
    svc._reconcile_payment_terms = MagicMock()
    monkeypatch.setattr(cim, "assert_payment_writable", lambda *a, **k: None)
    return svc


def test_restore_rejects_when_milestone_reassigned(monkeypatch):
    # c1 was deleted; while gone, m1 got assigned to another live cost row.
    svc = _restore_svc(monkeypatch)
    svc.repo.get_by_id.return_value = SimpleNamespace(id="c1", project_id="p1")
    svc.repo.list_milestone_ids.return_value = ["m1"]
    # phases_binding_milestones (excluding c1) reports m1 held elsewhere -> conflict
    svc.repo.phases_binding_milestones.return_value = [("m1", "A")]

    with pytest.raises(ValidationError):
        svc.restore("c1", caller_user_id="u", caller_is_admin=True)

    svc.repo.restore.assert_not_called()


def test_restore_succeeds_when_milestones_still_free(monkeypatch):
    svc = _restore_svc(monkeypatch)
    svc.repo.get_by_id.return_value = SimpleNamespace(id="c1", project_id="p1")
    svc.repo.list_milestone_ids.return_value = ["m1"]
    svc.repo.phases_binding_milestones.return_value = []  # still free

    svc.restore("c1", caller_user_id="u", caller_is_admin=True)

    svc.repo.restore.assert_called_once()
    # the free-check excludes the row's own id so its own bindings never conflict
    _, kwargs = svc.repo.phases_binding_milestones.call_args
    assert kwargs.get("exclude_cost_item_id") == "c1"
