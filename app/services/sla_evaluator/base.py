"""Evaluator base class + shared context dataclass.

Each per-formula evaluator implements `evaluate(ctx) -> EvaluatedResult`.
The context bundles everything needed: SLA master rows, mapping overrides,
observations, and the resolved period.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.models.sla_activity_mapping import SlaActivityMapping
from app.models.sla_condition_band import SlaConditionBand
from app.models.sla_definition import SlaDefinition
from app.models.sla_guard_condition import SlaGuardCondition
from app.models.sla_lookup_row import SlaLookupRow
from app.models.sla_metric import SlaMetric
from app.models.sla_parameter_value import SlaParameterValue
from app.schemas.sla_evaluation import (
    BreachDetail,
    GuardResult,
    MetricObservation,
)


@dataclass
class EvaluationContext:
    """Read-only inputs for a single severity evaluation.

    LD-related fields (ld_base_amount, points_to_ld_map) were removed when
    severity and LD were split into separate APIs. The LD calculator owns
    that data — see the dedicated LD endpoints (TBD).
    """
    mapping: SlaActivityMapping
    sla: SlaDefinition
    formula_type: str
    metrics: List[SlaMetric]
    parameters: List[SlaParameterValue]
    bands: List[SlaConditionBand]
    lookup_rows: List[SlaLookupRow]
    guards: List[SlaGuardCondition]
    period_start: date
    period_end: date
    observations: List[MetricObservation]
    overrides_applied: Dict[str, Any] = field(default_factory=dict)

    # Project-scoped severity_master resolved at request time. None means
    # "no project chart configured" → evaluator must use its baked-in
    # RFP defaults.
    project_id: Optional[str] = None
    level_points_map: Optional[Dict[int, Decimal]] = None  # severity_master


@dataclass
class EvaluatedResult:
    """Severity-only output of a formula evaluation.

    No ld_percent / ld_amount — those live in the LD API. Each evaluator
    returns the band/level the metric fell into and the breakdown that
    explains it.
    """
    severity_level: Optional[int] = None
    accumulated_points: Optional[Decimal] = None
    breaches: List[BreachDetail] = field(default_factory=list)
    guards: List[GuardResult] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


class FormulaEvaluator:
    """Subclasses implement evaluate(); base provides shared helpers."""

    formula_type: str = ""

    def evaluate(self, ctx: EvaluationContext) -> EvaluatedResult:
        raise NotImplementedError

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _observation_for(ctx: EvaluationContext, metric_key: str) -> Optional[MetricObservation]:
        for obs in ctx.observations:
            if obs.metric_key == metric_key:
                return obs
        return None

    @staticmethod
    def _primary_metric(ctx: EvaluationContext) -> Optional[SlaMetric]:
        for m in ctx.metrics:
            if m.is_primary:
                return m
        return ctx.metrics[0] if ctx.metrics else None

    @staticmethod
    def _evaluate_guards(ctx: EvaluationContext) -> List[GuardResult]:
        results: List[GuardResult] = []
        for g in ctx.guards:
            obs = FormulaEvaluator._observation_for(ctx, g.metric_key)
            observed = obs.single_value if obs and obs.single_value is not None else None
            triggered = False
            if observed is not None:
                triggered = _compare(observed, g.operator, g.threshold_value)
            results.append(
                GuardResult(
                    metric_key=g.metric_key,
                    operator=g.operator,
                    threshold_value=g.threshold_value,
                    observed_value=observed,
                    triggered=triggered,
                    action=g.action,
                    action_description=g.action_description,
                )
            )
        return results

    @staticmethod
    def _value_in_band(value: Decimal, band: SlaConditionBand) -> bool:
        """Backwards-compatible inclusivity: min strict, max inclusive (current schema default).

        Phase 1 of the refactor adds explicit min_inclusive/max_inclusive on the
        band row; until then we use the convention used by the existing seed
        data: range_min exclusive, range_max inclusive.
        """
        if band.range_min is not None and not (value > band.range_min):
            return False
        if band.range_max is not None and not (value <= band.range_max):
            return False
        return True


def _compare(left: Decimal, op: str, right: Decimal) -> bool:
    if op == "LT":
        return left < right
    if op == "LTE":
        return left <= right
    if op == "GT":
        return left > right
    if op == "GTE":
        return left >= right
    if op == "EQ":
        return left == right
    if op == "NEQ":
        return left != right
    return False
