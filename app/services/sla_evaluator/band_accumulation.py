"""band_accumulation evaluator — BSP-style daily band accumulation.

LD% for the period = sum_over_bands(days_in_band * rate_percent) / total_days_in_period

Observation shape: DAILY_VALUES (one value per day) or BAND_COUNTS
(pre-aggregated days_in_band per band_label).

severity_level returned is the highest severity_level among bands that had
non-zero days_in_band, when bands carry severity_level. May be None if bands
only carry rate_percent.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List

from app.models.sla_condition_band import SlaConditionBand
from app.schemas.sla_evaluation import BreachDetail, MetricObservation
from app.services.sla_evaluator.base import (
    EvaluatedResult,
    EvaluationContext,
    FormulaEvaluator,
)


class BandAccumulationEvaluator(FormulaEvaluator):
    formula_type = "band_accumulation"

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

        total_days = (ctx.period_end - ctx.period_start).days + 1
        if total_days <= 0:
            result.notes.append("Empty reporting period.")
            return result

        days_in_band: Dict[str, int] = {}
        if obs.shape == "BAND_COUNTS" and obs.band_counts:
            days_in_band = {k: int(v) for k, v in obs.band_counts.items()}
        elif obs.shape == "DAILY_VALUES" and obs.daily_values:
            for value in obs.daily_values:
                band = self._first_band_for(value, bands)
                if band is None:
                    continue
                days_in_band[band.band_label] = days_in_band.get(band.band_label, 0) + 1
        else:
            result.notes.append(
                f"band_accumulation expects DAILY_VALUES or BAND_COUNTS, got '{obs.shape}'."
            )
            return result

        total_contribution = Decimal("0")
        highest_severity = None
        for band in bands:
            count = days_in_band.get(band.band_label, 0)
            if count == 0:
                continue
            rate = band.rate_percent or Decimal("0")
            contribution = (Decimal(count) * rate) / Decimal(total_days)
            total_contribution += contribution

            if band.severity_level is not None:
                if highest_severity is None or band.severity_level > highest_severity:
                    highest_severity = band.severity_level

            result.breaches.append(
                BreachDetail(
                    metric_key=primary.metric_key,
                    band_label=band.band_label,
                    days_in_band=count,
                    severity_level=band.severity_level,
                    rate_percent=rate,
                    contribution_percent=contribution,
                )
            )

        result.ld_percent = total_contribution
        result.severity_level = highest_severity
        if ctx.ld_base_amount is not None and result.ld_percent is not None:
            result.ld_amount = (ctx.ld_base_amount * result.ld_percent) / Decimal("100")
        return result

    @staticmethod
    def _first_band_for(value: Decimal, bands: List[SlaConditionBand]):
        for band in bands:
            if FormulaEvaluator._value_in_band(value, band):
                return band
        return None
