"""SlaEvaluatorService — loads a mapping's context, dispatches to the right
per-formula evaluator, and returns a typed response.

Activity-level evaluate fans out to every active mapping on that activity.

Project-scoped scoring (severity_master, project_ld_bands) is resolved once
per evaluate() call: we ask pmis-project-management for the activity's
``project_id``, then load the two master tables from this service's own DB.
If project-management is unreachable, evaluation continues with the RFP
defaults baked into the per-formula evaluators.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.clients import ProjectManagementClient, ProjectManagementUnavailable
from app.core.errors import NotFoundError, ValidationError
from app.models.sla_activity_mapping import SlaActivityMapping
from app.models.sla_definition import SlaDefinition
from app.repositories.master_repository import MasterRepository
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
    ScoringSource,
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
    def __init__(
        self,
        db: Session,
        project_mgmt_client: Optional[ProjectManagementClient] = None,
    ):
        self.db = db
        self.mapping_repo = SlaActivityMappingRepository(db)
        self.sla_repo = SlaRepository(db)
        self.master_repo = MasterRepository(db)
        self.project_mgmt_client = project_mgmt_client

    # ------------------------------------------------------------------ public

    def evaluate_mapping(
        self,
        mapping_id: str,
        payload: MappingEvaluationRequest,
        bearer_token: Optional[str] = None,
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

        scoring = self._resolve_project_scoring(mapping.activity_id, bearer_token)
        return self._evaluate(
            mapping=mapping,
            sla=sla,
            formula_type=formula_type,
            period_start=payload.period_start,
            period_end=payload.period_end,
            observations=payload.metric_observations,
            scoring=scoring,
        )

    def evaluate_activity(
        self,
        activity_id: str,
        payload: ActivityEvaluationRequest,
        bearer_token: Optional[str] = None,
    ) -> ActivityEvaluationResponse:
        rows = self.mapping_repo.list_for_activity(activity_id, active_only=True)
        period_start, period_end = self._resolve_period_for_activity(payload, rows)

        # Resolve project scoring ONCE for the activity — all its mappings
        # share the same activity_id → same project_id → same severity_master.
        # Avoids N round-trips to project-management for a fan-out evaluate.
        scoring = self._resolve_project_scoring(activity_id, bearer_token)

        mapping_results: List[MappingEvaluationResponse] = []
        skipped = 0
        # Roll up severity counts so the FE can show "L4 × 2, L2 × 1" at a
        # glance without iterating mapping_results client-side.
        severity_breakdown: Dict[str, int] = {}
        for mapping, sla, formula_type in rows:
            if formula_type is None:
                skipped += 1
                continue
            observations = payload.observations_by_sla_ref.get(sla.sla_ref, [])
            try:
                single = self._evaluate(
                    mapping=mapping,
                    sla=sla,
                    formula_type=formula_type,
                    period_start=payload.period_start,
                    period_end=payload.period_end,
                    observations=observations,
                    scoring=scoring,
                )
            except ValidationError:
                skipped += 1
                continue
            mapping_results.append(single)
            if single.severity_level is not None:
                key = f"L{single.severity_level}"
                severity_breakdown[key] = severity_breakdown.get(key, 0) + 1

        return ActivityEvaluationResponse(
            activity_id=activity_id,
            period_start=period_start,
            period_end=period_end,
            mapping_results=mapping_results,
            summary={
                "mappings_evaluated": len(mapping_results),
                "mappings_skipped": skipped,
                "severity_breakdown": severity_breakdown,
                "project_id": scoring["project_id"],
                "severity_master_source": scoring["severity_master_source"],
            },
        )

    # ------------------------------------------------------------------ project scoring

    def _resolve_project_scoring(
        self, activity_id: str, bearer_token: Optional[str]
    ) -> Dict[str, Any]:
        """Resolve project_id for an activity and load its severity_master.

        Returns a dict ready to splice into EvaluationContext and the response::

            {
                "project_id": Optional[str],
                "level_points_map": Optional[Dict[int, Decimal]],
                "severity_master_source": "project" | "default" | "unavailable",
            }

        The three sources mean:
          * ``project``      — table had rows, evaluator will use them.
          * ``default``      — project was resolved but had no rows, RFP defaults.
          * ``unavailable``  — project-management was down or the activity is
                               unknown there; we don't know the project so we
                               also fall back to RFP defaults.

        project_ld_bands is intentionally not loaded here — LD computation
        lives in the dedicated LD API.
        """
        result: Dict[str, Any] = {
            "project_id": None,
            "level_points_map": None,
            "severity_master_source": "default",
        }

        if self.project_mgmt_client is None:
            return result

        try:
            project_id = self.project_mgmt_client.get_activity_project_id(
                activity_id, bearer_token=bearer_token,
            )
        except ProjectManagementUnavailable:
            result["severity_master_source"] = "unavailable"
            return result

        if not project_id:
            # Activity unknown to project-management. Same outcome as upstream
            # being down: defaults, but flagged so the FE can show it.
            result["severity_master_source"] = "unavailable"
            return result

        result["project_id"] = project_id
        level_map = self._build_level_points_map(project_id)
        if level_map:
            result["level_points_map"] = level_map
            result["severity_master_source"] = "project"
        return result

    def _build_level_points_map(
        self, project_id: str
    ) -> Optional[Dict[int, Decimal]]:
        rows = self.master_repo.list_for_project(project_id)
        if not rows:
            return None
        return {row.level: Decimal(row.points) for row in rows}

    # ------------------------------------------------------------------ internal

    def _evaluate(
        self,
        *,
        mapping: SlaActivityMapping,
        sla: SlaDefinition,
        formula_type: str,
        period_start: Optional[date],
        period_end: Optional[date],
        observations: List[MetricObservation],
        scoring: Dict[str, Any],
    ) -> MappingEvaluationResponse:
        # Resolve the reporting period from request → overrides → mapping
        # defaults. ld_base_amount is NOT read here — it's an LD concern.
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
            from datetime import timedelta
            resolved_end = resolved_start + timedelta(days=89)
            applied["resolved_end_default"] = str(resolved_end)
        elif period_end is None and overrides.get("actual_end_date"):
            applied["actual_end_date"] = str(resolved_end)

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
            observations=observations,
            overrides_applied=applied,
            project_id=scoring["project_id"],
            level_points_map=scoring["level_points_map"],
        )

        evaluator = _EVALUATORS.get(formula_type)
        if evaluator is None:
            raise ValidationError(
                f"No evaluator registered for formula_type '{formula_type}'.",
                code="no_evaluator",
            )

        result: EvaluatedResult = evaluator.evaluate(ctx)

        sev_source: ScoringSource = scoring["severity_master_source"]

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
            project_id=scoring["project_id"],
            severity_master_source=sev_source,
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
