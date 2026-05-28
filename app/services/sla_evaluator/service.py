"""SlaEvaluatorService — loads a mapping's context, dispatches to the right
per-formula evaluator, and returns a typed response.

Activity-level evaluate fans out to every active mapping on that activity.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.models.sla_activity_mapping import SlaActivityMapping
from app.models.sla_definition import SlaDefinition
from app.repositories.sla_activity_mapping_repository import (
    SlaActivityMappingRepository,
)
from app.repositories.sla_repository import SlaRepository
from app.schemas.sla_evaluation import (
    ActivityEvaluationRequest,
    ActivityEvaluationResponse,
    MappingEvaluationRequest,
    MappingEvaluationResponse,
    MetricObservation,
)
from app.services.sla_evaluator.band_accumulation import BandAccumulationEvaluator
from app.services.sla_evaluator.base import (
    EvaluatedResult,
    EvaluationContext,
    FormulaEvaluator,
)
from app.services.sla_evaluator.fixed_escalation import FixedEscalationEvaluator
from app.services.sla_evaluator.point_accumulation import PointAccumulationEvaluator
from app.services.sla_evaluator.wac import WacEvaluator


_EVALUATORS: Dict[str, FormulaEvaluator] = {
    BandAccumulationEvaluator.formula_type: BandAccumulationEvaluator(),
    PointAccumulationEvaluator.formula_type: PointAccumulationEvaluator(),
    FixedEscalationEvaluator.formula_type: FixedEscalationEvaluator(),
    WacEvaluator.formula_type: WacEvaluator(),
}


class SlaEvaluatorService:
    def __init__(self, db: Session):
        self.db = db
        self.mapping_repo = SlaActivityMappingRepository(db)
        self.sla_repo = SlaRepository(db)

    # ------------------------------------------------------------------ public

    def evaluate_mapping(
        self, mapping_id: str, payload: MappingEvaluationRequest
    ) -> MappingEvaluationResponse:
        loaded = self.mapping_repo.load_with_sla(mapping_id)
        if loaded is None:
            raise NotFoundError(
                f"Mapping '{mapping_id}' not found", code="mapping_not_found"
            )
        mapping, sla, formula_type = loaded

        if mapping.status != "ACTIVE":
            raise ValidationError(
                f"Mapping is '{mapping.status}'; only ACTIVE mappings can be evaluated.",
                code="mapping_not_active",
            )
        if formula_type is None:
            raise ValidationError(
                f"SLA '{sla.sla_ref}' has no formula_type resolved.",
                code="formula_missing",
            )

        result = self._evaluate(
            mapping=mapping,
            sla=sla,
            formula_type=formula_type,
            period_start=payload.period_start,
            period_end=payload.period_end,
            ld_base_amount=payload.ld_base_amount,
            observations=payload.metric_observations,
        )
        return result

    def evaluate_activity(
        self, activity_id: str, payload: ActivityEvaluationRequest
    ) -> ActivityEvaluationResponse:
        rows = self.mapping_repo.list_for_activity(activity_id, active_only=True)
        period_start, period_end = self._resolve_period_for_activity(payload, rows)

        mapping_results: List[MappingEvaluationResponse] = []
        total_ld_pct = Decimal("0")
        skipped = 0
        for mapping, sla, formula_type in rows:
            if formula_type is None:
                skipped += 1
                continue
            observations = payload.observations_by_sla_ref.get(sla.sla_ref, [])
            ld_base_override = payload.ld_base_amount_overrides.get(sla.sla_ref)
            try:
                single = self._evaluate(
                    mapping=mapping,
                    sla=sla,
                    formula_type=formula_type,
                    period_start=payload.period_start,
                    period_end=payload.period_end,
                    ld_base_amount=ld_base_override,
                    observations=observations,
                )
            except ValidationError:
                skipped += 1
                continue
            mapping_results.append(single)
            if single.ld_percent is not None:
                total_ld_pct += single.ld_percent

        return ActivityEvaluationResponse(
            activity_id=activity_id,
            period_start=period_start,
            period_end=period_end,
            mapping_results=mapping_results,
            summary={
                "mappings_evaluated": len(mapping_results),
                "mappings_skipped": skipped,
                "total_ld_percent": str(total_ld_pct),
            },
        )

    # ------------------------------------------------------------------ internal

    def _evaluate(
        self,
        *,
        mapping: SlaActivityMapping,
        sla: SlaDefinition,
        formula_type: str,
        period_start: Optional[date],
        period_end: Optional[date],
        ld_base_amount: Optional[Decimal],
        observations: List[MetricObservation],
    ) -> MappingEvaluationResponse:
        # Resolve period + ld_base with overrides falling back to mapping/SLA defaults.
        overrides: Dict[str, Any] = mapping.overrides or {}
        applied: Dict[str, Any] = {}

        resolved_start = period_start or _parse_date(overrides.get("actual_start_date"))
        if resolved_start is None:
            resolved_start = mapping.effective_from
        elif period_start is None:
            applied["actual_start_date"] = str(resolved_start)

        resolved_end = (
            period_end
            or _parse_date(overrides.get("actual_end_date"))
            or mapping.effective_until
        )
        if resolved_end is None:
            # If still unknown, default to 90 days after start (a quarter).
            from datetime import timedelta
            resolved_end = resolved_start + timedelta(days=89)
            applied["resolved_end_default"] = str(resolved_end)
        elif period_end is None and overrides.get("actual_end_date"):
            applied["actual_end_date"] = str(resolved_end)

        resolved_ld_base = ld_base_amount
        if resolved_ld_base is None and overrides.get("ld_base_amount") is not None:
            try:
                resolved_ld_base = Decimal(str(overrides["ld_base_amount"]))
                applied["ld_base_amount"] = str(resolved_ld_base)
            except (ValueError, ArithmeticError):
                pass

        if "t_anchor_date" in overrides:
            applied["t_anchor_date"] = overrides["t_anchor_date"]

        # Build context.
        metrics = self.sla_repo.list_metrics(sla.id)
        parameters = self.sla_repo.list_parameters(sla.id)
        bands = self.sla_repo.list_bands(sla.id)
        lookup_rows = self.sla_repo.list_lookup_rows(sla.id)
        guards = self.sla_repo.list_guards(sla.id)

        ctx = EvaluationContext(
            mapping=mapping,
            sla=sla,
            formula_type=formula_type,
            metrics=metrics,
            parameters=parameters,
            bands=bands,
            lookup_rows=lookup_rows,
            guards=guards,
            period_start=resolved_start,
            period_end=resolved_end,
            ld_base_amount=resolved_ld_base,
            observations=observations,
            overrides_applied=applied,
        )

        evaluator = _EVALUATORS.get(formula_type)
        if evaluator is None:
            raise ValidationError(
                f"No evaluator registered for formula_type '{formula_type}'.",
                code="no_evaluator",
            )

        result: EvaluatedResult = evaluator.evaluate(ctx)

        return MappingEvaluationResponse(
            mapping_id=mapping.id,
            activity_id=mapping.activity_id,
            sla_id=sla.id,
            sla_ref=sla.sla_ref,
            contract_type=sla.contract_type,
            formula_type=formula_type,
            period_start=resolved_start,
            period_end=resolved_end,
            severity_level=result.severity_level,
            accumulated_points=result.accumulated_points,
            ld_percent=result.ld_percent,
            ld_amount=result.ld_amount,
            breaches=result.breaches,
            guards=result.guards,
            notes=result.notes,
            overrides_applied=applied,
        )

    def _resolve_period_for_activity(
        self,
        payload: ActivityEvaluationRequest,
        rows: List,
    ) -> tuple[date, date]:
        if payload.period_start and payload.period_end:
            return payload.period_start, payload.period_end
        if rows:
            mapping = rows[0][0]
            start = payload.period_start or mapping.effective_from
            end = payload.period_end or (mapping.effective_until or _ninety_days_after(start))
            return start, end
        today = date.today()
        return today, today


def _parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _ninety_days_after(d: date) -> date:
    from datetime import timedelta
    return d + timedelta(days=89)
