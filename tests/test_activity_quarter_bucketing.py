"""Rollup buckets a mapping by its ACTIVITY's anchored quarter, not the eval
record date. The date driver is `_activity_start_ist`, which turns the resolver's
ISO startDate into an IST calendar date (the quarter authority).

The full rollup path (a Q2/Q3 activity whose breach was recorded in a later
quarter moves back to the activity's quarter, F included) is verified end-to-end
against a copied project; these unit-test the date helper it hinges on."""
from __future__ import annotations

from datetime import date

from app.services.sla_compliance_service import _activity_start_ist


def test_offset_datetime_kept():
    assert _activity_start_ist({"startDate": "2026-04-09T00:00:00+05:30"}) == date(2026, 4, 9)


def test_utc_instant_converted_to_ist_day():
    # 2026-04-08 18:30 UTC == 2026-04-09 00:00 IST → the IST day is the 9th.
    assert _activity_start_ist({"startDate": "2026-04-08T18:30:00+00:00"}) == date(2026, 4, 9)
    assert _activity_start_ist({"startDate": "2026-04-08T18:30:00Z"}) == date(2026, 4, 9)


def test_plain_date_string():
    assert _activity_start_ist({"startDate": "2026-04-09"}) == date(2026, 4, 9)


def test_missing_or_unparseable():
    assert _activity_start_ist(None) is None
    assert _activity_start_ist({}) is None
    assert _activity_start_ist({"startDate": None}) is None
    assert _activity_start_ist({"startDate": "not-a-date"}) is None
