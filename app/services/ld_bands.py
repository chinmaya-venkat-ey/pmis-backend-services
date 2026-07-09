"""Points → LD% lookup for the project LD chart (``project_ld_bands``).

The chart maps accumulated severity POINTS to an LD PERCENT: the result is the
``ld_percent`` of the HIGHEST tier whose ``points_threshold`` the points meet
(threshold <= points). Below the lowest tier -> 0%. A project that has configured
no custom chart uses the RFP MSAP defaults below — the single source of truth
(``MasterService`` seeds its default bands from this list too).
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

# (points_threshold, ld_percent, label) — RFP MSAP default (Annexure-3E).
DEFAULT_LD_BANDS: List[Tuple[Decimal, Decimal, str]] = [
    (Decimal("0"), Decimal("0"), "On Target"),
    (Decimal("2"), Decimal("1"), "Tier 1"),
    (Decimal("4"), Decimal("2"), "Tier 2"),
    (Decimal("6"), Decimal("3"), "Tier 3"),
    (Decimal("8"), Decimal("4"), "Tier 4 / Cap"),
]


def resolve_band_pairs(rows: Sequence) -> List[Tuple[Decimal, Decimal]]:
    """Return ``(threshold, ld_percent)`` pairs for a project's chart, or the
    RFP default when the project has configured none. ``rows`` are
    ``ProjectLdBand`` ORM rows (as returned by ``list_ld_bands_for_project``)."""
    if rows:
        return [(Decimal(str(r.points_threshold)), Decimal(str(r.ld_percent))) for r in rows]
    return [(t, p) for (t, p, _label) in DEFAULT_LD_BANDS]


def ld_percent_for_points(
    points, pairs: Sequence[Tuple[Decimal, Decimal]]
) -> Optional[Decimal]:
    """LD% for ``points`` from ``pairs`` ((threshold, ld_percent), any order).

    The highest tier whose threshold is <= ``points`` wins; points below every
    tier -> ``0``; ``points`` is None or no pairs -> ``None`` (unknown)."""
    if points is None or not pairs:
        return None
    pts = Decimal(str(points))
    hit: Optional[Decimal] = None
    for threshold, pct in sorted(pairs, key=lambda x: x[0]):
        if threshold <= pts:
            hit = pct
        else:
            break
    return hit if hit is not None else Decimal("0")
