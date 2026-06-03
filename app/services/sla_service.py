"""SlaService — business logic for SLA master onboarding, DSL generation, and retrieval."""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

import yaml
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.sla_condition_band import SlaConditionBand
from app.models.sla_definition import SlaDefinition
from app.models.sla_guard_condition import SlaGuardCondition
from app.models.sla_lookup_row import SlaLookupRow
from app.models.sla_metric import SlaMetric
from app.models.sla_parameter_value import SlaParameterValue
from app.repositories.master_repository import MasterRepository
from app.repositories.sla_repository import SlaRepository
from app.schemas.sla import (
    SlaConditionBandResponse,
    SlaDefinitionResponse,
    SlaDetailResponse,
    SlaDslResponse,
    SlaGuardConditionResponse,
    SlaLookupRowResponse,
    SlaMetricResponse,
    SlaOnboardRequest,
    SlaOnboardResponse,
    SlaParameterResponse,
    SlaUpdateRequest,
)


# ---------------------------------------------------------------------------
# DSL generator
# ---------------------------------------------------------------------------

def _decimal_str(v: Optional[Decimal]) -> Optional[str]:
    return str(v) if v is not None else None


def _generate_dsl(
    defn: SlaDefinition,
    formula_type: str,
    metrics: List[SlaMetric],
    parameters: List[SlaParameterValue],
    bands: List[SlaConditionBand],
    lookup_rows: List[SlaLookupRow],
    guards: List[SlaGuardCondition],
) -> str:
    data = {
        "sla_ref": defn.sla_ref,
        "title": defn.title,
        "description": defn.description,
        "contract_type": defn.contract_type,
        "formula_type": formula_type,
        "measurement_interval": defn.measurement_interval,
        "reporting_interval": defn.reporting_interval,
        "baseline_type": defn.baseline_type,
        "compound_metric_rule": defn.compound_metric_rule,
        "ld_aggregation_method": defn.ld_aggregation_method,
        "ld_computation_base": defn.ld_computation_base,
        "effective_from": str(defn.effective_from),
        "effective_until": str(defn.effective_until) if defn.effective_until else None,
        "metrics": [
            {
                "metric_key": m.metric_key,
                "display_name": m.display_name,
                "unit": m.unit,
                "target_numeric": _decimal_str(m.target_numeric),
                "target_date": str(m.target_date) if m.target_date else None,
                "direction": m.direction,
                "is_primary": m.is_primary,
            }
            for m in metrics
        ],
        "parameters": [
            {"param_key": p.param_key, "param_value": p.param_value}
            for p in parameters
        ],
        "condition_bands": [
            {
                "metric_key": b.metric_key,
                "band_label": b.band_label,
                "range_min": _decimal_str(b.range_min),
                "range_max": _decimal_str(b.range_max),
                "range_unit": b.range_unit,
                "severity_level": b.severity_level,
                "rate_percent": _decimal_str(b.rate_percent),
                "points_contribution": _decimal_str(b.points_contribution),
                "fixed_amount": _decimal_str(b.fixed_amount),
                "band_group_id": b.band_group_id,
                "sort_order": b.sort_order,
            }
            for b in bands
        ],
        "lookup_table": [
            {
                "lookup_key": r.lookup_key,
                "lookup_value": _decimal_str(r.lookup_value),
                "sort_order": r.sort_order,
            }
            for r in lookup_rows
        ],
        "guard_conditions": [
            {
                "metric_key": g.metric_key,
                "operator": g.operator,
                "threshold_value": _decimal_str(g.threshold_value),
                "threshold_unit": g.threshold_unit,
                "action": g.action,
                "action_description": g.action_description,
                "guard_group_id": g.guard_group_id,
            }
            for g in guards
        ],
    }
    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class SlaService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = SlaRepository(db)
        self.master_repo = MasterRepository(db)

    # ---------------------------------------------------------------- helpers

    def _build_detail(
        self,
        defn: SlaDefinition,
        formula_type: str,
        metrics: List[SlaMetric],
        params: List[SlaParameterValue],
        bands: List[SlaConditionBand],
        lookup_rows: List[SlaLookupRow],
        guards: List[SlaGuardCondition],
    ) -> SlaDetailResponse:
        return SlaDetailResponse(
            id=defn.id,
            contract_type=defn.contract_type,
            formula_type=formula_type,
            sla_ref=defn.sla_ref,
            title=defn.title,
            description=defn.description,
            measurement_interval=defn.measurement_interval,
            reporting_interval=defn.reporting_interval,
            baseline_type=defn.baseline_type,
            compound_metric_rule=defn.compound_metric_rule,
            ld_aggregation_method=defn.ld_aggregation_method,
            ld_computation_base=defn.ld_computation_base,
            status=defn.status,
            effective_from=defn.effective_from,
            effective_until=defn.effective_until,
            dsl_version=defn.dsl_version,
            metadata=defn.metadata_ or {},
            created_at=defn.created_at,
            updated_at=defn.updated_at,
            metrics=[SlaMetricResponse.model_validate(m) for m in metrics],
            parameters=[SlaParameterResponse.model_validate(p) for p in params],
            condition_bands=[SlaConditionBandResponse.model_validate(b) for b in bands],
            lookup_table=[SlaLookupRowResponse.model_validate(r) for r in lookup_rows],
            guard_conditions=[SlaGuardConditionResponse.model_validate(g) for g in guards],
        )

    def _build_flat(self, defn: SlaDefinition, formula_type: str) -> SlaDefinitionResponse:
        return SlaDefinitionResponse(
            id=defn.id,
            contract_type=defn.contract_type,
            formula_type=formula_type,
            sla_ref=defn.sla_ref,
            title=defn.title,
            description=defn.description,
            measurement_interval=defn.measurement_interval,
            reporting_interval=defn.reporting_interval,
            baseline_type=defn.baseline_type,
            compound_metric_rule=defn.compound_metric_rule,
            ld_aggregation_method=defn.ld_aggregation_method,
            ld_computation_base=defn.ld_computation_base,
            status=defn.status,
            effective_from=defn.effective_from,
            effective_until=defn.effective_until,
            dsl_version=defn.dsl_version,
            created_at=defn.created_at,
            updated_at=defn.updated_at,
        )

    # ---------------------------------------------------------------- seed defaults

    def seed_default_slas(
        self,
        contract_types: Optional[List[str]] = None,
        created_by: Optional[str] = None,
    ) -> dict:
        """Idempotent fan-out onboarding of RFP-default SLAs.

        Reads payloads from ``app.seed_data.sla_master_seeds`` and pushes each
        through ``create_from_form``. SLAs that already exist (matched by
        ``sla_ref`` or by ``(contract_type, title)``) are skipped — neither
        a re-run nor a partial seed should produce duplicate rows or errors.

        Args:
            contract_types: filter to only these codes (BSP / MSAP / MSIP / PMU).
                None = seed everything in the bundle.

        Returns:
            {"seeded": N, "skipped_existing": M, "failed": [{sla_ref, error}, ...]}
        """
        from app.seed_data import ALL_SEED_SLAS, SEEDS_BY_CONTRACT
        from app.schemas.sla import SlaOnboardRequest

        # Pick the seed list. Unknown contract codes are tolerated — they just
        # contribute zero rows. "ALL" / "*" tokens (case-insensitive) expand to
        # every contract type the server knows about, equivalent to omitting
        # the filter — provided so callers can be explicit instead of relying
        # on the "empty list = all" default that's easy to misread.
        if contract_types:
            wanted = {c.strip().upper() for c in contract_types if c and c.strip()}
            if "ALL" in wanted or "*" in wanted or not wanted:
                payloads = list(ALL_SEED_SLAS)
            else:
                payloads = [p for ct, lst in SEEDS_BY_CONTRACT.items() if ct in wanted for p in lst]
        else:
            payloads = list(ALL_SEED_SLAS)

        seeded = 0
        skipped = 0
        failed: List[dict] = []
        for raw in payloads:
            try:
                req = SlaOnboardRequest(**raw)
            except Exception as exc:  # pragma: no cover — defensive
                failed.append({"sla_ref": raw.get("sla_ref"), "error": f"schema: {exc}"})
                continue
            try:
                self.create_from_form(req, created_by=created_by)
                seeded += 1
            except ConflictError:
                # Already onboarded — fine. The whole point of a seeder is to
                # be safe to run twice.
                skipped += 1
            except Exception as exc:
                failed.append({"sla_ref": raw.get("sla_ref"), "error": str(exc)})

        return {
            "seeded": seeded,
            "skipped_existing": skipped,
            "failed": failed,
            "total_candidates": len(payloads),
        }

    # ---------------------------------------------------------------- create

    def create_from_form(
        self, payload: SlaOnboardRequest, created_by: Optional[str] = None
    ) -> SlaOnboardResponse:
        # Validate formula exists
        formula = self.master_repo.get_formula_by_type(payload.formula_type)
        if formula is None:
            raise ValidationError(
                f"Formula type '{payload.formula_type}' not found in formula_library",
                code="unknown_formula_type",
            )

        # Validate sla_ref uniqueness
        if self.repo.get_by_ref(payload.sla_ref) is not None:
            raise ConflictError(
                f"SLA with ref '{payload.sla_ref}' already exists",
                code="duplicate_sla_ref",
            )

        # Duplicate check 1 — same title in same contract_type
        if self.repo.find_by_title_and_contract_type(payload.contract_type, payload.title) is not None:
            raise ConflictError(
                f"An SLA with title '{payload.title}' already exists for contract_type '{payload.contract_type}'",
                code="duplicate_sla_title",
            )

        # Formula-specific validation
        if formula.requires_bands and not payload.condition_bands:
            raise ValidationError(
                f"Formula '{payload.formula_type}' requires at least one condition_band",
                code="missing_condition_bands",
            )
        if formula.requires_lookup and not payload.lookup_table:
            raise ValidationError(
                f"Formula '{payload.formula_type}' requires at least one lookup_table row",
                code="missing_lookup_table",
            )

        # Validate metric_key uniqueness within request
        metric_keys = [m.metric_key for m in payload.metrics]
        if len(metric_keys) != len(set(metric_keys)):
            raise ValidationError("Duplicate metric_key values in metrics", code="duplicate_metric_key")

        # Validate param_key uniqueness
        param_keys = [p.param_key for p in payload.parameters]
        if len(param_keys) != len(set(param_keys)):
            raise ValidationError("Duplicate param_key values in parameters", code="duplicate_param_key")

        # Create definition
        defn = SlaDefinition(
            project_id=None,
            contract_type=payload.contract_type,
            formula_id=formula.id,
            sla_ref=payload.sla_ref,
            title=payload.title,
            description=payload.description,
            measurement_interval=payload.measurement_interval,
            reporting_interval=payload.reporting_interval,
            baseline_type=payload.baseline_type,
            compound_metric_rule=payload.compound_metric_rule,
            ld_aggregation_method=payload.ld_aggregation_method,
            ld_computation_base=payload.ld_computation_base,
            metadata_=payload.metadata,
            status="ACTIVE",
            effective_from=payload.effective_from,
            effective_until=payload.effective_until,
            dsl_version=1,
            created_by=created_by,
        )
        defn = self.repo.create_definition(defn)
        sla_id = defn.id

        # Create sub-tables
        metrics = self.repo.bulk_add_metrics([
            SlaMetric(
                sla_id=sla_id,
                metric_key=m.metric_key,
                display_name=m.display_name,
                unit=m.unit,
                target_numeric=m.target_numeric,
                target_date=m.target_date,
                direction=m.direction,
                is_primary=m.is_primary,
            )
            for m in payload.metrics
        ])

        params = self.repo.bulk_add_parameters([
            SlaParameterValue(
                sla_id=sla_id,
                param_key=p.param_key,
                param_value=p.param_value,
            )
            for p in payload.parameters
        ])

        bands = self.repo.bulk_add_bands([
            SlaConditionBand(
                sla_id=sla_id,
                metric_key=b.metric_key,
                band_label=b.band_label,
                range_min=b.range_min,
                range_max=b.range_max,
                range_unit=b.range_unit,
                severity_level=b.severity_level,
                rate_percent=b.rate_percent,
                points_contribution=b.points_contribution,
                fixed_amount=b.fixed_amount,
                band_group_id=b.band_group_id,
                sort_order=b.sort_order,
            )
            for b in payload.condition_bands
        ])

        lookup_rows = self.repo.bulk_add_lookup_rows([
            SlaLookupRow(
                sla_id=sla_id,
                lookup_key=r.lookup_key,
                lookup_value=r.lookup_value,
                sort_order=r.sort_order,
            )
            for r in payload.lookup_table
        ])

        guards = self.repo.bulk_add_guards([
            SlaGuardCondition(
                sla_id=sla_id,
                metric_key=g.metric_key,
                operator=g.operator,
                threshold_value=g.threshold_value,
                threshold_unit=g.threshold_unit,
                action=g.action,
                action_description=g.action_description,
                guard_group_id=g.guard_group_id,
            )
            for g in payload.guard_conditions
        ])

        # Generate and store DSL
        dsl_text = _generate_dsl(defn, formula.formula_type, metrics, params, bands, lookup_rows, guards)
        self.repo.update_dsl(defn, dsl_text, 1)

        # Similar SLA warning — same contract_type + formula_type (non-blocking)
        similar_rows = self.repo.find_similar_by_formula(
            payload.contract_type, formula.formula_type, defn.id
        )
        similar_slas = [self._build_flat(d, ft) for d, ft in similar_rows]

        detail = self._build_detail(defn, formula.formula_type, metrics, params, bands, lookup_rows, guards)
        return SlaOnboardResponse(**detail.model_dump(), similar_slas=similar_slas)

    # ---------------------------------------------------------------- list

    def list_slas(
        self,
        *,
        contract_type: Optional[str] = None,
        formula_type: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[List[SlaDefinitionResponse], int]:
        rows = self.repo.list_definitions_with_formula(
            contract_type=contract_type,
            formula_type=formula_type,
            status=status,
            skip=skip,
            limit=limit,
        )
        total = self.repo.count_definitions(
            contract_type=contract_type,
            formula_type=formula_type,
            status=status,
        )
        items = [self._build_flat(defn, ft) for defn, ft in rows]
        return items, total

    # ---------------------------------------------------------------- get detail

    def get_detail(self, sla_id: str) -> SlaDetailResponse:
        defn = self.repo.get_by_id(sla_id)
        if defn is None:
            raise NotFoundError(f"SLA '{sla_id}' not found")
        formula = self.master_repo.get_formula_by_id(defn.formula_id)
        metrics = self.repo.list_metrics(sla_id)
        params = self.repo.list_parameters(sla_id)
        bands = self.repo.list_bands(sla_id)
        lookup_rows = self.repo.list_lookup_rows(sla_id)
        guards = self.repo.list_guards(sla_id)
        ft = formula.formula_type if formula else ""
        return self._build_detail(defn, ft, metrics, params, bands, lookup_rows, guards)

    # ---------------------------------------------------------------- get DSL

    def get_dsl(self, sla_id: str) -> SlaDslResponse:
        defn = self.repo.get_by_id(sla_id)
        if defn is None:
            raise NotFoundError(f"SLA '{sla_id}' not found")
        if not defn.dsl_source:
            raise NotFoundError("DSL not yet generated for this SLA", code="dsl_not_found")
        return SlaDslResponse(
            sla_id=defn.id,
            sla_ref=defn.sla_ref,
            dsl_version=defn.dsl_version,
            dsl_source=defn.dsl_source,
        )

    # ---------------------------------------------------------------- update basic fields

    def update_basic(self, sla_id: str, payload: SlaUpdateRequest) -> SlaDetailResponse:
        defn = self.repo.get_by_id(sla_id)
        if defn is None:
            raise NotFoundError(f"SLA '{sla_id}' not found")
        if defn.status == "DELETED":
            raise ConflictError("Cannot update a deleted SLA", code="sla_deleted")

        updates = payload.model_dump(exclude_unset=True)
        if "metadata" in updates:
            updates["metadata_"] = updates.pop("metadata")

        for k, v in updates.items():
            setattr(defn, k, v)
        self.db.flush()

        # Reload sub-tables and regenerate DSL
        formula = self.master_repo.get_formula_by_id(defn.formula_id)
        metrics = self.repo.list_metrics(sla_id)
        params = self.repo.list_parameters(sla_id)
        bands = self.repo.list_bands(sla_id)
        lookup_rows = self.repo.list_lookup_rows(sla_id)
        guards = self.repo.list_guards(sla_id)
        ft = formula.formula_type if formula else ""

        dsl_text = _generate_dsl(defn, ft, metrics, params, bands, lookup_rows, guards)
        self.repo.update_dsl(defn, dsl_text, defn.dsl_version + 1)

        return self._build_detail(defn, ft, metrics, params, bands, lookup_rows, guards)

    # ---------------------------------------------------------------- soft delete

    def soft_delete(self, sla_id: str) -> SlaDefinitionResponse:
        defn = self.repo.get_by_id(sla_id)
        if defn is None:
            raise NotFoundError(f"SLA '{sla_id}' not found")
        if defn.status == "DELETED":
            raise ConflictError("SLA is already deleted", code="already_deleted")
        defn.status = "DELETED"
        self.db.flush()
        formula = self.master_repo.get_formula_by_id(defn.formula_id)
        return self._build_flat(defn, formula.formula_type if formula else "")
