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


def _drop_nulls_and_defaults(d: dict, defaults: dict) -> dict:
    """Compact dict for DSL emission.

    Removes keys whose value is None / empty string / empty list, and
    removes keys that equal their declared default. The DSL stays minimal
    so a reader's eye lands on what's *unique* about this SLA, not on
    boilerplate like "baseline_type: STATIC".
    """
    out = {}
    for k, v in d.items():
        if v is None or v == "" or v == []:
            continue
        if k in defaults and v == defaults[k]:
            continue
        out[k] = v
    return out


def _generate_dsl(
    defn: SlaDefinition,
    formula_type: str,
    metrics: List[SlaMetric],
    parameters: List[SlaParameterValue],
    bands: List[SlaConditionBand],
    lookup_rows: List[SlaLookupRow],
    guards: List[SlaGuardCondition],
) -> str:
    """Emit the SLA as a readable YAML grouped by RFP-style sections.

    The output is optimised for human eyes — fields that are at their
    framework default ("STATIC", "INDEPENDENT", "SUM", "QUARTERLY",
    "QUARTERLY_PAYMENT") are dropped, as are nulls and empty lists. The
    result reads like the RFP table with the technical bits underneath.
    """
    # ── Section 1: identification ──
    identification = _drop_nulls_and_defaults({
        "sla_ref": defn.sla_ref,
        "title": defn.title,
        "category": defn.category,
        "contract_type": defn.contract_type,
        "project_id": defn.project_id,
        "status": defn.status if defn.status != "ACTIVE" else None,
    }, defaults={})

    # ── Section 2: RFP text rows ──
    rfp_text = _drop_nulls_and_defaults({
        "definition": defn.description,
        "scope": defn.scope_text,
        "source_of_data": defn.data_source,
        "calculation": defn.calculation_method,
        "reports_submitted_to": defn.reports_submitted_to,
    }, defaults={})

    # ── Section 3: cadence + LD base ──
    cadence = _drop_nulls_and_defaults({
        "measurement_interval": defn.measurement_interval,
        "reporting_interval": defn.reporting_interval,
        "applied_on": defn.ld_computation_base,
    }, defaults={
        "measurement_interval": "QUARTERLY",
        "reporting_interval": "QUARTERLY",
        "applied_on": "QUARTERLY_PAYMENT",
    })

    # ── Section 4: lifetime ──
    lifetime = _drop_nulls_and_defaults({
        "effective_from": str(defn.effective_from),
        "effective_until": str(defn.effective_until) if defn.effective_until else None,
    }, defaults={})

    # ── Section 5: mapping-time variables ──
    # The placeholder list is the spec for the mapping form. Empty = the
    # SLA plugs straight onto an activity with no extra input.
    mapping_inputs = list(defn.placeholders or [])

    # ── Section 6: what is measured ──
    measurements = []
    for m in sorted(metrics, key=lambda x: (not x.is_primary, x.metric_key)):
        measurements.append(_drop_nulls_and_defaults({
            "key": m.metric_key,
            "name": m.display_name,
            "unit": m.unit,
            "target": _decimal_str(m.target_numeric) or (
                str(m.target_date) if m.target_date else None
            ),
            "direction": m.direction,
            "primary": m.is_primary if m.is_primary else None,
        }, defaults={"direction": "LOWER_BETTER"}))

    # ── Section 7: target table (severity bands OR linear tiers) ──
    target = []
    for b in sorted(bands, key=lambda x: x.sort_order or 0):
        target.append(_drop_nulls_and_defaults({
            "severity": b.severity_level,
            "rate_percent": _decimal_str(b.rate_percent),
            "points": _decimal_str(b.points_contribution),
            "from": _decimal_str(b.range_min),
            "to": _decimal_str(b.range_max),
            "unit": b.range_unit,
            "label": b.band_label,
            "metric": b.metric_key,
        }, defaults={}))
    linear_tiers = []
    for r in sorted(lookup_rows, key=lambda x: x.sort_order or 0):
        linear_tiers.append(_drop_nulls_and_defaults({
            "tier": r.lookup_key,
            "ld_percent": _decimal_str(r.lookup_value),
        }, defaults={}))

    # ── Section 8: advanced (only if non-trivial) ──
    advanced = _drop_nulls_and_defaults({
        "formula_type": formula_type,
        "baseline_type": defn.baseline_type,
        "compound_metric_rule": defn.compound_metric_rule,
        "ld_aggregation_method": defn.ld_aggregation_method,
        "parameters": [
            {"key": p.param_key, "value": p.param_value} for p in parameters
        ] or None,
        "guards": [
            _drop_nulls_and_defaults({
                "metric": g.metric_key,
                "op": g.operator,
                "threshold": _decimal_str(g.threshold_value),
                "unit": g.threshold_unit,
                "action": g.action,
                "description": g.action_description,
                "group": g.guard_group_id,
            }, defaults={}) for g in guards
        ] or None,
    }, defaults={
        "baseline_type": "STATIC",
        "compound_metric_rule": "INDEPENDENT",
        "ld_aggregation_method": "SUM",
    })

    # Stitch the top-level sections together, skipping any that are empty.
    data = {}
    for label, block in (
        ("identification",  identification),
        ("rfp",             rfp_text),
        ("cadence",         cadence),
        ("lifetime",        lifetime),
        ("mapping_inputs",  mapping_inputs),
        ("measurements",    measurements),
        ("target",          target),
        ("linear_tiers",    linear_tiers),
        ("advanced",        advanced),
    ):
        if block:
            data[label] = block

    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ---------------------------------------------------------------------------
