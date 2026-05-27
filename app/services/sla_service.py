"""SlaService — business logic for SLA definitions."""
from __future__ import annotations

import copy
from datetime import datetime
from typing import List, Optional, Tuple
from uuid import uuid4

import yaml
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, DslParseError, ProjectLdConfigNotFoundError, SlaNotFoundError
from app.models.sla_asl_snapshot import SlaAslSnapshot
from app.models.sla_condition_band import SlaConditionBand
from app.models.sla_definition import SlaDefinition
from app.models.sla_dsl_version import SlaDslVersion
from app.models.sla_guard_condition import SlaGuardCondition
from app.models.sla_lookup_row import SlaLookupRow
from app.models.sla_metric import SlaMetric
from app.models.sla_parameter_value import SlaParameterValue
from app.repositories.project_ld_config_repository import ProjectLdConfigRepository
from app.repositories.sla_repository import SlaRepository
from app.schemas.sla import SlaCreateFromTemplateRequest, SlaCreateRequest, SlaUpdateRequest
from app.services import dsl_parser
from app.services.dsl_parser import PARSER_VERSION, ParsedDSL


class SlaService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = SlaRepository(db)
        self.project_repo = ProjectLdConfigRepository(db)

    # ---------------------------------------------------------------- read

    def get_by_id(self, project_id: str, sla_id: str) -> SlaDefinition:
        self._require_project(project_id)
        sla = self.repo.get_by_id(sla_id)
        if sla is None or sla.project_id != project_id:
            raise SlaNotFoundError(f"SLA '{sla_id}' not found on project '{project_id}'")
        return sla

    def list_for_project(
        self,
        project_id: str,
        *,
        status: Optional[str] = None,
        milestone_id: Optional[str] = None,
        activity_id: Optional[str] = None,
    ) -> List[Tuple[SlaDefinition, str]]:
        self._require_project(project_id)
        return self.repo.list_for_project(
            project_id, status=status, milestone_id=milestone_id, activity_id=activity_id
        )

    # ---------------------------------------------------------------- create from DSL

    def create(
        self,
        project_id: str,
        payload: SlaCreateRequest,
        *,
        caller_user_id: Optional[str],
    ) -> SlaDefinition:
        self._require_project(project_id)
        parsed = dsl_parser.parse(payload.dsl)
        return self._persist_new(
            project_id=project_id,
            parsed=parsed,
            dsl_text=payload.dsl,
            effective_from=payload.effective_from,
            effective_until=payload.effective_until,
            milestone_id=payload.milestone_id,
            activity_id=payload.activity_id,
            change_reason=payload.change_reason,
            caller_user_id=caller_user_id,
        )

    # ---------------------------------------------------------------- create from template

    def create_from_template(
        self,
        project_id: str,
        payload: SlaCreateFromTemplateRequest,
        *,
        caller_user_id: Optional[str],
    ) -> SlaDefinition:
        self._require_project(project_id)
        tmpl = self.repo.get_template_by_ref(payload.template_ref)
        if tmpl is None:
            raise SlaNotFoundError(f"Template '{payload.template_ref}' not found")

        base = yaml.safe_load(tmpl.default_dsl) or {}
        base.update(payload.overrides)
        merged_dsl = yaml.dump(base, default_flow_style=False, allow_unicode=True)

        parsed = dsl_parser.parse(merged_dsl)
        return self._persist_new(
            project_id=project_id,
            parsed=parsed,
            dsl_text=merged_dsl,
            effective_from=payload.effective_from,
            effective_until=payload.effective_until,
            milestone_id=payload.milestone_id,
            activity_id=payload.activity_id,
            change_reason=payload.change_reason or f"Instantiated from template {payload.template_ref}",
            caller_user_id=caller_user_id,
        )

    # ---------------------------------------------------------------- update (new DSL version)

    def update(
        self,
        project_id: str,
        sla_id: str,
        payload: SlaUpdateRequest,
        *,
        caller_user_id: Optional[str],
    ) -> SlaDefinition:
        sla = self.get_by_id(project_id, sla_id)
        parsed = dsl_parser.parse(payload.dsl)

        if parsed.sla_ref != sla.sla_ref:
            raise DslParseError(
                f"Cannot change sla_ref via update. "
                f"Existing: '{sla.sla_ref}', DSL has: '{parsed.sla_ref}'"
            )

        formula = self.repo.get_formula_by_type(parsed.formula_type)
        if formula is None:
            raise DslParseError(f"Unknown formula type '{parsed.formula_type}'")
        if formula.requires_bands and not parsed.bands:
            raise DslParseError(f"Formula '{parsed.formula_type}' requires 'bands' but none were provided")
        if formula.requires_lookup and not parsed.lookup_table:
            raise DslParseError(f"Formula '{parsed.formula_type}' requires 'lookup_table' but none was provided")
        schema_required = (formula.parameter_schema or {}).get("required", [])
        missing_params = [k for k in schema_required if k not in parsed.parameters]
        if missing_params:
            raise DslParseError(
                f"Formula '{parsed.formula_type}' requires parameters: " + ", ".join(missing_params)
            )

        for model in (SlaMetric, SlaGuardCondition, SlaParameterValue, SlaConditionBand, SlaLookupRow):
            self.db.execute(delete(model).where(model.sla_id == sla_id))

        self.repo.retire_current_asl(sla_id)

        asl = copy.deepcopy(parsed.asl_json)
        asl["sla_id"] = sla_id

        new_version = sla.dsl_version + 1
        self.repo.bulk_add(self._build_sub_rows(sla_id, parsed))

        dsl_row = SlaDslVersion(
            id=str(uuid4()), sla_id=sla_id, version=new_version,
            dsl_text=payload.dsl, change_reason=payload.change_reason, authored_by=caller_user_id,
        )
        self.db.add(dsl_row)
        self.db.flush()

        self.db.add(SlaAslSnapshot(
            id=str(uuid4()), sla_id=sla_id, dsl_version_id=dsl_row.id,
            asl_json=asl, parser_version=PARSER_VERSION, is_current=True,
        ))

        sla.title = parsed.title
        sla.description = parsed.description
        sla.measurement_interval = parsed.measurement_interval
        sla.reporting_interval = parsed.reporting_interval
        sla.baseline_type = parsed.baseline_type
        sla.compound_metric_rule = parsed.compound_metric_rule
        sla.ld_aggregation_method = parsed.ld_aggregation_method
        sla.ld_computation_base = parsed.ld_computation_base
        sla.dsl_source = payload.dsl
        sla.dsl_version = new_version
        sla.updated_at = datetime.utcnow()

        self.db.flush()
        self.db.refresh(sla)
        return sla

    # ---------------------------------------------------------------- DSL / ASL reads

    def get_dsl_text(self, project_id: str, sla_id: str) -> str:
        sla = self.get_by_id(project_id, sla_id)
        dsl_row = self.repo.get_current_dsl(sla_id, sla.dsl_version)
        return dsl_row.dsl_text if dsl_row else (sla.dsl_source or "")

    def get_asl(self, project_id: str, sla_id: str) -> dict:
        self.get_by_id(project_id, sla_id)
        snap = self.repo.get_current_asl(sla_id)
        return snap.asl_json if snap else {}

    # ---------------------------------------------------------------- templates

    def list_templates(self, *, applicable_to: Optional[str] = None):
        return self.repo.list_templates(applicable_to=applicable_to)

    # ---------------------------------------------------------------- internals

    def _require_project(self, project_id: str):
        if self.project_repo.get_by_project_id(project_id) is None:
            raise ProjectLdConfigNotFoundError(
                f"No LD config found for project '{project_id}'. "
                f"Create one first via POST /api/v3/projects/{project_id}/ld-config"
            )

    def _persist_new(
        self,
        *,
        project_id: str,
        parsed: ParsedDSL,
        dsl_text: str,
        effective_from,
        effective_until,
        milestone_id,
        activity_id,
        change_reason,
        caller_user_id,
    ) -> SlaDefinition:
        if self.repo.get_by_ref(project_id, parsed.sla_ref) is not None:
            raise ConflictError(
                f"SLA ref '{parsed.sla_ref}' already exists on project '{project_id}'",
                code="duplicate_sla_ref",
            )

        formula = self.repo.get_formula_by_type(parsed.formula_type)
        if formula is None:
            raise DslParseError(f"Unknown formula type '{parsed.formula_type}'")
        if formula.requires_bands and not parsed.bands:
            raise DslParseError(f"Formula '{parsed.formula_type}' requires 'bands' but none were provided")
        if formula.requires_lookup and not parsed.lookup_table:
            raise DslParseError(f"Formula '{parsed.formula_type}' requires 'lookup_table' but none was provided")
        schema_required = (formula.parameter_schema or {}).get("required", [])
        missing_params = [k for k in schema_required if k not in parsed.parameters]
        if missing_params:
            raise DslParseError(
                f"Formula '{parsed.formula_type}' requires parameters: " + ", ".join(missing_params)
            )

        sla_id = str(uuid4())
        sla = SlaDefinition(
            id=sla_id,
            project_id=project_id,
            milestone_id=milestone_id,
            activity_id=activity_id,
            formula_id=formula.id,
            sla_ref=parsed.sla_ref,
            title=parsed.title,
            description=parsed.description,
            measurement_interval=parsed.measurement_interval,
            reporting_interval=parsed.reporting_interval,
            baseline_type=parsed.baseline_type,
            compound_metric_rule=parsed.compound_metric_rule,
            ld_aggregation_method=parsed.ld_aggregation_method,
            ld_computation_base=parsed.ld_computation_base,
            metadata_={},
            status="ACTIVE",
            effective_from=effective_from,
            effective_until=effective_until,
            dsl_source=dsl_text,
            dsl_version=1,
            created_by=caller_user_id,
        )
        self.repo.create(sla)

        asl = copy.deepcopy(parsed.asl_json)
        asl["sla_id"] = sla_id

        self.repo.bulk_add(self._build_sub_rows(sla_id, parsed))

        dsl_row = SlaDslVersion(
            id=str(uuid4()), sla_id=sla_id, version=1,
            dsl_text=dsl_text, change_reason=change_reason, authored_by=caller_user_id,
        )
        self.db.add(dsl_row)
        self.db.flush()

        self.db.add(SlaAslSnapshot(
            id=str(uuid4()), sla_id=sla_id, dsl_version_id=dsl_row.id,
            asl_json=asl, parser_version=PARSER_VERSION, is_current=True,
        ))
        self.db.flush()
        self.db.refresh(sla)
        return sla

    @staticmethod
    def _build_sub_rows(sla_id: str, parsed: ParsedDSL) -> list:
        rows: list = []
        for m in parsed.metrics:
            rows.append(SlaMetric(
                id=str(uuid4()), sla_id=sla_id, metric_key=m.key,
                display_name=m.display_name, unit=m.unit,
                target_numeric=m.target_numeric, target_date=m.target_date,
                direction=m.direction, is_primary=m.is_primary,
            ))
        for g in parsed.guard_conditions:
            rows.append(SlaGuardCondition(
                id=str(uuid4()), sla_id=sla_id, metric_key=g.metric_key,
                operator=g.operator, threshold_value=g.threshold_value,
                threshold_unit=g.threshold_unit, action=g.action,
                action_description=g.action_description, guard_group_id=g.guard_group_id,
            ))
        for k, v in parsed.parameters.items():
            rows.append(SlaParameterValue(
                id=str(uuid4()), sla_id=sla_id, param_key=k, param_value=v,
            ))
        for b in parsed.bands:
            rows.append(SlaConditionBand(
                id=str(uuid4()), sla_id=sla_id, metric_key=b.metric_key,
                band_label=b.band_label, range_min=b.range_min, range_max=b.range_max,
                range_unit=b.range_unit, rate_percent=b.rate_percent,
                points_contribution=b.points_contribution, fixed_amount=b.fixed_amount,
                sort_order=b.sort_order, band_group_id=b.band_group_id,
            ))
        for lr in parsed.lookup_table:
            rows.append(SlaLookupRow(
                id=str(uuid4()), sla_id=sla_id,
                lookup_key=lr.lookup_key, lookup_value=lr.lookup_value, sort_order=lr.sort_order,
            ))
        return rows
