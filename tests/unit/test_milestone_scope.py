"""Vendor-scoped milestone visibility helper (pure branches, no DB)."""
from __future__ import annotations

from types import SimpleNamespace

from app.core import milestone_scope as ms


def test_admin_gets_no_filter():
    assert ms.vendor_milestone_filter("P1", caller_vendor_id="V1", caller_is_admin=True) is None
    # even with no vendor, an admin is unrestricted
    assert ms.vendor_milestone_filter("P1", caller_vendor_id=None, caller_is_admin=True) is None


def test_no_vendor_nonadmin_is_fail_closed():
    clause = ms.vendor_milestone_filter("P1", caller_vendor_id=None, caller_is_admin=False)
    assert clause is not None
    assert "false" in str(clause).lower()  # matches nothing -> sees nothing


def test_vendor_user_gets_activity_subquery():
    clause = ms.vendor_milestone_filter("P1", caller_vendor_id="V1", caller_is_admin=False)
    assert clause is not None
    s = str(clause).lower()
    assert "activities" in s and "milestone_id" in s  # IN (SELECT activity.milestone_id ...)


def test_can_see_admin_and_no_vendor_without_db():
    m = SimpleNamespace(id="m1")
    # admin: True without touching the db; no-vendor non-admin: False without db
    assert ms.can_see_milestone(None, m, caller_vendor_id="V1", caller_is_admin=True) is True
    assert ms.can_see_milestone(None, m, caller_vendor_id=None, caller_is_admin=False) is False
    assert ms.can_see_milestone(None, None, caller_vendor_id="V1", caller_is_admin=False) is False
