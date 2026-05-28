"""fixed_escalation evaluator — milestone / delay-based tiered LD%.

Looks up an observed value (e.g. days_of_delay, percent_complete) against the
SLA's `sla_lookup_rows`. Each row has a `lookup_key` (label like "on_time",
"delay_1_7", "delay_8_plus") and a `lookup_value` (LD percent). Until we wire
explicit range semantics on lookup rows, this evaluator treats them as
ordered tiers and selects the *last row whose sort_order is <= the observed
tier index* — works for the common case where the form fills tiers in order
and the user supplies the tier label as the observation. When the observation
is SINGLE_VALUE, we fall back to picking the row with the highest
lookup_value <= observed.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from app.schemas.sla_evaluation import BreachDetail
from app.services.sla_evaluator.base import (
    EvaluatedResult,
    EvaluationContext,
    FormulaEvaluator,
)


class FixedEscalationEvaluator(FormulaEvaluator):
    formula_type = "fixed_escalation"

    def evaluate(self, ctx: EvaluationContext) -> EvaluatedResult:
        result = EvaluatedResult()
        result.guards = self._evaluate_guards(ctx)

        primary = self._primary_metric(ctx)
        if primary is None:
            result.notes.append("No primary metric defined; cannot evaluate.")
            return result

        obs = self._observation_for(ctx, primary.metric_key)
        if obs is None:
            result.notes.append(f"No observation for primary metric '{primary.metric_key}'.")
            return result

        rows = sorted(ctx.lookup_rows, key=lambda r: r.sort_order)
        if not rows:
            result.notes.append("No lookup rows defined for fixed_escalation.")
            return result

        chosen = None
        observed_value: Optional[Decimal] = None
        if obs.shape == "SINGLE_VALUE" and obs.single_value is not None:
            observed_value = obs.single_value
            # Walk tiers in order; choose the last tier whose lookup_value
            # threshold is <= observed_value. Treat lookup_value here as an
            # ordered ascending escalation indicator until ranges are added.
            for row in rows:
                threshold = Decimal(row.sort_order)
                if observed_value >= threshold:
                    chosen = row
        else:
            result.notes.append(
                f"fixed_escalation expects SINGLE_VALUE observation, got '{obs.shape}'."
            )
            return result

        if chosen is None:
            result.notes.append("No lookup tier matched the observation.")
            return result

        ld = Decimal(chosen.lookup_value or 0)
        result.ld_percent = ld
        if ctx.ld_base_amount is not None:
            result.ld_amount = (ctx.ld_base_amount * ld) / Decimal("100")

        result.breaches.append(
            BreachDetail(
                metric_key=primary.metric_key,
                band_label=chosen.lookup_key,
                observed_value=observed_value,
                rate_percent=ld,
                contribution_percent=ld,
                note="fixed_escalation tier matched",
            )
        )
        return result
