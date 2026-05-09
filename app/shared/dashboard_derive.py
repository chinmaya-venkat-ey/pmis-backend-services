"""Pure derivation functions for the dashboard surface.

Defines three mutually-exclusive **project** buckets and three
mutually-exclusive **item** (M/A) buckets:

  * ``ontrack``    — work in flight, no breached deadline yet.
  * ``delayed``    — at least one live M/A is past its expected end
                     and not yet ``completed`` (project-level), or the
                     item itself is past its end and not completed.
  * ``completed``  — project lifecycle is ``closed``; or the item's
                     ``status`` is ``completed``. Wins over ``delayed``
                     even when finished after the planned end date —
                     the bucket reflects whether work is *done*, not
                     whether it was *on time*.

Note: there is no ``active`` bucket. The Summary view's "Active
Projects" KPI tile is a derived count (``total − completed``), not a
distinct bucket. An empty project (``new``/``draft``, no M/A yet)
falls into ``ontrack`` by the vacuous-truth rule (no item is past its
end ⇒ all items are within dates).

The dashboard uses these via three primitives:

  * ``item_bucket`` for a milestone or activity row
  * ``project_bucket`` for a project, derived from its lifecycle
    status + the buckets of its live M/A items
  * ``item_delay_days`` for the "Delayed Track" listings — counted
    only for non-completed items past their end date

All callers must pass an IST calendar date (``today_ist_date``) — the
PMIS contract is that *all* deadline math runs in IST. Use
``ist_today()`` from this module to get the right value.
"""
from datetime import date, datetime, timezone
from typing import Iterable, Optional

from .datetime import IST


# --- Public bucket constants -----------------------------------------------

BUCKET_ONTRACK = "ontrack"
BUCKET_DELAYED = "delayed"
BUCKET_COMPLETED = "completed"

# Order matters for pie / KPI display — keep stable. Both project and
# item buckets share this triple.
PROJECT_BUCKETS = (BUCKET_ONTRACK, BUCKET_DELAYED, BUCKET_COMPLETED)
ITEM_BUCKETS = (BUCKET_ONTRACK, BUCKET_DELAYED, BUCKET_COMPLETED)


# Project lifecycle -> ``completed`` mapping. Anything else needs the
# item walk below.
_LIFECYCLE_COMPLETED = frozenset({"closed"})

# Lifecycles that participate in the "check the items" path. Any other
# value falls through to ``ontrack`` (defensive — never seen in the
# wild, but won't crash on unexpected data).
_LIFECYCLE_INFLIGHT = frozenset({"new", "draft", "published"})


# Status the M/A row carries when work is done.
_ITEM_STATUS_COMPLETED = "completed"


# --- IST today -------------------------------------------------------------

def ist_today() -> date:
    """Today's calendar date in IST. Single helper so every dashboard
    endpoint uses the same instant."""
    return datetime.now(timezone.utc).astimezone(IST).date()


def _ist_calendar_date(dt: Optional[datetime]) -> Optional[date]:
    """Project ``dt`` onto the IST calendar. Naive inputs are assumed
    UTC (matches ``UtcDateTime`` storage)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).date()


# --- Item-level derivation -------------------------------------------------

def item_bucket(
    status: Optional[str],
    expected_end: Optional[datetime],
    today_ist_date: date,
) -> str:
    """Bucket a single milestone or activity.

    Rules (mutually exclusive):
      1. ``status == "completed"`` → ``completed`` (wins even when the
         row finished after its planned end).
      2. else if expected end is strictly before today (IST)
         → ``delayed``.
      3. else → ``ontrack``.

    A row with no expected end (legacy, pre-required-dates) is treated
    as ``ontrack`` — it has no deadline to breach.
    """
    if (status or "") == _ITEM_STATUS_COMPLETED:
        return BUCKET_COMPLETED
    end_d = _ist_calendar_date(expected_end)
    if end_d is not None and end_d < today_ist_date:
        return BUCKET_DELAYED
    return BUCKET_ONTRACK


def item_delay_days(
    status: Optional[str],
    expected_end: Optional[datetime],
    today_ist_date: date,
) -> int:
    """Days delayed for a milestone or activity.

    Returns 0 unless the row is in the ``delayed`` bucket (i.e. not
    completed AND expected end < today IST). Then returns the integer
    count of calendar days past the deadline.
    """
    if (status or "") == _ITEM_STATUS_COMPLETED:
        return 0
    end_d = _ist_calendar_date(expected_end)
    if end_d is None or end_d >= today_ist_date:
        return 0
    return (today_ist_date - end_d).days


# --- Project-level derivation ---------------------------------------------

def project_bucket(
    lifecycle_status: Optional[str],
    item_buckets: Iterable[str],
) -> str:
    """Bucket a project from its lifecycle status + the buckets of its
    live milestones and activities.

    Rules (mutually exclusive — three buckets):
      * lifecycle ``closed``                          → ``completed``
      * lifecycle in {new, draft, published} AND
        any item bucket == ``delayed``                → ``delayed``
      * lifecycle in {new, draft, published} AND
        every item is ``completed`` / ``ontrack`` (or
        no items at all)                              → ``ontrack``
      * any unrecognised lifecycle status              → ``ontrack``
        (defensive default; never seen in practice)

    Empty-project rule: a project with zero live M/A items falls into
    ``ontrack`` by vacuous truth — confirmed acceptable by the senior
    review (matches "Active Projects" KPI being derived as
    ``total − completed``, so empty projects still count as active on
    the KPI strip).

    The caller is responsible for excluding soft-deleted M/A from
    ``item_buckets``.
    """
    s = (lifecycle_status or "").lower()
    if s in _LIFECYCLE_COMPLETED:
        return BUCKET_COMPLETED
    # Item walk — any delayed → delayed; else ontrack.
    for b in item_buckets:
        if b == BUCKET_DELAYED:
            return BUCKET_DELAYED
    return BUCKET_ONTRACK


def progress_pct(
    completed_ma: int,
    total_ma: int,
) -> int:
    """Project-level progress as a rounded integer percentage.

    Defined as ``(completed M + completed A) / (total M + total A)``
    over live (non-deleted) rows. ``0`` when there are no items.
    """
    if total_ma <= 0:
        return 0
    return int(round(completed_ma * 100.0 / total_ma))


# --- Helpers used by counter folds in the repository -----------------------

def empty_bucket_counts() -> dict:
    """Zeroed bucket dict, ready to ``+= 1`` against. Three keys —
    ``ontrack``, ``delayed``, ``completed``."""
    return {b: 0 for b in PROJECT_BUCKETS}
