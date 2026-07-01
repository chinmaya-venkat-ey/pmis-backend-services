"""Chronological phase ordering — shared so the payment-page builder and the
payment-term validation agree on phase order and on which phase is "last".

Order is derived purely from each phase's milestone date span
(``phase_dates[phase] = (min_start, max_end)``): earliest ``start`` first, ties
broken by earliest ``end`` (shorter span precedes), undated phases (no bound
milestone dates) last, name as the final deterministic tie-break.
"""
from __future__ import annotations

from typing import List


def name_key(phase):
    """Deterministic tie-break on the phase NAME: numeric names by value
    (1, 2, 10 — not 1, 10, 2), non-numeric names after, lexical."""
    s = str(phase)
    return (0, int(s), s) if s.isdigit() else (1, 0, s)


def phase_order_key(phase, phase_dates):
    """Sort key for one phase (see module docstring)."""
    start, end = phase_dates.get(phase, (None, None))
    dated = 0 if start is not None else 1
    # The leading ``dated`` flag (0 dated / 1 undated) always separates the two
    # groups, so the date fields are only ever compared within a group (both
    # datetimes, or both None → equal) and never datetime-vs-None.
    return (dated, start, end if end is not None else start, name_key(phase))


def order_phases(phases, phase_dates) -> List:
    """Chronologically-ordered list of ``phases``."""
    return sorted(phases, key=lambda p: phase_order_key(p, phase_dates))
