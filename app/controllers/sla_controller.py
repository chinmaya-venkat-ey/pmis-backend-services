"""SlaController — orchestrates SlaService, shapes wire responses."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.schemas.sla import (
    SlaCreateFromTemplateRequest,
    SlaCreateRequest,
    SlaDetailResponse,
    SlaResponse,
    SlaUpdateRequest,
    TemplateResponse,
)
from app.services.sla_service import SlaService


class SlaController:
    def __init__(self, db: Session):
        self.service = SlaService(db)
        self.repo = self.service.repo

    # ---------------------------------------------------------------- SLA CRUD

    def get(self, project_id: str, sla_id: str) -> SlaDetailResponse:
        sla, formula_type = self._get_with_formula(project_id, sla_id)
        return self._to_detail(sla, formula_type)

    def list_(
        self,
        project_id: str,
        *,
        status: Optional[str] = None,
        milestone_id: Optional[str] = None,
        activity_id: Optional[str] = None,
    ) -> List[SlaResponse]:
        rows = self.service.list_for_project(
            project_id, status=status, milestone_id=milestone_id, activity_id=activity_id
        )
        return [self._to_flat(sla, ft) for sla, ft in rows]

    def create(
        self, project_id: str, payload: SlaCreateRequest, *, caller_user_id: Optional[str]
    ) -> SlaDetailResponse:
        sla = self.service.create(project_id, payload, caller_user_id=caller_user_id)
        _, formula_type = self._get_with_formula(project_id, sla.id)
        return self._to_detail(sla, formula_type)

    def create_from_template(
        self,
        project_id: str,
        payload: SlaCreateFromTemplateRequest,
        *,
        caller_user_id: Optional[str],
    ) -> SlaDetailResponse:
        sla = self.service.create_from_template(project_id, payload, caller_user_id=caller_user_id)
        _, formula_type = self._get_with_formula(project_id, sla.id)
        return self._to_detail(sla, formula_type)

    def update(
        self,
        project_id: str,
        sla_id: str,
        payload: SlaUpdateRequest,
        *,
        caller_user_id: Optional[str],
    ) -> SlaDetailResponse:
        sla = self.service.update(project_id, sla_id, payload, caller_user_id=caller_user_id)
        _, formula_type = self._get_with_formula(project_id, sla.id)
        return self._to_detail(sla, formula_type)

    def get_dsl(self, project_id: str, sla_id: str) -> str:
        return self.service.get_dsl_text(project_id, sla_id)

    def get_asl(self, project_id: str, sla_id: str) -> Dict[str, Any]:
        return self.service.get_asl(project_id, sla_id)

    # ---------------------------------------------------------------- templates

    def list_templates(self, *, applicable_to: Optional[str] = None) -> List[TemplateResponse]:
        rows = self.service.list_templates(applicable_to=applicable_to)
        return [
            TemplateResponse(
                id=tmpl.id, template_ref=tmpl.template_ref, title=tmpl.title,
                description=tmpl.description, formula_id=tmpl.formula_id,
                formula_type=ft, applicable_to=tmpl.applicable_to or [], is_active=tmpl.is_active,
            )
            for tmpl, ft in rows
        ]

    # ---------------------------------------------------------------- response shaping

    def _get_with_formula(self, project_id: str, sla_id: str):
        from app.models.formula_library import FormulaLibrary
        from sqlalchemy import select
        sla = self.repo.get_by_id(sla_id)
        formula = self.service.db.execute(
            select(FormulaLibrary).where(FormulaLibrary.id == sla.formula_id)
        ).scalar_one_or_none()
        return sla, (formula.formula_type if formula else None)

    def _to_flat(self, sla, formula_type: Optional[str]) -> SlaResponse:
        return SlaResponse(
            id=sla.id,
            project_id=sla.project_id,
            milestone_id=sla.milestone_id,
            activity_id=sla.activity_id,
            formula_id=sla.formula_id,
            formula_type=formula_type,
            sla_ref=sla.sla_ref,
            title=sla.title,
            description=sla.description,
            measurement_interval=sla.measurement_interval,
            reporting_interval=sla.reporting_interval,
            baseline_type=sla.baseline_type,
            compound_metric_rule=sla.compound_metric_rule,
            ld_aggregation_method=sla.ld_aggregation_method,
            ld_computation_base=sla.ld_computation_base,
            status=sla.status,
            effective_from=sla.effective_from,
            effective_until=sla.effective_until,
            dsl_version=sla.dsl_version,
            created_by=sla.created_by,
            created_at=sla.created_at,
            updated_at=sla.updated_at,
        )

    def _to_detail(self, sla, formula_type: Optional[str]) -> SlaDetailResponse:
        from app.schemas.sla import (
            ConditionBandResponse, GuardConditionResponse,
            LookupRowResponse, MetricResponse,
        )
        sla_id = sla.id
        metrics = [MetricResponse.model_validate(m) for m in self.repo.get_metrics(sla_id)]
        guards = [GuardConditionResponse.model_validate(g) for g in self.repo.get_guards(sla_id)]
        params = {p.param_key: p.param_value for p in self.repo.get_parameters(sla_id)}
        bands = [ConditionBandResponse.model_validate(b) for b in self.repo.get_bands(sla_id)]
        lookups = [LookupRowResponse.model_validate(r) for r in self.repo.get_lookup_rows(sla_id)]
        dsl_row = self.repo.get_current_dsl(sla_id, sla.dsl_version)
        asl_snap = self.repo.get_current_asl(sla_id)
        return SlaDetailResponse(
            **self._to_flat(sla, formula_type).model_dump(),
            parameters=params,
            metrics=metrics,
            guard_conditions=guards,
            bands=bands,
            lookup_table=lookups,
            current_dsl=dsl_row.dsl_text if dsl_row else sla.dsl_source,
            current_asl=asl_snap.asl_json if asl_snap else None,
        )
