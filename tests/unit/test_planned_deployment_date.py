"""planned_deployment_date: the IST-calendar-date guard on the request schema
(#1) and the within-activity-window validation on the service (#2).

Guard (#1): a plain YYYY-MM-DD (what the FE sends) is stored verbatim; a client
that serialises the picked day as a full instant — e.g. IST midnight sent as a
UTC `Z` timestamp, which lands on the previous UTC day — is projected onto the
IST calendar so the stored date never shifts by a timezone.

Window (#2): every allocation's deployment date must fall inside the activity's
own [start_date, end_date] window (inclusive, IST calendar)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.errors import ValidationError
from app.schemas.activity import ActivityPlannedResourceItem
from app.services.activity_service import ActivityService
from app.utilities.date_rules import to_ist_calendar_date

IST = timezone(timedelta(hours=5, minutes=30))


def _pdd(value):
    """Build an item with the given deployment-date input; return the
    schema-normalised date."""
    return ActivityPlannedResourceItem(
        designation="PM", quantity=1, duration=1, plannedDeploymentDate=value,
    ).planned_deployment_date


# ── #1 guard — schema normalisation ──────────────────────────────────
def test_plain_date_string_unchanged():
    assert _pdd("2026-09-01") == date(2026, 9, 1)


def test_date_object_unchanged():
    assert _pdd(date(2026, 9, 1)) == date(2026, 9, 1)


def test_ist_midnight_sent_as_utc_z_recovers_ist_day():
    # 2026-08-31T18:30:00Z == 2026-09-01 00:00 IST — must store the IST day.
    assert _pdd("2026-08-31T18:30:00Z") == date(2026, 9, 1)
    assert _pdd("2026-08-31T18:30:00+00:00") == date(2026, 9, 1)


def test_offset_and_zero_time_datetimes_keep_their_day():
    assert _pdd("2026-09-01T00:00:00+05:30") == date(2026, 9, 1)
    assert _pdd("2026-09-01T00:00:00.000Z") == date(2026, 9, 1)
    assert _pdd("2026-09-01T12:00:00+05:30") == date(2026, 9, 1)


def test_helper_none_and_empty():
    assert to_ist_calendar_date(None) is None
    assert to_ist_calendar_date("") is None


# ── #2 window validation ─────────────────────────────────────────────
def _activity(start, end):
    return SimpleNamespace(start_date=start, end_date=end)


def _item(d):
    return SimpleNamespace(designation="PM", planned_deployment_date=d)


def _check(activity, items):
    # unbound method — no ActivityService state is touched by this helper.
    ActivityService._assert_deployment_dates_within_window(None, activity, items)


_ACT = _activity(
    datetime(2026, 9, 1, 0, 0, tzinfo=IST),
    datetime(2026, 9, 30, 23, 59, 59, tzinfo=IST),  # stored end-of-day
)


@pytest.mark.parametrize("d", [date(2026, 9, 1), date(2026, 9, 30), date(2026, 9, 15)])
def test_within_window_inclusive_accepted(d):
    _check(_ACT, [_item(d)])  # no raise


@pytest.mark.parametrize("d", [date(2026, 8, 31), date(2026, 10, 1)])
def test_outside_window_rejected(d):
    with pytest.raises(ValidationError) as ei:
        _check(_ACT, [_item(d)])
    assert ei.value.details["errorIdentifier"] == "deployment_date_outside_activity_window"


def test_no_window_activity_skips():
    _check(_activity(None, None), [_item(date(2020, 1, 1))])  # no raise


def test_default_deploy_equal_to_activity_start_passes():
    # The FE / backfill default is "deploy = activity start"; must stay valid.
    _check(_ACT, [_item(date(2026, 9, 1))])
