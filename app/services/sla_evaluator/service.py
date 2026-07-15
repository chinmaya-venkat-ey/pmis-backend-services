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
    BulkEvaluationRequest,
    EvalFormBand,
    EvalFormInput,
    EvalFormPeriod,
    EvalFormSchema,
    EvalFormSubmit,
    MappingFormSchema,
    SimpleEvaluationRequest,
    MappingEvaluationRequest,
    MappingEvaluationResponse,
    MetricObservation,
    ScoringSource,
)
from app.services.ld_bands import ld_percent_for_points, resolve_band_pairs
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


def _severity_from_ld_pct(ld_pct: Decimal) -> int:
    """Bucket an effective LD % into the 0-4 severity scale banded SLAs use.

    Applied to linear-LD (fixed_escalation) results so the response's
    ``severity_level`` matches the shape point_accumulation SLAs emit
    natively. Thresholds track the PMU RFP severity progression:
    ≤ 1% → 1, ≤ 2% → 2, ≤ 5% → 3, > 5% → 4.
    """
    if ld_pct <= 0:      return 0
    if ld_pct <= 1:      return 1
    if ld_pct <= 2:      return 2
    if ld_pct <= 5:      return 3
    return 4


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

        # Change 2: whole-activity LD total — the LD% is CUMULATIVE across SLAs.
        # Each evaluated SLA already derived its own ld_percent from its own points
        # via the project's LD chart; the activity total is the SUM of those per-SLA
        # percentages, CAPPED at 10% (the maximum LD allowed for the activity total).
        # total_points is retained for display only. None when nothing was evaluated.
        total_points: Optional[Decimal] = None
        total_ld_percent: Optional[Decimal] = None
        if mapping_results:
            total_points = sum(
                (m.accumulated_points or Decimal("0") for m in mapping_results),
                Decimal("0"),
            )
            per_sla_ld = [
                m.ld_percent for m in mapping_results if m.ld_percent is not None
            ]
            if per_sla_ld:
                total_ld_percent = min(sum(per_sla_ld), Decimal("10"))

        return ActivityEvaluationResponse(
            activity_id=activity_id,
            period_start=period_start,
            period_end=period_end,
            mapping_results=mapping_results,
            total_points=total_points,
            total_ld_percent=total_ld_percent,
            summary={
                "mappings_evaluated": len(mapping_results),
                "mappings_skipped": skipped,
                "severity_breakdown": severity_breakdown,
                "project_id": scoring["project_id"],
                "severity_master_source": scoring["severity_master_source"],
            },
        )

    # ------------------------------------------------------------------ simple evaluation

    def evaluate_by_sla_ref(
        self,
        activity_id: str,
        sla_ref: str,
        payload: SimpleEvaluationRequest,
        bearer_token: Optional[str] = None,
    ) -> MappingEvaluationResponse:
        """Single-SLA evaluation keyed by ``(activity_id, sla_ref)``.

        Looks up the mapping, infers the observation shape from the SLA's
        primary metric + formula, then delegates to the existing engine.
        """
        loaded = self.mapping_repo.find_by_activity_and_sla_ref(
            activity_id, sla_ref, active_only=True,
        )
        if loaded is None:
            raise NotFoundError(
                f"No active mapping for SLA '{sla_ref}' on activity "
                f"'{activity_id}'. Attach the SLA to the activity first.",
                code="mapping_not_found",
            )
        mapping, sla, formula_type = loaded
        if formula_type is None:
            raise ValidationError(
                f"SLA '{sla.sla_ref}' has no formula_type resolved.",
                code="formula_missing",
            )

        # The translator returns a *list* — one MetricObservation for
        # single-metric SLAs, N for multi-metric SLAs (e.g. PMU-SLA007
        # where the dict {bd:16, hrs:144} yields one SINGLE_VALUE per
        # metric so the engine evaluates both metrics' bands).
        observations = self._translate_simple_value(sla, formula_type, payload.value)

        scoring = self._resolve_project_scoring(mapping.activity_id, bearer_token)
        return self._evaluate(
            mapping=mapping,
            sla=sla,
            formula_type=formula_type,
            period_start=payload.period_start,
            period_end=payload.period_end,
            observations=observations,
            scoring=scoring,
        )

    def evaluate_activity_bulk(
        self,
        activity_id: str,
        payload: BulkEvaluationRequest,
        bearer_token: Optional[str] = None,
    ) -> ActivityEvaluationResponse:
        """Multi-SLA evaluation keyed by ``sla_ref`` instead of metric_key/shape.

        The simple body (``{"PMU-SLA005": 2, "PMU-SLA007": {...}}``) is
        translated per-SLA into a list of MetricObservation and the
        existing per-activity engine runs unchanged.
        """
        # Reuse the full-fan-out path; we just translate the simple
        # observations dict into the engine-shaped one first.
        translated: Dict[str, List[MetricObservation]] = {}
        rows = self.mapping_repo.list_for_activity(activity_id, active_only=True)
        sla_by_ref = {sla.sla_ref: (sla, ft) for (_m, sla, ft) in rows}
        for sla_ref, value in (payload.observations or {}).items():
            entry = sla_by_ref.get(sla_ref)
            if entry is None:
                # Unknown sla_ref — silently skip; the engine will record a
                # "no observations" note when it hits the mapping.
                continue
            sla, ft = entry
            # Translator returns a list — spread it directly. Multi-metric
            # SLAs produce one observation per metric.
            translated[sla_ref] = self._translate_simple_value(sla, ft, value)

        engine_payload = ActivityEvaluationRequest(
            period_start=payload.period_start,
            period_end=payload.period_end,
            observations_by_sla_ref=translated,
        )
        return self.evaluate_activity(
            activity_id, engine_payload, bearer_token=bearer_token,
        )

    # Maps formula_type → the natural MetricObservation.shape when the
    # caller hands us a plain number. The bulk path uses the same map.
    _SHAPE_FOR_NUMBER = {
        "point_accumulation": "SINGLE_VALUE",
        "band_accumulation":  "DAILY_VALUES",  # caller almost never passes 1 number here
        "fixed_escalation":   "SINGLE_VALUE",
        "wac":                "SINGLE_VALUE",  # caller should send a dict
    }

    def _translate_simple_value(
        self,
        sla: SlaDefinition,
        formula_type: str,
        value: Any,
    ) -> List[MetricObservation]:
        """Translate a caller-friendly value into 1+ MetricObservations.

        Rules:
          * number (int/float/str-number)  → 1 × SINGLE_VALUE on the primary metric
          * list of numbers                → 1 × DAILY_VALUES on the primary metric
          * dict with WAC keys (wac SLAs)  → 1 × WAC_BREAKDOWN on the primary metric
          * dict whose keys match metric_keys (multi-metric SLAs)
                                           → N × SINGLE_VALUE, one per metric
          * dict otherwise                 → 1 × BAND_COUNTS on the primary metric
                                             (legacy "days per band label" path)

        Returns a list so the multi-metric case can produce one observation
        per metric — required for SLAs like PMU-SLA007 that gate Sev 0 on
        BD AND hours both meeting target.
        """
        metrics = self.sla_repo.list_metrics(sla.id)
        metric_keys = {m.metric_key for m in metrics if m.metric_key}
        primary = self._primary_metric_key(sla)
        if primary is None:
            raise ValidationError(
                f"SLA '{sla.sla_ref}' has no primary metric defined.",
                code="primary_metric_missing",
            )

        if isinstance(value, list):
            try:
                daily = [Decimal(str(v)) for v in value]
            except (ValueError, ArithmeticError) as exc:
                raise ValidationError(
                    f"Daily values for '{sla.sla_ref}' must be numbers: {exc}",
                    code="invalid_daily_values",
                ) from exc
            return [MetricObservation(
                metric_key=primary, shape="DAILY_VALUES", daily_values=daily,
            )]

        if isinstance(value, dict):
            if formula_type == "wac":
                try:
                    wac = {k: Decimal(str(v)) for k, v in value.items()}
                except (ValueError, ArithmeticError) as exc:
                    raise ValidationError(
                        f"WAC breakdown values must be numbers: {exc}",
                        code="invalid_wac_breakdown",
                    ) from exc
                return [MetricObservation(
                    metric_key=primary, shape="WAC_BREAKDOWN", wac_breakdown=wac,
                )]

            # Multi-metric case: every dict key is a known metric_key on
            # this SLA. Emit one SINGLE_VALUE observation per metric so
            # the engine evaluates the bands declared on each one.
            if metric_keys and set(value.keys()).issubset(metric_keys):
                obs_list: List[MetricObservation] = []
                for mkey, mval in value.items():
                    try:
                        n = Decimal(str(mval))
                    except (ValueError, ArithmeticError) as exc:
                        raise ValidationError(
                            f"Value for metric '{mkey}' on SLA "
                            f"'{sla.sla_ref}' must be a number: {exc}",
                            code="invalid_metric_value",
                        ) from exc
                    obs_list.append(MetricObservation(
                        metric_key=mkey, shape="SINGLE_VALUE", single_value=n,
                    ))
                return obs_list

            # Legacy "days per band label" dict — counts integer per band.
            try:
                counts = {k: int(v) for k, v in value.items()}
            except (ValueError, TypeError) as exc:
                raise ValidationError(
                    f"Band counts must be integer values: {exc}",
                    code="invalid_band_counts",
                ) from exc
            return [MetricObservation(
                metric_key=primary, shape="BAND_COUNTS", band_counts=counts,
            )]

        # Scalar: number-ish.
        try:
            single = Decimal(str(value))
        except (ValueError, ArithmeticError) as exc:
            raise ValidationError(
                f"Expected number / list / dict for SLA '{sla.sla_ref}', "
                f"got {type(value).__name__}: {exc}",
                code="invalid_observation_value",
            ) from exc
        return [MetricObservation(
            metric_key=primary, shape="SINGLE_VALUE", single_value=single,
        )]

    # ------------------------------------------------------------------ mapping form schema

    _APPLIED_ON_LABEL = {
        "QUARTERLY_PAYMENT": "Net Planned Quarterly Payment (NPQP)",
        "ANNUAL_PAYMENT":    "Annual Contract Value",
        "FIXED_AMOUNT":      "Deliverable Cost (set per mapping)",
    }

    # Maps placeholder.type → EvalFormInput.type. The placeholder schema
    # uses "money" / "date" / "number" / "text"; the form schema uses
    # the EvalFormInput vocabulary (number / integer / text / list / object).
    _PLACEHOLDER_INPUT_TYPE = {
        "money":  "number",
        "number": "number",
        "date":   "text",   # FE renders a date picker on type=text + name hint
        "text":   "text",
    }

    def get_mapping_form_schema(
        self,
        sla_id: str,
        activity_id: Optional[str] = None,
        bearer_token: Optional[str] = None,
    ) -> MappingFormSchema:
        """Build the FE-renderable form spec for *attaching* this SLA to an activity.

        Same design as ``get_evaluation_form_schema`` but for stage 2 of
        the flow. Reads the SLA's ``placeholders`` JSONB and turns each
        entry into an EvalFormInput so the FE renders the mapping modal
        purely from the response.
        """
        sla = self.sla_repo.get_by_id(sla_id)
        if sla is None:
            raise NotFoundError(f"SLA '{sla_id}' not found", code="sla_not_found")
        formula = self.master_repo.get_formula_by_id(sla.formula_id)
        formula_type = formula.formula_type if formula else "unknown"

        # ── Translate placeholders → EvalFormInput rows ───────────────
        inputs: List[EvalFormInput] = []
        placeholders = sla.placeholders or []
        for ph in placeholders:
            if not isinstance(ph, dict):
                continue
            key = ph.get("key")
            if not key:
                continue
            ph_type = ph.get("type") or "text"
            input_type = self._PLACEHOLDER_INPUT_TYPE.get(ph_type, "text")
            inputs.append(EvalFormInput(
                name=key,
                type=input_type,
                label=ph.get("label") or key,
                unit=("date" if ph_type == "date" else
                      "₹" if ph_type == "money" else None),
                placeholder="YYYY-MM-DD" if ph_type == "date" else (
                    "e.g. 1000000" if ph_type == "money" else "value"),
                help=ph.get("help"),
                required=bool(ph.get("required", True)),
            ))

        # ── effective_from default — try the activity's planned start ─
        effective_from_default = None
        if activity_id and self.project_mgmt_client is not None:
            try:
                act = self.project_mgmt_client.get_activity(
                    activity_id, bearer_token=bearer_token,
                )
                if isinstance(act, dict):
                    sd = act.get("startDate") or act.get("start_date")
                    if sd:
                        effective_from_default = _parse_date(sd)
            except Exception:  # noqa: BLE001
                pass
        if effective_from_default is None:
            effective_from_default = sla.effective_from

        # ── Explanation — surface "Applied On" so the operator can see
        # whether this SLA needs an ld_base_amount placeholder filled. ─
        applied_on = sla.ld_computation_base
        applied_on_label = self._APPLIED_ON_LABEL.get(applied_on, applied_on or "")
        explanation_parts = [
            f"Attaching this SLA scopes it to one activity. "
            f"Applied On: {applied_on_label}.",
        ]
        if inputs:
            explanation_parts.append(
                "Fill in the values below — they go into the mapping's "
                "``overrides`` and are used by the evaluator later."
            )
        else:
            explanation_parts.append(
                "This SLA needs no per-attachment inputs — plugs straight "
                "onto the activity."
            )
        explanation = " ".join(explanation_parts)

        # ── Submit target ─────────────────────────────────────────────
        body_template: Dict[str, Any] = {
            "sla_id": sla.id,
            "activity_id": activity_id,
            "effective_from": str(effective_from_default) if effective_from_default else None,
            "overrides": {ph.get("key"): None for ph in placeholders if isinstance(ph, dict) and ph.get("key")},
        }
        submit = EvalFormSubmit(
            method="POST",
            url="/api/v3/sla-activity-mappings",
            body_template=body_template,
        )

        return MappingFormSchema(
            sla_ref=sla.sla_ref,
            sla_title=sla.title,
            project_id=sla.project_id,
            contract_type=sla.contract_type,
            category=sla.category,
            formula_type=formula_type,
            explanation=explanation,
            effective_from_default=effective_from_default,
            inputs=inputs,
            submit=submit,
            applied_on=applied_on,
            applied_on_label=applied_on_label,
        )

    # ------------------------------------------------------------------ form schema

    def get_evaluation_form_schema(
        self,
        activity_id: str,
        sla_ref: str,
        bearer_token: Optional[str] = None,
    ) -> EvalFormSchema:
        """Build the FE-renderable form spec for evaluating one SLA.

        Introspects the SLA's stored config (metric, bands, lookup table)
        and the active mapping, returns ``inputs`` / ``bands`` / period
        defaults so the FE can render the modal generically without
        hardcoded per-formula logic.
        """
        loaded = self.mapping_repo.find_by_activity_and_sla_ref(
            activity_id, sla_ref, active_only=True,
        )
        if loaded is None:
            raise NotFoundError(
                f"No active mapping for SLA '{sla_ref}' on activity "
                f"'{activity_id}'. Attach the SLA first.",
                code="mapping_not_found",
            )
        mapping, sla, formula_type = loaded
        if formula_type is None:
            raise ValidationError(
                f"SLA '{sla.sla_ref}' has no formula_type resolved.",
                code="formula_missing",
            )

        # Pull the sub-tables we need for the form.
        metrics = self.sla_repo.list_metrics(sla.id)
        bands = self.sla_repo.list_bands(sla.id)
        lookups = self.sla_repo.list_lookup_rows(sla.id)
        primary = next((m for m in metrics if m.is_primary), None) or (metrics[0] if metrics else None)

        # ── Inputs — DSL-introspection-driven ────────────────────────
        # Multi-metric SLAs (PMU-SLA007 has BD + hrs) get one object
        # input with a sub-field per metric. Single-metric SLAs get one
        # scalar input as before.
        inputs = self._build_form_inputs(formula_type, metrics, primary)

        # ── Bands — the RFP rule reference card ─────────────────────
        # Multi-metric: bands grouped by metric_key. Linear escalation
        # with many lookup rows: summarised "0.5% per week" instead of
        # dumping every tier.
        band_list = self._build_form_bands(bands, lookups, metrics)

        # ── Period defaults — try the activity's planned dates from
        # project-mgmt; fall back to the mapping's effective range.
        period_start = mapping.effective_from
        period_end = mapping.effective_until
        if self.project_mgmt_client is not None:
            try:
                act = self.project_mgmt_client.get_activity(
                    activity_id, bearer_token=bearer_token,
                )
                if isinstance(act, dict):
                    sd = act.get("startDate") or act.get("start_date")
                    ed = act.get("endDate") or act.get("end_date")
                    if sd:
                        period_start = _parse_date(sd) or period_start
                    if ed:
                        period_end = _parse_date(ed) or period_end
            except Exception:  # noqa: BLE001 — project-mgmt is best-effort
                pass

        period = EvalFormPeriod(
            start_default=period_start, end_default=period_end,
        )

        # ── Question + explanation — human-friendly intro on the form ─
        measure_label = (primary.display_name if primary else "value") or "value"
        question = "What did you measure?"
        explanation_parts = [
            f"Enter the actual {measure_label.lower()} you observed during this reporting period."
        ]
        # Surface date-type placeholders so the caller knows the mapping
        # already locked them in (e.g. T₀, K=approval_date). This is the
        # bit that makes "variance from K" comprehensible.
        date_placeholders = [
            p for p in (sla.placeholders or [])
            if isinstance(p, dict) and p.get("type") == "date"
        ]
        overrides = mapping.overrides or {}
        for ph in date_placeholders:
            key = ph.get("key")
            label = ph.get("label") or key
            stamped = overrides.get(key) if key else None
            if stamped:
                explanation_parts.append(
                    f"Note — “{label}” is set to {stamped} on this mapping; "
                    "the value you enter is measured relative to that date."
                )
            else:
                explanation_parts.append(
                    f"Heads-up — this SLA expects “{label}” to be set on the "
                    "mapping (currently empty). Patch the mapping's overrides "
                    "before evaluating."
                )
        explanation = " ".join(explanation_parts)

        # ── Submit target — the simple eval endpoint ────────────────
        submit = EvalFormSubmit(
            method="POST",
            url=f"/api/v3/activities/{activity_id}/sla-evaluate/{sla_ref}",
            body_template={
                "period_start": str(period_start) if period_start else None,
                "period_end": str(period_end) if period_end else None,
                "value": None,
            },
        )

        return EvalFormSchema(
            sla_ref=sla.sla_ref,
            sla_title=sla.title,
            activity_id=activity_id,
            mapping_id=mapping.id,
            formula_type=formula_type,
            category=sla.category,
            question=question,
            explanation=explanation,
            period=period,
            inputs=inputs,
            bands=band_list,
            submit=submit,
        )

    @staticmethod
    def _build_form_inputs(
        formula_type: str,
        all_metrics,    # list[SlaMetric]
        primary,        # SlaMetric or None
    ) -> List[EvalFormInput]:
        """Build the FE form-input spec from the SLA's metrics + formula.

        Three branches:
          * ``wac`` — fixed 7-field defect breakdown.
          * ``band_accumulation`` — one list field (daily readings of
            the primary metric).
          * Everything else — one input per declared metric. Most SLAs
            have a single metric and get a plain scalar input; SLA-007
            and friends have BD + hrs and get one object with two
            sub-fields so the operator enters both at once.
        """
        if formula_type == "wac":
            return [EvalFormInput(
                name="value", type="object", label="Defect breakdown",
                help="Enter the defect counts you observed during the period.",
                fields=[
                    EvalFormInput(name="blocker",      type="integer", label="Blocker defects",   placeholder="0", minimum=0),
                    EvalFormInput(name="critical",     type="integer", label="Critical defects",  placeholder="0", minimum=0),
                    EvalFormInput(name="major",        type="integer", label="Major defects",     placeholder="0", minimum=0),
                    EvalFormInput(name="minor",        type="integer", label="Minor defects",     placeholder="0", minimum=0),
                    EvalFormInput(name="applications", type="integer", label="Applications",      placeholder="1", minimum=1),
                    EvalFormInput(name="baseline",     type="number",  label="Baseline WAC",      placeholder="0.40"),
                    EvalFormInput(name="previous_wac", type="number",  label="Previous WAC",      placeholder="0.40"),
                ],
            )]

        if formula_type == "band_accumulation":
            label = (primary.display_name if primary else "Value") or "Value"
            unit = (primary.unit if primary else "") or None
            return [EvalFormInput(
                name="value", type="list", label=f"Daily readings of {label}",
                unit=unit, item_type="number",
                help="Comma- or newline-separated. Roughly 90 entries for a quarter.",
            )]

        # point_accumulation / fixed_escalation:
        # Multi-metric SLAs (e.g. PMU-SLA007 with BD + hrs) get an
        # object input so the operator types both numbers in one form.
        metric_list = list(all_metrics or [])
        if len(metric_list) > 1:
            # Sort primary first so the FE renders it on top.
            metric_list.sort(key=lambda m: 0 if m.is_primary else 1)
            return [EvalFormInput(
                name="value", type="object",
                label="Measurements for this period",
                help="The contract requires all of these values together.",
                fields=[
                    EvalFormInput(
                        name=m.metric_key or f"metric_{i}",
                        type="number",
                        label=m.display_name or m.metric_key or "Value",
                        unit=(m.unit or None),
                        placeholder="0",
                        minimum=0,
                    )
                    for i, m in enumerate(metric_list)
                ],
            )]

        # Single metric — one scalar input.
        label = (primary.display_name if primary else "Value") or "Value"
        unit = (primary.unit if primary else "") or None
        return [EvalFormInput(
            name="value", type="number", label=label, unit=unit,
            placeholder="0", help="Just type the number you observed for this period.",
            minimum=0,
        )]

    # Threshold above which a lookup-table SLA's bands card is collapsed
    # to a "Linear LD" summary plus the first / last tier. Below the
    # threshold (the default-ish lookup tables) we keep showing every
    # row so the operator can scan it.
    _LOOKUP_BAND_DUMP_LIMIT = 8

    @classmethod
    def _build_form_bands(
        cls,
        bands,        # list[SlaConditionBand]
        lookups,      # list[SlaLookupRow]
        metrics,      # list[SlaMetric] — used to group multi-metric SLAs
    ) -> List[EvalFormBand]:
        """RFP rule reference rows. Grouped by metric for multi-metric SLAs
        and summarised for long lookup tables.
        """
        # ── Multi-metric → group bands by metric_key so the FE shows
        # one section per metric. The grouping is conveyed via the
        # ``unit`` field (we prefix it with the metric's display name)
        # because the schema doesn't have a "group" field; the FE renders
        # by sorting on this — clear enough for the demo, structured
        # bands can come later.
        if bands:
            metric_label_by_key = {
                (m.metric_key or ""): (m.display_name or m.metric_key or "")
                for m in (metrics or [])
            }
            out: List[EvalFormBand] = []
            for b in sorted(
                bands,
                key=lambda x: (x.metric_key or "", x.severity_level or 0, x.sort_order or 0),
            ):
                # Stamp the metric label into the unit field when there's
                # more than one metric — clear for the operator without a
                # schema bump.
                unit = b.range_unit
                if len(metric_label_by_key) > 1 and b.metric_key:
                    mlabel = metric_label_by_key.get(b.metric_key)
                    if mlabel:
                        unit = f"{unit or ''} · {mlabel}".strip(" ·")
                out.append(EvalFormBand(
                    severity=b.severity_level,
                    label=b.band_label or "",
                    range_min=b.range_min,
                    range_max=b.range_max,
                    unit=unit,
                ))
            return out

        if not lookups:
            return []

        # ── Linear escalation. Short tables stay as-is; long ones get
        # summarised with a synthesized "Linear LD: X% per unit" row
        # followed by the first and last tier so the operator sees the
        # shape without scrolling through 100+ rows.
        sorted_rows = sorted(lookups, key=lambda x: x.sort_order or 0)
        if len(sorted_rows) <= cls._LOOKUP_BAND_DUMP_LIMIT:
            return [EvalFormBand(
                severity=None,
                label=r.lookup_key or "",
                rate_percent=r.lookup_value,
            ) for r in sorted_rows]

        # Infer the rate from the first non-zero tier delta.
        rate = None
        for idx, r in enumerate(sorted_rows):
            if r.lookup_value and r.lookup_value > 0:
                if idx == 0:
                    rate = r.lookup_value
                else:
                    rate = r.lookup_value - (sorted_rows[idx - 1].lookup_value or 0)
                break

        summary_rows: List[EvalFormBand] = []
        if rate is not None:
            summary_rows.append(EvalFormBand(
                severity=None,
                label=f"Linear LD: {rate}% per unit  ({len(sorted_rows)} tiers, "
                      f"max {sorted_rows[-1].lookup_value}%)",
                rate_percent=rate,
            ))
        # Append the first and last tier so the band card stays useful.
        summary_rows.append(EvalFormBand(
            severity=None,
            label=f"first tier: {sorted_rows[0].lookup_key}",
            rate_percent=sorted_rows[0].lookup_value,
        ))
        summary_rows.append(EvalFormBand(
            severity=None,
            label=f"last tier: {sorted_rows[-1].lookup_key}",
            rate_percent=sorted_rows[-1].lookup_value,
        ))
        return summary_rows

    def _primary_metric_key(self, sla: SlaDefinition) -> Optional[str]:
        """Look up the SLA's primary metric_key via the repo.

        Falls back to the first metric if none is flagged is_primary —
        most PMU SLAs only have one metric anyway.
        """
        metrics = self.sla_repo.list_metrics(sla.id)
        if not metrics:
            return None
        primary = next((m for m in metrics if m.is_primary), None) or metrics[0]
        return primary.metric_key

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

        ``ld_band_pairs`` is the project's points→LD% chart (project_ld_bands),
        or the RFP default chart when the project has none / is unresolved — it
        drives the ld_percent on each mapping and the whole-activity total.
        """
        result: Dict[str, Any] = {
            "project_id": None,
            "level_points_map": None,
            "severity_master_source": "default",
            "ld_band_pairs": resolve_band_pairs([]),  # RFP default until resolved
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
        # LD chart for this project (falls back to RFP default when unconfigured).
        result["ld_band_pairs"] = resolve_band_pairs(
            self.master_repo.list_ld_bands_for_project(project_id)
        )
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

        # Change 1: derive this SLA's LD% from its accumulated points via the
        # project's LD chart (uncapped — the 10% cap is a whole-activity concern).
        ld_percent = ld_percent_for_points(
            result.accumulated_points, scoring["ld_band_pairs"],
        )

        # For linear-LD (fixed_escalation) SLAs the evaluator only reports
        # per-tier rate_percent inside breaches[]; it doesn't set
        # severity_level or accumulated_points. The FE renders those fields
        # as blank cells, which reads as "not measured" even though the SLA
        # WAS evaluated. Normalise here so the "click Evaluate" path
        # (this method) and the cron-persist path both surface consistent
        # numbers. Point-accumulation / band-accumulation / wac results
        # come through untouched — the block only fires when the evaluator
        # returned None.
        severity_out = result.severity_level
        points_out = result.accumulated_points
        breached_flag = bool(result.breaches) and any(
            (b.rate_percent and b.rate_percent > 0)
            or (b.severity_level is not None and b.severity_level >= 1)
            or (b.points_contribution and b.points_contribution > 0)
            for b in (result.breaches or [])
        )
        # Effective LD % for fixed_escalation = max tier rate; for
        # point_accumulation = ld_percent from the project's LD chart.
        effective_ld = ld_percent
        if effective_ld is None and result.breaches:
            rates = [
                b.rate_percent for b in result.breaches
                if getattr(b, "rate_percent", None) is not None
            ]
            if rates:
                effective_ld = max(rates)
        if severity_out is None:
            if not breached_flag:
                severity_out = 0
            elif effective_ld is not None:
                severity_out = _severity_from_ld_pct(effective_ld)
        if points_out is None and effective_ld is not None:
            points_out = effective_ld

        return MappingEvaluationResponse(
            mapping_id=mapping.id,
            activity_id=mapping.activity_id,
            sla_id=sla.id,
            sla_ref=sla.sla_ref,
            contract_type=sla.contract_type,
            formula_type=formula_type,
            period_start=resolved_start,
            period_end=resolved_end,
            severity_level=severity_out,
            accumulated_points=points_out,
            ld_percent=ld_percent if ld_percent is not None else effective_ld,
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
