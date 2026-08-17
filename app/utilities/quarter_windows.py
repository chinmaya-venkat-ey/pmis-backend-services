"""Tile a ``[start, end]`` window into anchored QUARTER buckets.

Used to lay out a resource-based milestone's activities as one-per-quarter slices
— auto-generated for new milestones and used to realign existing ones — anchored
on the **milestone start** so the windows line up 1:1 with contract-management's
phase-anchored SLA quarters (``project_anchor`` = earliest resource-based
milestone start). Reuses ``cf_pool``'s quarter bucket math.

Pure date math — no DB, no side effects.
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional, Tuple

from app.utilities.cf_pool import _as_date, bucket_bounds, bucket_index

_QUARTERLY = "quarterly"


def quarter_windows(m_start, m_end) -> List[Tuple[date, date]]:
    """Anchored quarter windows tiling ``[m_start, m_end]``, anchored on
    ``m_start``.

    Window ``k`` = ``[m_start + 3k months, m_start + 3(k+1) months − 1 day]``,
    with the LAST window's end clamped to ``m_end``. Returns ``(start, end)``
    ``date`` pairs — at least one window when both dates are present and
    ``m_end >= m_start``; ``[]`` otherwise. Accepts ``date`` or tz-aware
    ``datetime`` (normalised to the IST calendar date)."""
    s = _as_date(m_start)
    e = _as_date(m_end)
    if not (s and e) or e < s:
        return []
    # anchor == m_start ⇒ the start bucket index is 0.
    end_i = bucket_index(e, _QUARTERLY, anchor=s)
    windows: List[Tuple[date, date]] = []
    for k in range(end_i + 1):
        ws, we = bucket_bounds(k, _QUARTERLY, anchor=s)
        if k == end_i:
            we = min(we, e)  # clamp the final window to the milestone end
        windows.append((ws, we))
    return windows


def quarter_window_of(d, m_start, m_end) -> Optional[Tuple[date, date]]:
    """The quarter window (anchored on ``m_start``, end clamped to ``m_end``) that
    CONTAINS date ``d`` — used to snap an existing activity's window to its own
    quarter without moving it to a different one. ``None`` when a date is
    missing."""
    s = _as_date(m_start)
    e = _as_date(m_end)
    dd = _as_date(d)
    if not (s and e and dd):
        return None
    k = bucket_index(dd, _QUARTERLY, anchor=s)
    if k is None or k < 0:
        k = 0
    ws, we = bucket_bounds(k, _QUARTERLY, anchor=s)
    return (ws, min(we, e))