# RFP-shape onboarding helpers
# ---------------------------------------------------------------------------

# Words in a measurement display name that suggest "lower is better". When
# none of these match, we fall back to HIGHER_BETTER. The user can change
# the direction later via PATCH if the heuristic gets it wrong.
_LOWER_BETTER_HINTS = (
    "delay", "delayed", "variance", "fail", "failure", "defect", "error",
    "downtime", "mttr", "outage", "incident", "replacement", "miss",
)


def _smart_direction(display_name: str) -> str:
    """Guess metric direction from the display name. Fallback: HIGHER_BETTER.

    Most PMU SLAs measure something where higher = worse (days delayed,
    replacements, failures), so detect that and flip the default.
    """
    name = (display_name or "").lower()
    return "LOWER_BETTER" if any(h in name for h in _LOWER_BETTER_HINTS) else "HIGHER_BETTER"


def _band_default_label(row) -> str:
    """Generate a readable band label when the user didn't type one.

    Produces e.g. "0 < x <= 7" or "x > 30" or "x <= 0".
    """
    lo, hi = row.from_value, row.to_value
    if lo is None and hi is not None:
        return f"x <= {hi}"
    if lo is not None and hi is None:
        return f"x > {lo}"
    if lo is not None and hi is not None:
        return f"{lo} < x <= {hi}"
    return "any"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class SlaService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = SlaRepository(db)
        self.master_repo = MasterRepository(db)
        # Lazy-init the attachment repo so the import only happens when
        # the service is instantiated (keeps the top-of-file import block
        # small and side-effect-free).
        from app.repositories.sla_attachment_repository import (
            SlaAttachmentRepository,
        )
        self.attachment_repo = SlaAttachmentRepository(db)

    # ---------------------------------------------------------------- helpers

    def _attachments_for_one(self, sla_id: str) -> list:
        """Pull live attachments for a single SLA and convert to response shape."""
        from app.schemas.sla_attachment import SlaAttachmentResponse
        rows = self.attachment_repo.list_for_sla(sla_id)
        return [
            SlaAttachmentResponse(
                id=r.id, sla_id=r.sla_id, file_id=r.file_id, file_url=r.file_url,
                original_filename=r.original_filename, mime_type=r.mime_type,
                size_bytes=r.size_bytes, caption=r.caption,
                uploaded_by=r.uploaded_by, uploaded_at=r.uploaded_at,
            )
            for r in rows
        ]

    def _attachments_for_many(self, sla_ids: List[str]) -> dict:
        """Batch-fetch attachments for many SLAs in one DB round-trip.

        Returns a dict keyed by sla_id with values already in response shape;
        SLAs with no live attachments aren't in the dict.
        """
        from app.schemas.sla_attachment import SlaAttachmentResponse
        grouped = self.attachment_repo.list_grouped_by_sla(sla_ids)
        return {
            sid: [
                SlaAttachmentResponse(
                    id=r.id, sla_id=r.sla_id, file_id=r.file_id, file_url=r.file_url,
                    original_filename=r.original_filename, mime_type=r.mime_type,
                    size_bytes=r.size_bytes, caption=r.caption,
                    uploaded_by=r.uploaded_by, uploaded_at=r.uploaded_at,
                )
                for r in rows
            ]
            for sid, rows in grouped.items()
        }

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
            # RFP-native presentation fields surfaced on detail too so the FE
            # can render the RFP-style table without a second round-trip.
            category=defn.category,
            scope_text=defn.scope_text,
            data_source=defn.data_source,
            calculation_method=defn.calculation_method,
            reports_submitted_to=defn.reports_submitted_to,
            measurement_interval=defn.measurement_interval,
            reporting_interval=defn.reporting_interval,
            baseline_type=defn.baseline_type,
            compound_metric_rule=defn.compound_metric_rule,
            ld_aggregation_method=defn.ld_aggregation_method,
            ld_computation_base=defn.ld_computation_base,
            status=defn.status,
            effective_from=defn.effective_from,
            effective_until=defn.effective_until,
            project_id=defn.project_id,
            placeholders=defn.placeholders or [],
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
            # RFP-native presentation fields.
            category=defn.category,
            scope_text=defn.scope_text,
            data_source=defn.data_source,
            calculation_method=defn.calculation_method,
            reports_submitted_to=defn.reports_submitted_to,
            measurement_interval=defn.measurement_interval,
            reporting_interval=defn.reporting_interval,
            baseline_type=defn.baseline_type,
            compound_metric_rule=defn.compound_metric_rule,
            ld_aggregation_method=defn.ld_aggregation_method,
            ld_computation_base=defn.ld_computation_base,
            status=defn.status,
            effective_from=defn.effective_from,
            effective_until=defn.effective_until,
            project_id=defn.project_id,
            placeholders=defn.placeholders or [],
            dsl_version=defn.dsl_version,
            created_at=defn.created_at,
            updated_at=defn.updated_at,
        )

    # ---------------------------------------------------------------- RFP-shape onboarding

    def create_from_rfp(self, payload, created_by: Optional[str] = None):
        """RFP-shape onboarding entry point — translates and delegates.

        Takes the friendly RFP-shape payload, derives every technical field
        (formula_type, metric_key, sort_order, band rows, lookup rows) from
        a category lookup + simple slugification, then hands off to the
        existing create_from_form so seeds / PATCH / evaluator stay on the
        same code path.
        """
        # Avoid a circular import — these schemas live in the same module
        # that's already importing SlaService at module load.
        from app.schemas.sla import (
            SlaConditionBandInput, SlaLookupRowInput, SlaMetricInput,
            SlaOnboardRequest,
        )

        # 1. Resolve category → engine via sla_category_master.
        category = self.master_repo.get_sla_category(payload.category_code)
        if category is None:
            raise ValidationError(
                f"Unknown SLA category '{payload.category_code}'. Pick one from GET /api/v3/sla-categories.",
                code="unknown_sla_category",
            )
        formula_type = category.formula_type

        # 2. Slugify display name -> stable metric_key.
        def _slug(name: str) -> str:
            slug = "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")
            # Collapse runs of underscores.
            while "__" in slug:
                slug = slug.replace("__", "_")
            return slug or "value"

        primary_key = _slug(payload.measurement.display_name)
        metrics = [
            SlaMetricInput(
                metric_key=primary_key,
                display_name=payload.measurement.display_name,
                unit=payload.measurement.unit,
                target_numeric=payload.measurement.target_value,
                direction=_smart_direction(payload.measurement.display_name),
                is_primary=True,
            )
        ]
        if payload.secondary_measurement:
            secondary_key = _slug(payload.secondary_measurement.display_name)
            if secondary_key == primary_key:
                secondary_key += "_2"
            metrics.append(SlaMetricInput(
                metric_key=secondary_key,
                display_name=payload.secondary_measurement.display_name,
                unit=payload.secondary_measurement.unit,
                target_numeric=payload.secondary_measurement.target_value,
                direction=_smart_direction(payload.secondary_measurement.display_name),
                is_primary=False,
            ))

        # 3. Build condition_bands from the RFP "Target" rows (severity SLAs)
        #    OR a lookup_table from linear escalation (deliverable / query SLAs).
        condition_bands: List = []
        lookup_table: List = []
        if payload.target_rows:
            for idx, row in enumerate(payload.target_rows):
                condition_bands.append(SlaConditionBandInput(
                    metric_key=primary_key,
                    band_label=row.threshold_label
                        or f"L{row.severity} {_band_default_label(row)}",
                    range_min=row.from_value,
                    range_max=row.to_value,
                    range_unit=payload.measurement.unit or None,
                    severity_level=row.severity,
                    sort_order=idx + 1,
                ))
        if payload.linear_escalation:
            esc = payload.linear_escalation
            rate = esc.rate_per_unit_percent
            grace = esc.grace_units
            # Tier `i` units of delay = max(0, i - grace) * rate %.
            for i in range(0, esc.max_units + 1):
                effective_units = max(0, i - grace)
                ld_pct = (Decimal(effective_units) * rate).quantize(Decimal("0.01"))
                lookup_table.append(SlaLookupRowInput(
                    lookup_key=f"{esc.unit}_{i}",
                    lookup_value=ld_pct,
                    sort_order=i + 1,
                ))

        # 4. Hand the translated payload to the existing onboarding path.
        # contract_type is now optional on the wire — if the caller omitted
        # it, pass None and let the row store NULL. (Future: derive from
        # the project via pmis-project-management.)
        #
        # We also stash the lossless RFP-form snapshot in metadata so the
        # ``GET /sla-masters/{id}`` endpoint can return exactly what the
        # operator typed in instead of reverse-engineering it from the
        # technical sub-tables.
        rfp_snapshot = payload.model_dump(mode="json")
        full = SlaOnboardRequest(
            sla_ref=payload.sla_ref,
            title=payload.title,
            project_id=payload.project_id,
            contract_type=payload.contract_type,
            formula_type=formula_type,
            description=payload.definition,
            category=category.display_name,
            scope_text=payload.scope,
            data_source=payload.data_source,
            calculation_method=payload.calculation,
            reports_submitted_to=payload.reports_submitted_to,
            measurement_interval=payload.measurement_interval,
            reporting_interval=payload.reporting_interval,
            ld_computation_base=payload.applied_on,
            effective_from=payload.effective_from,
            effective_until=payload.effective_until,
            metrics=metrics,
            condition_bands=condition_bands,
            lookup_table=lookup_table,
            placeholders=payload.placeholders,
            metadata={"rfp_form": rfp_snapshot},
        )
        return self.create_from_form(full, created_by=created_by)

    # ---------------------------------------------------------------- seed defaults

    def seed_default_slas(
        self,
        contract_types: Optional[List[str]] = None,
        created_by: Optional[str] = None,
        overwrite: bool = False,
        project_id: Optional[str] = None,
    ) -> dict:
        """Fan-out onboarding of RFP-default SLAs.

        Reads payloads from ``app.seed_data.sla_master_seeds`` and pushes each
        through ``create_from_form``. By default the seeder is idempotent: SLAs
        that already exist (matched by ``sla_ref`` or by
        ``(contract_type, title)``) are skipped.

        Args:
            contract_types: filter to only these codes (BSP / MSAP / MSIP / PMU).
                None = seed everything in the bundle.
            overwrite: when True, SLAs that already exist are *refreshed in place*
                with the latest seed values for the basic RFP-presentation fields
                (description, category, scope_text, data_source, calculation_method,
                reports_submitted_to, cadence, ld_computation_base, effective dates).
                Sub-tables (metrics, condition_bands, lookup_table, parameters,
                guards) are intentionally NOT touched — touching them risks
                breaking activity mappings that already reference the bands by
                id. Run ``DELETE`` then a fresh seed if you need a full reset.

        Returns:
            {
              "seeded":            N,
              "overwritten":       N,  # only non-zero when overwrite=True
              "skipped_existing":  N,
              "failed":            [{sla_ref, error}, ...],
              "total_candidates":  N,
            }
        """
        from app.seed_data import ALL_SEED_SLAS, SEEDS_BY_CONTRACT
        from app.schemas.sla import SlaOnboardRequest, SlaUpdateRequest

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

        # Fields that overwrite mode refreshes on existing rows. Notably absent:
        # sla_ref (the identity), contract_type, formula_type (changing those
        # would invalidate downstream evaluator state) and sub-tables.
        _OVERWRITE_FIELDS = (
            "title", "description", "category", "scope_text", "data_source",
            "calculation_method", "reports_submitted_to",
            "measurement_interval", "reporting_interval", "ld_computation_base",
            "effective_from", "effective_until",
            # The new attributes also get refreshed so existing seeds pick up
            # the project binding and the per-mapping variable list.
            "project_id", "placeholders",
        )

        seeded = 0
        overwritten = 0
        skipped = 0
        failed: List[dict] = []
        for raw in payloads:
            sla_ref = raw.get("sla_ref")
            # Stamp every seeded SLA with the caller's project_id so the
            # bundle becomes "this project's SLA catalogue". Without a
            # project_id the SLAs stay catalog templates (the legacy
            # behaviour for seeds run before the project-binding work).
            if project_id:
                raw = {**raw, "project_id": project_id}
            try:
                req = SlaOnboardRequest(**raw)
            except Exception as exc:  # pragma: no cover — defensive
                failed.append({"sla_ref": sla_ref, "error": f"schema: {exc}"})
                continue
            try:
                self.create_from_form(req, created_by=created_by)
                seeded += 1
            except ConflictError:
                if not overwrite:
                    skipped += 1
                    continue
                # Refresh the basic fields on the existing row so SLAs seeded
                # before the RFP-fields enrichment pick up category / scope_text /
                # data_source / calculation_method / reports_submitted_to.
                existing = self.repo.get_by_ref(sla_ref)
                if existing is None:
                    # Title-collision conflict (different sla_ref, same title in
                    # the same contract_type). Can't safely refresh — skip.
                    skipped += 1
                    continue
                try:
                    update_payload = SlaUpdateRequest(**{
                        k: getattr(req, k) for k in _OVERWRITE_FIELDS
                        if getattr(req, k, None) is not None
                    })
                    self.update_basic(existing.id, update_payload)
                    overwritten += 1
                except Exception as exc:
                    failed.append({"sla_ref": sla_ref, "error": f"overwrite: {exc}"})
            except Exception as exc:
                failed.append({"sla_ref": sla_ref, "error": str(exc)})

        return {
            "seeded": seeded,
            "overwritten": overwritten,
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

        # Duplicate check 1 — same title in same contract_type. Skipped
        # when contract_type is None (project-scoped flow); duplicate
        # protection there comes from the sla_ref uniqueness check above.
        if payload.contract_type and self.repo.find_by_title_and_contract_type(
            payload.contract_type, payload.title,
        ) is not None:
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

        # Create definition. project_id is now first-class — when the
        # caller supplies it the SLA belongs to that project, otherwise it
        # remains a catalog template (legacy behaviour).
        defn = SlaDefinition(
            project_id=payload.project_id,
            contract_type=payload.contract_type,
            formula_id=formula.id,
            sla_ref=payload.sla_ref,
            title=payload.title,
            description=payload.description,
            # RFP-native presentation fields (UIDAI RFP §5.28 row headers).
            category=payload.category,
            scope_text=payload.scope_text,
            data_source=payload.data_source,
            calculation_method=payload.calculation_method,
            reports_submitted_to=payload.reports_submitted_to,
            measurement_interval=payload.measurement_interval,
            reporting_interval=payload.reporting_interval,
            baseline_type=payload.baseline_type,
            compound_metric_rule=payload.compound_metric_rule,
            ld_aggregation_method=payload.ld_aggregation_method,
            ld_computation_base=payload.ld_computation_base,
            metadata_=payload.metadata,
            # Per-mapping variables (typed list). The mapping form renders
            # one input per entry; empty list means "no placeholders, just
            # attach the template to an activity".
            placeholders=[p.model_dump() for p in payload.placeholders] if payload.placeholders else [],
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
        project_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[List[SlaDefinitionResponse], int]:
        rows = self.repo.list_definitions_with_formula(
            contract_type=contract_type,
            formula_type=formula_type,
            status=status,
            project_id=project_id,
            skip=skip,
            limit=limit,
        )
        total = self.repo.count_definitions(
            contract_type=contract_type,
            formula_type=formula_type,
            status=status,
            project_id=project_id,
        )
        items = [self._build_flat(defn, ft) for defn, ft in rows]
        # Embed live attachments in one batch query so the FE list / gallery
        # renders straight from this response (no N+1 follow-ups).
        if items:
            atts = self._attachments_for_many([i.id for i in items])
            for it in items:
                it.attachments = atts.get(it.id, [])
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
        resp = self._build_detail(defn, ft, metrics, params, bands, lookup_rows, guards)
        resp.attachments = self._attachments_for_one(sla_id)
        return resp

    # ---------------------------------------------------------------- RFP-friendly view

    def get_rfp_view(self, sla_id: str):
        """Build the operator-facing view of an SLA.

        Pulls the RFP-form snapshot stashed at onboarding when available,
        otherwise reverse-engineers the same shape from the technical
        sub-tables. Either way the response carries no metric_key /
        sort_order / range_min — those live on GET /{id}/parsed.
        """
        from app.schemas.sla import (
            SlaRfpViewResponse,
            SlaSimpleLinearEscalation,
            SlaSimpleMeasurement,
            SlaSimpleTargetRow,
        )

        defn = self.repo.get_by_id(sla_id)
        if defn is None:
            raise NotFoundError(f"SLA '{sla_id}' not found")

        metrics = self.repo.list_metrics(sla_id)
        bands = self.repo.list_bands(sla_id)
        lookup_rows = self.repo.list_lookup_rows(sla_id)
        stash = (defn.metadata_ or {}).get("rfp_form") or {}

        # ── measurement / secondary_measurement ──
        # Stash wins if present (it carries the exact strings the user
        # typed); otherwise pluck from the primary / secondary metric.
        measurement = None
        if stash.get("measurement"):
            measurement = SlaSimpleMeasurement(**stash["measurement"])
        else:
            primary = next((m for m in metrics if m.is_primary), None) or (metrics[0] if metrics else None)
            if primary:
                measurement = SlaSimpleMeasurement(
                    display_name=primary.display_name or primary.metric_key,
                    unit=primary.unit,
                )
        secondary_measurement = None
        if stash.get("secondary_measurement"):
            secondary_measurement = SlaSimpleMeasurement(**stash["secondary_measurement"])
        else:
            secondaries = [m for m in metrics if not m.is_primary]
            if secondaries:
                secondary_measurement = SlaSimpleMeasurement(
                    display_name=secondaries[0].display_name or secondaries[0].metric_key,
                    unit=secondaries[0].unit,
                )

        # ── target_rows ──
        target_rows: List = []
        if stash.get("target_rows"):
            target_rows = [SlaSimpleTargetRow(**r) for r in stash["target_rows"]]
        elif bands:
            for b in sorted(bands, key=lambda x: x.sort_order or 0):
                target_rows.append(SlaSimpleTargetRow(
                    severity=b.severity_level,
                    threshold_label=b.band_label or "",
                    from_value=str(b.range_min) if b.range_min is not None else None,
                    to_value=str(b.range_max) if b.range_max is not None else None,
                ))

        # ── linear_escalation ──
        # Stash gives us the exact rate / unit / grace the user typed.
        # Reverse-engineering from the expanded lookup_table is lossy
        # (we lose the "unit" choice), so we only do it when there's no
        # stash. Tolerate two stash shapes: the canonical one with
        # ``rate_per_unit_percent`` (post-fix) and the legacy
        # ``rate_percent`` field name (pre-fix). The latter rides on a
        # handful of SLAs onboarded before this method existed.
        linear_escalation = None
        if stash.get("linear_escalation"):
            le = dict(stash["linear_escalation"])
            if "rate_percent" in le and "rate_per_unit_percent" not in le:
                le["rate_per_unit_percent"] = le.pop("rate_percent")
            try:
                linear_escalation = SlaSimpleLinearEscalation(**le)
            except Exception:
                # Legacy / malformed stash — fall back to lookup-table derivation.
                linear_escalation = None
        if linear_escalation is None and lookup_rows:
            sorted_rows = sorted(lookup_rows, key=lambda x: x.sort_order or 0)
            # Find first non-zero row → tells us grace count + the rate.
            rate = None
            grace = 0
            for idx, r in enumerate(sorted_rows):
                if r.lookup_value and r.lookup_value > 0:
                    if idx == 0:
                        rate = r.lookup_value
                    else:
                        rate = r.lookup_value - (sorted_rows[idx - 1].lookup_value or 0)
                        grace = idx - (1 if (sorted_rows[idx - 1].lookup_value or 0) == 0 else 0)
                    break
            # The SlaSimpleLinearEscalation schema constrains rate to
            # (0, 10] %. Real PMU rates are 0.1–1%, so any reverse-engineered
            # value outside that band means we can't faithfully express the
            # SLA as "linear escalation" — return None and let the FE fall
            # back to showing the verbose lookup table instead.
            if rate is not None and 0 < rate <= 10:
                linear_escalation = SlaSimpleLinearEscalation(
                    rate_per_unit_percent=rate, unit="week", grace_units=grace,
                    max_units=max(len(sorted_rows) - 1, 1),
                )

        # placeholders — the row itself is canonical (JSONB column).
        placeholders = defn.placeholders or []

        return SlaRfpViewResponse(
            id=defn.id,
            sla_ref=defn.sla_ref,
            title=defn.title,
            project_id=defn.project_id,
            contract_type=defn.contract_type,
            category=defn.category,
            status=defn.status,
            # Both naming conventions ride along so old + new FE code keep working.
            description=defn.description,
            definition=stash.get("definition") or defn.description,
            scope_text=defn.scope_text,
            scope=stash.get("scope") or defn.scope_text,
            data_source=defn.data_source,
            calculation_method=defn.calculation_method,
            calculation=stash.get("calculation") or defn.calculation_method,
            reports_submitted_to=defn.reports_submitted_to,
            measurement_interval=defn.measurement_interval,
            reporting_interval=defn.reporting_interval,
            ld_computation_base=defn.ld_computation_base,
            applied_on=defn.ld_computation_base,
            effective_from=defn.effective_from,
            effective_until=defn.effective_until,
            measurement=measurement,
            secondary_measurement=secondary_measurement,
            target_rows=target_rows,
            linear_escalation=linear_escalation,
            placeholders=placeholders,
            attachments=self._attachments_for_one(sla_id),
            created_at=defn.created_at,
            updated_at=defn.updated_at,
        )

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
