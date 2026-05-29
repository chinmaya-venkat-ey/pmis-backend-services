"""point_accumulation evaluator — MSAP/PMU-style severity points.

Per measurement, find the severity band that matches the observed value, look
up its points contribution, sum across the period, and map points to LD%
using the project's severity_master (or the fallback table from RFP).

Default severity points (RFP Annexure-3E): 0=-2, 1=2, 2=4, 3=6, 4=8.
Default points-to-LD: <=0 -> 0%, 2 -> 1%, 4 -> 2%, 6 -> 3%, >=8 -> 4%.

Observation shape: SINGLE_VALUE (one measurement for the period), or
BAND_COUNTS (number of measurements that fell into each band, e.g. months).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional

from app.models.sla_condition_band import SlaConditionBand
from app.schemas.sla_evaluation import BreachDetail
from app.services.sla_evaluator.base import (
    EvaluatedResult,
    EvaluationContext,
    FormulaEvaluator,
)


# Fallback severity_level -> points map (RFP default).
DEFAULT_LEVEL_POINTS: Dict[int, Decimal] = {
    0: Decimal("-2"),
    1: Decimal("2"),
    2: Decimal("4"),
    3: Decimal("6"),
    4: Decimal("8"),
}

# Fallback points -> LD% map (RFP default).
# Keys are inclusive thresholds; we walk them sorted ascending.
DEFAULT_POINTS_TO_LD: List[tuple[Decimal, Decimal]] = [
    (Decimal("0"), Decimal("0")),
    (Decimal("2"), Decimal("1")),
    (Decimal("4"), Decimal("2")),
    (Decimal("6"), Decimal("3")),
    (Decimal("8"), Decimal("4")),
]


def _points_for_level(level: Optional[int], ctx: Optional["EvaluationContext"] = None) -> Decimal:
    """Resolve points for a severity level.

    Priority:
      1. ``ctx.level_points_map`` — populated from contract.severity_master for
         the resolved project.
      2. ``DEFAULT_LEVEL_POINTS`` — RFP fallback (0=-2, 1=2, 2=4, 3=6, 4=8).

    ``level=None`` returns 0 — no severity assigned, no points contribution.
    """
    if level is None:
        return Decimal("0")
    if ctx is not None and ctx.level_points_map and level in ctx.level_points_map:
        return ctx.level_points_map[level]
    return DEFAULT_LEVEL_POINTS.get(level, Decimal(level * 2))


def _ld_percent_for_points(
    points: Decimal, ctx: Optional["EvaluationContext"] = None
) -> Decimal:
    """Map accumulated points to LD percent.

    Priority:
      1. ``ctx.points_to_ld_map`` — populated from contract.project_ld_bands
         for the resolved project. Already sorted ascending by threshold.
      2. ``DEFAULT_POINTS_TO_LD`` — RFP fallback.

    Treat sub-zero / fractional points conservatively: floor to the nearest
    table threshold that the points meet or exceed.
    """
    table = (ctx.points_to_ld_map if ctx is not None and ctx.points_to_ld_map
             else DEFAULT_POINTS_TO_LD)
    result = Decimal("0")
    for threshold, ld in table:
        if points >= threshold:
            result = ld
    return result


class PointAccumulationEvaluator(FormulaEvaluator):
    formula_type = "point_accumulation"

    def evaluate(self, ctx: EvaluationContext) -> EvaluatedResult:
        result = EvaluatedResult()
        result.guards = self._evaluate_guards(ctx)

        primary = self._primary_metric(ctx)
        if primary is None:
            result.notes.append("No primary metric defined; cannot evaluate.")
            return result

        bands = [b for b in ctx.bands if b.metric_key == primary.metric_key]
        if not bands:
            result.notes.append(f"No condition bands for primary metric '{primary.metric_key}'.")
            return result

        obs = self._observation_for(ctx, primary.metric_key)
        if obs is None:
            result.notes.append(f"No observation for primary metric '{primary.metric_key}'.")
            return result

        accumulated = Decimal("0")
        highest_level: Optional[int] = None

        if obs.shape == "SINGLE_VALUE" and obs.single_value is not None:
            band = self._first_band_for(obs.single_value, bands)
            if band is not None:
                pts = self._band_points(band, ctx)
                accumulated += pts
                highest_level = band.severity_level
                result.breaches.append(
                    BreachDetail(
                        metric_key=primary.metric_key,
                        band_label=band.band_label,
                        observed_value=obs.single_value,
                        severity_level=band.severity_level,
                        points_contribution=pts,
                    )
                )
        elif obs.shape == "BAND_COUNTS" and obs.band_counts:
            label_to_band = {b.band_label: b for b in bands}
            for label, count in obs.band_counts.items():
                band = label_to_band.get(label)
                if band is None or count <= 0:
                    continue
                pts = self._band_points(band, ctx) * Decimal(count)
                accumulated += pts
                if band.severity_level is not None:
                    if highest_level is None or band.severity_level > highest_level:
                        highest_level = band.severity_level
                result.breaches.append(
                    BreachDetail(
                        metric_key=primary.metric_key,
                        band_label=label,
                        days_in_band=int(count),
                        severity_level=band.severity_level,
                        points_contribution=pts,
                    )
                )
        else:
            result.notes.append(
                f"point_accumulation expects SINGLE_VALUE or BAND_COUNTS, got '{obs.shape}'."
            )
            return result

        result.accumulated_points = accumulated
        result.severity_level = highest_level
        result.ld_percent = _ld_percent_for_points(accumulated, ctx)
        if ctx.ld_base_amount is not None:
            result.ld_amount = (ctx.ld_base_amount * result.ld_percent) / Decimal("100")
        return result

    @staticmethod
    def _band_points(band: SlaConditionBand, ctx: "EvaluationContext") -> Decimal:
        # Explicit points on the band always win (data-driven override).
        if band.points_contribution is not None:
            return band.points_contribution
        # Otherwise fall through to the project's severity_master → RFP default.
        if band.severity_level is not None:
            return _points_for_level(band.severity_level, ctx)
        return Decimal("0")

    @staticmethod
    def _first_band_for(value: Decimal, bands: List[SlaConditionBand]):
        for band in bands:
            if FormulaEvaluator._value_in_band(value, band):
                return band
        return None
