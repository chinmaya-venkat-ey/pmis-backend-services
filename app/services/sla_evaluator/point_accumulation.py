"""point_accumulation evaluator — MSAP/PMU-style severity points.

Per measurement, find the severity band that matches the observed value,
look up its points contribution, and sum across the period. The result
is the highest band hit + the accumulated points.

Default severity points (RFP Annexure-3E): 0=-2, 1=2, 2=4, 3=6, 4=8.
These are used when the project's severity_master is empty.

This evaluator does NOT compute LD%. The LD API consumes
``accumulated_points`` + the project's project_ld_bands chart to derive
the penalty separately.

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

        # PER_UNIT_OVER_THRESHOLD — RFP §5.28.3.b (PMU/PMC-SLA005 shape):
        # baseline count (e.g. 1 replacement/quarter) is free; every unit
        # OVER the baseline emits the escalation band's severity once.
        # Point-accumulation single-band-hit doesn't express this; here
        # points scale linearly with (observed - baseline).
        rule = (getattr(ctx.sla, "ld_formula_rule", "") or "").upper()
        if (
            rule == "PER_UNIT_OVER_THRESHOLD"
            and obs.shape == "SINGLE_VALUE"
            and obs.single_value is not None
        ):
            return self._per_unit_over_threshold(ctx, result, primary.metric_key,
                                                  obs.single_value, bands)

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

    def _per_unit_over_threshold(
        self,
        ctx: EvaluationContext,
        result: EvaluatedResult,
        metric_key: str,
        observed_value: Decimal,
        bands: List[SlaConditionBand],
    ) -> EvaluatedResult:
        """RFP §5.28.3.b — points scale linearly with units over the
        baseline threshold.

        Reads the two bands the SLA's condition-band table provides:
          * baseline band (severity=0) — its ``range_max`` is the "free"
            threshold below which no penalty applies (e.g. 1 replacement).
          * escalation band (severity>0) — its ``severity_level`` is the
            penalty per unit over the threshold.

        Points = max(0, observed - baseline) * points_for(escalation_sev).
        Severity = escalation band's severity when observed > baseline,
        else 0.
        """
        baseline_band = next(
            (b for b in bands if (b.severity_level or 0) == 0 and b.range_max is not None),
            None,
        )
        escalation_band = next(
            (b for b in bands if (b.severity_level or 0) > 0),
            None,
        )
        if baseline_band is None or escalation_band is None:
            result.notes.append(
                "PER_UNIT_OVER_THRESHOLD needs one baseline band "
                "(severity=0, range_max=threshold) and one escalation band "
                "(severity>0); check the SLA's condition_bands."
            )
            return result

        baseline = Decimal(str(baseline_band.range_max))
        extra = max(Decimal("0"), observed_value - baseline)
        per_unit_pts = self._band_points(escalation_band, ctx)
        points = extra * per_unit_pts

        result.accumulated_points = points
        if extra > 0:
            result.severity_level = escalation_band.severity_level
            result.breaches.append(
                BreachDetail(
                    metric_key=metric_key,
                    band_label=escalation_band.band_label,
                    observed_value=observed_value,
                    severity_level=escalation_band.severity_level,
                    points_contribution=points,
                    note=(
                        f"PER_UNIT_OVER_THRESHOLD: extra={extra} "
                        f"(observed={observed_value} - baseline={baseline}), "
                        f"points/unit={per_unit_pts}"
                    ),
                )
            )
        else:
            result.severity_level = 0
        return result
