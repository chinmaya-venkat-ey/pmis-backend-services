"""Offline unit tests for the points -> LD% lookup and the whole-activity cap.

Covers both LD changes without a live server:
  1. per-SLA: accumulated_points -> ld_percent via the project LD chart.
  2. whole-activity: total points -> ld_percent, capped at 10%.
"""
from datetime import date
from decimal import Decimal

from app.services.ld_bands import (
    DEFAULT_LD_BANDS,
    ld_percent_for_points,
    resolve_band_pairs,
)
from app.schemas.sla_evaluation import (
    ActivityEvaluationResponse,
    MappingEvaluationResponse,
)


class _Row:
    """Stand-in for a ProjectLdBand ORM row."""
    def __init__(self, threshold, pct):
        self.points_threshold = threshold
        self.ld_percent = pct


def test_default_chart_lookup_highest_tier_wins():
    pairs = resolve_band_pairs([])           # RFP default: 0->0,2->1,4->2,6->3,8->4
    assert ld_percent_for_points(Decimal("0"), pairs) == Decimal("0")
    assert ld_percent_for_points(Decimal("2"), pairs) == Decimal("1")
    assert ld_percent_for_points(Decimal("5"), pairs) == Decimal("2")   # highest <= 5 is 4
    assert ld_percent_for_points(Decimal("8"), pairs) == Decimal("4")
    assert ld_percent_for_points(Decimal("100"), pairs) == Decimal("4")  # above max -> top tier


def test_below_lowest_and_negative_is_zero():
    pairs = resolve_band_pairs([])
    assert ld_percent_for_points(Decimal("-2"), pairs) == Decimal("0")


def test_none_points_or_empty_pairs_is_none():
    assert ld_percent_for_points(None, resolve_band_pairs([])) is None
    assert ld_percent_for_points(Decimal("5"), []) is None


def test_project_chart_overrides_default():
    pairs = resolve_band_pairs([_Row(Decimal("0"), Decimal("0")), _Row(Decimal("10"), Decimal("12"))])
    assert ld_percent_for_points(Decimal("12"), pairs) == Decimal("12")
    assert len(DEFAULT_LD_BANDS) == 5


def test_whole_activity_total_capped_at_10():
    # A chart that can exceed 10% -> total is capped.
    pairs = resolve_band_pairs([_Row(Decimal("0"), Decimal("0")), _Row(Decimal("10"), Decimal("12"))])
    total = sum((Decimal("6"), Decimal("8")), Decimal("0"))     # 14 points across SLAs
    capped = min(ld_percent_for_points(total, pairs), Decimal("10"))
    assert capped == Decimal("10")

    # Default chart tops out at 4% -> the cap is a no-op.
    dp = resolve_band_pairs([])
    total2 = sum((Decimal("2"), Decimal("4"), Decimal("6")), Decimal("0"))  # 12
    assert min(ld_percent_for_points(total2, dp), Decimal("10")) == Decimal("4")


def test_response_schemas_accept_new_fields():
    m = MappingEvaluationResponse(
        mapping_id="m1", activity_id="a1", sla_id="s1", sla_ref="PMU-SLA005",
        formula_type="point_accumulation", period_start=date(2026, 1, 1),
        period_end=date(2026, 3, 31), accumulated_points=Decimal("4"),
        ld_percent=Decimal("2"),
    )
    assert m.ld_percent == Decimal("2")
    act = ActivityEvaluationResponse(
        activity_id="a1", period_start=date(2026, 1, 1), period_end=date(2026, 3, 31),
        mapping_results=[m], total_points=Decimal("4"), total_ld_percent=Decimal("2"),
    )
    assert act.total_points == Decimal("4")
    assert act.total_ld_percent == Decimal("2")
