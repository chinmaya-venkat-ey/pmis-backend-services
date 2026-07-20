"""SLA compliance runner — the brain of the automated daily evaluation.

For one active mapping (or all of them, from the cron) it:
  1. sources the observed value — auto delay-days from the activity's dates
     for deadline SLAs, or the latest recorded observation otherwise;
  2. runs the existing engine in-process (``evaluate_by_sla_ref``);
  3. derives a **formula-aware** verdict + status (a fixed_escalation breach
     shows on ``breaches[].rate_percent``, not ``ld_percent``);
  4. computes the LD money against the contract base (per the SLA's
     ``ld_computation_base``); and
  5. writes one ``sla_evaluation_results`` row per (mapping, day).

Also records manual observations (the input side of the observations layer).

Decisions this encodes (see the design doc):
  A target-days from the planned window (+ grace) · B delay = max(0,
  actual − target − grace) with actual = (actual_end | today) − start ·
  D resource/%/count SLAs = recorded observations · E honour
  ld_computation_base, FIXED_AMOUNT resolved here, quarterly/annual bases
  resolved by the cost-page consumer.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as _date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients.db_activity_resolver import DbActivityResolver
from app.core.errors import NotFoundError, ValidationError
from app.models.sla_activity_mapping import SlaActivityMapping
from app.models.sla_definition import SlaDefinition
from app.models.sla_evaluation_result import SlaEvaluationResult
from app.models.sla_observation import SlaObservation
from app.models.sla_parameter_value import SlaParameterValue
from app.models.sla_quarterly_aggregate import SlaQuarterlyAggregate
from app.repositories.sla_activity_mapping_repository import SlaActivityMappingRepository
from app.repositories.sla_quarterly_aggregate_repository import (
    SlaQuarterlyAggregateRepository,
)
from app.schemas.sla_evaluation import SimpleEvaluationRequest
from app.services.ld_bands import ld_percent_for_points, resolve_band_pairs
from app.services.sla_evaluator.service import SlaEvaluatorService
from app.services.sla_evaluator.point_accumulation import DEFAULT_LEVEL_POINTS
from app.utilities.logger import get_logger
from app.utilities.quarter import QuarterKey, previous_quarter, quarter_of


def _sla_family_number(sla_ref: Optional[str]) -> Optional[int]:
    """Extract the SLA family number from ``PMU-SLA008`` /
    ``PMU_SLA009_20260715...`` and every other variant."""
    if not sla_ref:
        return None
    import re
    m = re.search(r"SLA[-_]?0*(\d+)", sla_ref, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _carry_forward_severity_for(
    sla_ref: Optional[str],
    contract_ld_rules: Dict[str, Decimal],
) -> Optional[int]:
    """Return the severity level to carry, sourced from
    ``contract_ld_rules`` (DSL — see migration 0023 seeds
    ``sla_008_carry_forward_severity=4``, ``sla_009_carry_forward_severity=2``
    for PMU). Returns None when no rule matches — the rollup falls back
    to the previous quarter's own severity in that case."""
    family = _sla_family_number(sla_ref)
    if family is None:
        return None
    val = contract_ld_rules.get(f"sla_{family:03d}_carry_forward_severity")
    return int(val) if val is not None else None


logger = get_logger(__name__)

# Formulas whose observation (days delayed) can be auto-derived from the
# activity's own dates. Everything else needs a recorded observation.
_DATE_DERIVABLE = {"fixed_escalation"}


# Severity bucketing for linear-LD (fixed_escalation) results — the
# formula doesn't emit severity_level natively, so we bucket the
# effective LD % into the same 0-4 scale banded SLAs use, so the FE
# renders a uniform "Severity" column across every SLA type. Thresholds
# roughly track the PMU RFP's severity progression:
#   ≤ 0%   → 0 (no breach; met=true takes this path)
#   ≤ 1%   → 1
#   ≤ 2%   → 2
#   ≤ 5%   → 3
#   >  5%  → 4 (capped tier / significant breach)
def _severity_from_ld_pct(ld_pct: Decimal) -> int:
    if ld_pct <= 0:      return 0
    if ld_pct <= 1:      return 1
    if ld_pct <= 2:      return 2
    if ld_pct <= 5:      return 3
    return 4


def _parse_date(v: Any) -> Optional[_date]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v)).date()
    except ValueError:
        try:
            return _date.fromisoformat(str(v)[:10])
        except ValueError:
            return None


def _num(v) -> Optional[Decimal]:
    return None if v is None else Decimal(str(v))


class SlaComplianceService:
    def __init__(self, db: Session):
        self.db = db
        # DB-backed activity resolution (reads project.activities cross-schema)
        # so the cron needs no bearer — just its shared secret.
        self.resolver = DbActivityResolver(db)
        self.evaluator = SlaEvaluatorService(db, self.resolver)
        self.mapping_repo = SlaActivityMappingRepository(db)
        self.qtr_agg_repo = SlaQuarterlyAggregateRepository(db)

    # ================================================================= observations

    def record_observation(
        self, *, mapping_id: str, observed_value: Any, metric_key: Optional[str] = None,
        source: str = "recorded", period_start: Optional[_date] = None,
        period_end: Optional[_date] = None, note: Optional[str] = None,
        recorded_by: Optional[str] = None,
    ) -> SlaObservation:
        loaded = self.mapping_repo.load_with_sla(mapping_id)
        if loaded is None:
            raise NotFoundError(f"Mapping '{mapping_id}' not found", code="mapping_not_found")
        mapping, _sla, _ft = loaded
        row = SlaObservation(
            id=str(uuid4()), mapping_id=mapping_id, sla_id=mapping.sla_id,
            activity_id=mapping.activity_id, project_id=None,
            metric_key=metric_key, observed_value=observed_value, source=source,
            period_start=period_start, period_end=period_end, note=note, recorded_by=recorded_by,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _latest_observation(self, mapping_id: str) -> Optional[SlaObservation]:
        return self.db.execute(
            select(SlaObservation).where(SlaObservation.mapping_id == mapping_id)
            .order_by(SlaObservation.created_at.desc()).limit(1)
        ).scalars().first()

    # ================================================================= derivation

    def _grace_days(self, sla_id: str) -> int:
        raw = self.db.execute(
            select(SlaParameterValue.param_value)
            .where(SlaParameterValue.sla_id == sla_id, SlaParameterValue.param_key == "grace_days")
        ).scalar()
        try:
            return int(float(raw)) if raw is not None else 0
        except (TypeError, ValueError):
            return 0

    def _derive_days(self, activity: Dict[str, Any], grace: int) -> Optional[Dict[str, Decimal]]:
        """target = planned window (end − start); actual = (actual_end|today) − start;
        delay = max(0, actual − target − grace). All in days."""
        start = _parse_date(activity.get("startDate"))
        planned_end = _parse_date(activity.get("endDate"))
        actual_end = _parse_date(activity.get("actualEndDate"))
        if start is None or planned_end is None:
            return None
        today = datetime.now(timezone.utc).date()
        ref = actual_end or today
        target = (planned_end - start).days
        actual = (ref - start).days
        delay = max(0, actual - target - grace)
        return {"target": Decimal(target), "actual": Decimal(actual), "delay": Decimal(delay)}

    # ================================================================= verdict (formula-aware)

    @staticmethod
    def _verdict(result) -> Tuple[str, bool, bool]:
        """Return (status, met, breached). Reads the right output field per engine."""
        # guard-triggered exclusion/suspension
        for g in (result.guards or []):
            action = (getattr(g, "action", "") or "").upper()
            if getattr(g, "triggered", False) and action in ("SUSPEND", "EXCLUDE"):
                return "excluded", False, False

        breached = False
        if result.ld_percent is not None and result.ld_percent > 0:
            breached = True
        if result.severity_level is not None and result.severity_level >= 1:
            breached = True
        for b in (result.breaches or []):
            rate = getattr(b, "rate_percent", None)
            sev = getattr(b, "severity_level", None)
            pts = getattr(b, "points_contribution", None)
            if (rate and rate > 0) or (sev is not None and sev >= 1) or (pts and pts > 0):
                breached = True
                break

        if breached:
            return "breached", False, True
        return "compliant", True, False

    @staticmethod
    def _effective_ld_percent(result) -> Optional[Decimal]:
        if result.ld_percent is not None:
            return Decimal(str(result.ld_percent))
        rates = [Decimal(str(b.rate_percent)) for b in (result.breaches or [])
                 if getattr(b, "rate_percent", None)]
        return max(rates) if rates else None

    def _ld_money(self, result, sla: SlaDefinition, mapping: SlaActivityMapping
                  ) -> Tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal], Optional[str]]:
        """(ld_percent, ld_amount, base_amount, base_kind). Contract-accurate:
        FIXED_AMOUNT resolves here from the mapping's ld_base_amount; quarterly/
        annual bases are left for the cost-page consumer (which owns payments)."""
        ld_pct = self._effective_ld_percent(result)
        base_kind = getattr(sla, "ld_computation_base", None)
        base_amount: Optional[Decimal] = None
        overrides = mapping.overrides or {}
        if base_kind == "FIXED_AMOUNT":
            base_amount = _num(overrides.get("ld_base_amount"))
        ld_amount = None
        if ld_pct is not None and base_amount is not None:
            ld_amount = (ld_pct / Decimal("100")) * base_amount
        return ld_pct, ld_amount, base_amount, base_kind

    # ================================================================= per-mapping run

    def evaluate_and_persist(self, mapping_id: str, on_date: _date) -> str:
        loaded = self.mapping_repo.load_with_sla(mapping_id)
        if loaded is None:
            raise NotFoundError(f"Mapping '{mapping_id}' not found", code="mapping_not_found")
        mapping, sla, formula_type = loaded
        if mapping.status != "ACTIVE" or formula_type is None:
            return "skipped"

        activity = self.resolver.get_activity(mapping.activity_id) or {}
        project_id = activity.get("projectId") or activity.get("project_id")
        milestone_id = activity.get("milestoneId") or activity.get("milestone_id")
        grace = self._grace_days(mapping.sla_id)

        days = None
        if formula_type in _DATE_DERIVABLE and activity:
            days = self._derive_days(activity, grace)

        if formula_type in _DATE_DERIVABLE and days is not None:
            observed: Any = int(days["delay"])
            source = "auto"
        else:
            obs = self._latest_observation(mapping_id)
            if obs is None:
                self._persist(mapping, sla, formula_type, on_date, None,
                              status="pending_observation", met=False, breached=False,
                              days=days, observed=None, project_id=project_id,
                              milestone_id=milestone_id, ld=(None, None, None,
                              getattr(sla, "ld_computation_base", None)))
                return "pending_observation"
            observed = obs.observed_value
            source = "recorded"

        try:
            result = self.evaluator.evaluate_by_sla_ref(
                mapping.activity_id, sla.sla_ref,
                SimpleEvaluationRequest(value=observed),
            )
        except (ValidationError, NotFoundError):
            return "skipped"

        status, met, breached = self._verdict(result)
        ld = self._ld_money(result, sla, mapping)
        self._persist(mapping, sla, formula_type, on_date, result, status=status,
                      met=met, breached=breached, days=days, observed=observed,
                      project_id=project_id, milestone_id=milestone_id, ld=ld)
        return status

    def _persist(self, mapping, sla, formula_type, on_date, result, *, status, met,
                 breached, days, observed, project_id, milestone_id, ld):
        ld_pct, ld_amount, base_amount, base_kind = ld
        breaches_json = None
        severity = points = None
        p_start = p_end = None
        if result is not None:
            breaches_json = [b.model_dump(mode="json") for b in (result.breaches or [])]
            severity = result.severity_level
            points = result.accumulated_points
            p_start, p_end = result.period_start, result.period_end

        # As of the shared-normaliser fix, severity_level and
        # accumulated_points are guaranteed populated by SlaEvaluatorService
        # for every formula type — this block is a defensive re-run of the
        # same bucketing in case the caller passed a hand-built result (e.g.
        # tests) that skipped the normaliser.
        if severity is None:
            if met:
                severity = 0
            elif breached and ld_pct is not None:
                severity = _severity_from_ld_pct(ld_pct)
        if points is None and ld_pct is not None:
            points = ld_pct

        existing = self.db.execute(
            select(SlaEvaluationResult).where(
                SlaEvaluationResult.mapping_id == mapping.id,
                SlaEvaluationResult.evaluated_on == on_date,
            )
        ).scalars().first()

        fields = dict(
            sla_id=mapping.sla_id, sla_ref=sla.sla_ref, activity_id=mapping.activity_id,
            milestone_id=milestone_id, project_id=project_id,
            period_start=p_start, period_end=p_end, formula_type=formula_type,
            status=status, met=met, breached=breached,
            severity_level=severity, accumulated_points=points, ld_percent=ld_pct,
            ld_amount=ld_amount, ld_base_amount=base_amount, ld_base_kind=base_kind,
            target_days=(days or {}).get("target"), actual_days=(days or {}).get("actual"),
            delay_days=(days or {}).get("delay"),
            observed_value=observed, breaches=breaches_json,
        )
        if existing is not None:
            for k, v in fields.items():
                setattr(existing, k, v)
        else:
            self.db.add(SlaEvaluationResult(id=str(uuid4()), mapping_id=mapping.id,
                                            evaluated_on=on_date, **fields))
        self.db.commit()

    # ================================================================= daily cron

    def run_daily(self, on_date: Optional[_date] = None) -> Dict[str, Any]:
        on_date = on_date or datetime.now(timezone.utc).date()
        active = self.db.execute(
            select(SlaActivityMapping).where(SlaActivityMapping.status == "ACTIVE")
        ).scalars().all()
        counts: Dict[str, int] = defaultdict(int)
        for m in active:
            try:
                counts[self.evaluate_and_persist(m.id, on_date)] += 1
            except Exception:  # noqa: BLE001 — one bad mapping must not stop the run
                counts["error"] += 1

        # Phase B — after every daily evaluation, refresh the current-quarter
        # rollup for every active mapping so `sla_quarterly_aggregate` stays
        # in step with the evaluation stream. Late observations that land
        # inside a still-open quarter therefore reflect immediately in the
        # aggregate; the settlement service (Phase D) reads only from
        # `sla_quarterly_aggregate` and never re-sums evaluation rows itself.
        qk = quarter_of(on_date)
        rollup_counts: Dict[str, int] = defaultdict(int)
        for m in active:
            try:
                self.rollup_mapping_for_quarter(m.id, qk)
                rollup_counts["ok"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "rollup_quarterly failed for mapping=%s quarter=%s: %s",
                    m.id, qk.label(), exc,
                )
                rollup_counts["error"] += 1

        # Phase D — on quarter_end+1, auto-close the just-ended quarter's
        # settlement rows for every project that has active mappings.
        # (Delegated to QuarterlySettlementService which self-guards on the
        # date so it's safe to call every day.)
        auto_closed_projects: List[str] = []
        try:
            from app.services.quarterly_settlement_service import (
                QuarterlySettlementService,
            )
            auto_closed_projects = QuarterlySettlementService(
                self.db, compliance_service=self,
            ).close_projects_ready_to_close(on_date=on_date)
        except Exception as exc:  # noqa: BLE001
            logger.warning("auto-close sweep failed: %s", exc)

        return {
            "evaluatedOn": on_date.isoformat(),
            "activeMappings": len(active),
            "outcomes": dict(counts),
            "quarterlyRollup": {
                "quarterKey": qk.label(),
                "counts": dict(rollup_counts),
            },
            "quarterlyAutoClose": {
                "projectsClosed": len(auto_closed_projects),
            },
        }

    # ================================================================= quarterly rollup (Phase B)
    #
    # Implements RFP §5.28.1.a-c: for one mapping in one quarter, sum every
    # evaluation_result's accumulated_points, look up the ladder ONCE, and
    # write / update the single sla_quarterly_aggregate row for that
    # (mapping, quarter). This is where "reset at end of reporting
    # interval" actually happens: each quarter is a fresh sum, independent
    # of prior quarters.

    def rollup_mapping_for_quarter(
        self, mapping_id: str, qk: QuarterKey,
    ) -> Optional[SlaQuarterlyAggregate]:
        """Refresh one mapping's quarterly aggregate row.

        Sums accumulated_points across every evaluation_result whose
        ``evaluated_on`` falls in the quarter, feeds the total to the
        project's LD chart via ld_percent_for_points, and upserts the
        result into contract.sla_quarterly_aggregate. Idempotent —
        re-running for the same (mapping, quarter) overwrites the row.

        Phase F2 — when ``sla.carry_forward_severity=True`` (SLA 008/009)
        AND the previous quarter had a breach AND this quarter shows no
        resolution (no evaluation row with met=True), a synthetic carry-
        forward row is emitted with the previous severity's points and
        ``carried_forward=True`` marked for the audit trail.

        Returns the persisted row, or None if the mapping has neither
        evaluations nor a carry-forward from the previous quarter.
        """
        loaded = self.mapping_repo.load_with_sla(mapping_id)
        if loaded is None:
            return None
        mapping, sla, _formula_type = loaded

        # Pull every evaluation row in this mapping × quarter.
        rows = self.db.execute(
            select(
                SlaEvaluationResult.id,
                SlaEvaluationResult.accumulated_points,
                SlaEvaluationResult.project_id,
                SlaEvaluationResult.activity_id,
                SlaEvaluationResult.met,
            ).where(
                SlaEvaluationResult.mapping_id == mapping_id,
                SlaEvaluationResult.evaluated_on >= qk.quarter_start,
                SlaEvaluationResult.evaluated_on <= qk.quarter_end,
            ).order_by(SlaEvaluationResult.evaluated_on)
        ).all()

        # Sum points from actual observations; track if any evaluation
        # resolved (met=True) — needed for the carry-forward gate.
        total_points = Decimal("0")
        source_ids: List[str] = []
        this_quarter_resolved = False
        for r in rows:
            if r.accumulated_points is not None:
                total_points += Decimal(str(r.accumulated_points))
            source_ids.append(r.id)
            if r.met:
                this_quarter_resolved = True

        # Phase F2 — carry-forward gate.
        carry_points, carry_severity, carry_note = Decimal("0"), None, None
        if (
            getattr(sla, "carry_forward_severity", False)
            and not this_quarter_resolved
        ):
            prev_qk = previous_quarter(qk)
            prev = self.qtr_agg_repo.get(mapping_id=mapping_id, qk=prev_qk)
            if prev is not None and (prev.derived_severity or 0) >= 1:
                # Carry-forward severity is DATA-DRIVEN — sourced from
                # contract_ld_rules per SLA family (RFP-specific values
                # seeded in migration 0023, e.g. sla_008=4, sla_009=2).
                # If no rule exists, fall back to the previous quarter's
                # own severity — preserves the breach's magnitude even
                # for un-configured families.
                rules = self.evaluator._load_contract_ld_rules(sla.contract_type)
                cf_sev = _carry_forward_severity_for(sla.sla_ref, rules)
                if cf_sev is None:
                    cf_sev = int(prev.derived_severity)
                cf_points = DEFAULT_LEVEL_POINTS.get(cf_sev, Decimal("0"))
                total_points += cf_points
                carry_points = cf_points
                carry_severity = cf_sev
                carry_note = (
                    f"carried from {prev_qk.label()} "
                    f"(prev sev={prev.derived_severity}, "
                    f"cf sev={cf_sev}, cf points={cf_points})"
                )

        # If neither observations nor a carry-forward apply, leave the
        # aggregate alone (returning None) — safer than writing an empty row.
        if not rows and carry_points == 0:
            return None

        # Ladder lookup — project's chart if configured, RFP default otherwise.
        scoring = self.evaluator._resolve_project_scoring(
            mapping.activity_id, bearer_token=None,
        )
        ld_pct = ld_percent_for_points(total_points, scoring["ld_band_pairs"])

        # Highest severity in this quarter = max(observed row severities, carry_severity).
        sev_row = self.db.execute(
            select(func.max(SlaEvaluationResult.severity_level)).where(
                SlaEvaluationResult.mapping_id == mapping_id,
                SlaEvaluationResult.evaluated_on >= qk.quarter_start,
                SlaEvaluationResult.evaluated_on <= qk.quarter_end,
            )
        ).scalar()
        derived_sev = None
        if sev_row is not None:
            derived_sev = int(sev_row)
        if carry_severity is not None:
            derived_sev = max(derived_sev or 0, carry_severity)

        # Project id / activity id — prefer freshest observation row;
        # fall back to the mapping's own activity_id (needed when the row
        # is carry-forward-only, no observations in this quarter).
        if rows:
            project_id = rows[-1].project_id or ""
            activity_id = rows[-1].activity_id or mapping.activity_id
        else:
            # Carry-forward-only: derive project_id via resolver.
            act = self.resolver.get_activity(mapping.activity_id) or {}
            project_id = act.get("projectId") or act.get("project_id") or ""
            activity_id = mapping.activity_id

        notes: Dict[str, Any] = {"sourceRowCount": len(source_ids)}
        if carry_note:
            notes["carryForward"] = carry_note

        return self.qtr_agg_repo.upsert(
            mapping_id=mapping_id,
            sla_id=sla.id,
            sla_ref=sla.sla_ref,
            project_id=project_id,
            activity_id=activity_id,
            qk=qk,
            accumulated_points=total_points,
            derived_severity=derived_sev,
            ld_percent=ld_pct,
            source_result_ids=source_ids,
            carried_forward=(carry_severity is not None),
            notes=notes,
        )

    def rollup_project_for_quarter(
        self, project_id: str, qk: QuarterKey,
    ) -> List[SlaQuarterlyAggregate]:
        """Roll up every mapping on a project that either had evaluations
        this quarter OR needs a carry-forward from the previous quarter.

        Reads from ``sla_evaluation_results`` (which carries ``project_id``
        directly) to identify the exact mapping set to refresh, avoiding
        the O(N) cross-schema resolver walk. Also picks up
        carry-forward-only mappings (SLA 008/009 that had a breach in
        the previous quarter and have no evaluation this quarter yet).
        """
        # 1. Mappings with evaluations in the current quarter.
        current_ids = set(self.db.execute(
            select(SlaEvaluationResult.mapping_id).where(
                SlaEvaluationResult.project_id == project_id,
                SlaEvaluationResult.evaluated_on >= qk.quarter_start,
                SlaEvaluationResult.evaluated_on <= qk.quarter_end,
            ).distinct()
        ).scalars().all())

        # 2. Phase F2 — mappings that had a breach LAST quarter on
        # carry-forward SLAs. rollup_mapping_for_quarter's own gate
        # decides whether to actually emit a synthetic row.
        prev_qk = previous_quarter(qk)
        carry_candidates = set(self.db.execute(
            select(SlaQuarterlyAggregate.mapping_id).where(
                SlaQuarterlyAggregate.project_id == project_id,
                SlaQuarterlyAggregate.fiscal_year == prev_qk.fiscal_year,
                SlaQuarterlyAggregate.quarter == prev_qk.quarter,
                SlaQuarterlyAggregate.derived_severity >= 1,
            )
        ).scalars().all())

        results: List[SlaQuarterlyAggregate] = []
        for mid in current_ids | carry_candidates:
            row = self.rollup_mapping_for_quarter(mid, qk)
            if row is not None:
                results.append(row)
        return results

    # ================================================================= activity completion
    #
    # Called by project-management when an activity moves to COMPLETED
    # (or actual_end_date is set). For each active mapping on the
    # activity:
    #   * date-derivable formula (``fixed_escalation``)  → auto-evaluate.
    #     A row lands in sla_evaluation_results immediately.
    #   * non-date-derivable formula                     → mark as
    #     pending_observation, then email project + activity owners so
    #     they know a manual value has to be recorded.
    #
    # This method is idempotent — re-running the same activity's flow
    # replaces its row for the current on_date (the (mapping_id,
    # evaluated_on) unique key in _persist takes care of that).

    def on_activity_complete(
        self,
        activity_id: str,
        *,
        on_date: Optional[_date] = None,
    ) -> Dict[str, Any]:
        """Run SLA evaluation for every active mapping on this activity.

        Auto-evaluates date-derivable SLAs, emails owners for the rest.
        Returns a per-mapping summary the caller can log / display.
        """
        on_date = on_date or datetime.now(timezone.utc).date()

        # Local imports keep module-load time small when the flow is unused.
        from app.clients.notification_client import (
            NotificationClient, TEMPLATE_SLA_MANUAL_REVIEW,
        )
        from app.repositories.sla_activity_mapping_repository import (
            SlaActivityMappingRepository,
        )

        mapping_repo = SlaActivityMappingRepository(self.db)
        active_rows = mapping_repo.list_for_activity(activity_id, active_only=True)

        auto_evaluated: List[Dict[str, Any]] = []
        manual_needed: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        # Pull activity + project context once — needed for the email payload.
        # Fetch via the resolver (which uses either project-mgmt HTTP or the
        # cross-schema mirror). Best-effort — missing context degrades to
        # "unknown" strings in the email rather than an exception.
        activity_ctx = self.resolver.get_activity(activity_id) or {}
        project_id = (
            activity_ctx.get("projectId")
            or activity_ctx.get("project_id")
        )

        notifier = NotificationClient()

        for mapping, sla, formula_type in active_rows:
            if formula_type is None:
                errors.append({
                    "mapping_id": mapping.id, "sla_ref": sla.sla_ref,
                    "reason": "formula_type not resolved",
                })
                continue
            try:
                status = self.evaluate_and_persist(mapping.id, on_date)
            except Exception as exc:  # noqa: BLE001
                errors.append({
                    "mapping_id": mapping.id, "sla_ref": sla.sla_ref,
                    "reason": f"{type(exc).__name__}: {exc}",
                })
                continue

            entry = {
                "mapping_id": mapping.id,
                "sla_id": sla.id,
                "sla_ref": sla.sla_ref,
                "formula_type": formula_type,
                "status": status,
            }

            if status == "pending_observation":
                # Manual input needed — email the owners so they can record it.
                # Wrapped in try/except so any notifier bug (NameError,
                # network glitch, template missing) NEVER 500s the whole
                # endpoint. The DB row already exists at
                # pending_observation status; a failure here just leaves
                # notification_sent_to empty for that entry.
                try:
                    emails_sent = self._notify_manual_review(
                        notifier=notifier,
                        activity_id=activity_id,
                        activity_ctx=activity_ctx,
                        mapping=mapping,
                        sla=sla,
                        project_id=project_id,
                    )
                except Exception as _exc:  # noqa: BLE001
                    from app.utilities.logger import get_logger
                    get_logger(__name__).warning(
                        "SLA manual-review notification raised for "
                        "activity=%s sla=%s: %s",
                        activity_id, sla.sla_ref, _exc,
                    )
                    emails_sent = []
                entry["notification_sent_to"] = emails_sent
                manual_needed.append(entry)
            else:
                auto_evaluated.append(entry)

        return {
            "activityId":      activity_id,
            "projectId":       project_id,
            "evaluatedOn":     on_date.isoformat(),
            "totalMappings":   len(active_rows),
            "autoEvaluated":   auto_evaluated,
            "manualNeeded":    manual_needed,
            "errors":          errors,
        }

    def _notify_manual_review(
        self, *, notifier, activity_id, activity_ctx, mapping, sla, project_id,
    ) -> List[str]:
        """Email + template dispatch to project + activity owners.

        Returns the list of email addresses we actually sent to. Empty
        list is fine (means we had no addresses to contact) — the
        pending_observation row stays in the DB either way, so a later
        cron / manual cleanup will retry.
        """
        # Recipient discovery — cross-schema query into project.*, no HTTP
        # hop back to project-mgmt just for emails. Ownership tables
        # discovered live on the VM:
        #   project.project_ownership     (role = 'project_owner' / 'owner')
        #   project.activity_assignments  (role = 'owner')
        # (Earlier code queried the wrong columns — projects.owner is a
        # division code, not a user_id. Fixed after live debug 2026-07-18.)
        from sqlalchemy import text as _sql_text
        recipients: List[str] = []
        try:
            if project_id:
                for r in self.db.execute(
                    _sql_text(
                        "SELECT DISTINCT u.email "
                        "FROM project.project_ownership po "
                        "JOIN users.users u ON u.id = po.user_id "
                        "WHERE po.project_id = :pid "
                        "  AND po.role IN ('project_owner', 'owner', 'owner_approver') "
                        "  AND po.deleted_at IS NULL "
                        "  AND u.email IS NOT NULL"
                    ),
                    {"pid": project_id},
                ).all():
                    if r[0] and r[0] not in recipients:
                        recipients.append(r[0])
            for r in self.db.execute(
                _sql_text(
                    "SELECT DISTINCT u.email "
                    "FROM project.activity_assignments aa "
                    "JOIN users.users u ON u.id = aa.user_id "
                    "WHERE aa.activity_id = :aid "
                    "  AND aa.role IN ('owner', 'owner_approver') "
                    "  AND aa.deleted_at IS NULL "
                    "  AND u.email IS NOT NULL"
                ),
                {"aid": activity_id},
            ).all():
                if r[0] and r[0] not in recipients:
                    recipients.append(r[0])
        except Exception as exc:  # noqa: BLE001
            # Owner-lookup failures shouldn't derail the completion flow —
            # log + fall through to send whatever we have (possibly nothing).
            from app.utilities.logger import get_logger
            get_logger(__name__).warning(
                "SLA manual-review owner lookup failed for activity %s: %s",
                activity_id, exc,
            )

        if not recipients:
            return []

        activity_name = (
            activity_ctx.get("name")
            or activity_ctx.get("activityName")
            or activity_id[:8]
        )
        payload = {
            "activity_id":   activity_id,
            "activity_name": activity_name,
            "project_id":    project_id,
            "sla_ref":       sla.sla_ref,
            "sla_title":     sla.title,
            "mapping_id":    mapping.id,
            "formula_type":  getattr(mapping, "formula_type", None),
        }

        # Two dispatches: (1) template-based (structured — notification-svc
        # renders + logs an audit trail), (2) direct email as fallback if
        # the template isn't installed yet on notification-svc. Template
        # dispatch is best-effort — a "template missing" from
        # notification-svc still returns 2xx.
        # Import here so this method is self-contained (called from
        # on_activity_complete but named referenced inside its own body
        # was NameError-ing on the first live test).
        from app.clients.notification_client import TEMPLATE_SLA_MANUAL_REVIEW
        for recipient in recipients:
            notifier.dispatch(
                template_kind=TEMPLATE_SLA_MANUAL_REVIEW,
                recipient=recipient,
                payload=payload,
                channel="email",
            )

        # Direct-email fallback so the operator sees a real message even
        # when the template doesn't exist in the notification catalog yet.
        subject = f"SLA needs manual evaluation — {sla.sla_ref} on {activity_name}"
        body = (
            f"Activity '{activity_name}' has been completed and one of its "
            f"SLAs ({sla.sla_ref} — {sla.title}) requires a manual "
            f"observation before it can be evaluated.\n\n"
            f"Activity ID: {activity_id}\n"
            f"Mapping ID:  {mapping.id}\n"
            f"SLA:         {sla.sla_ref}\n\n"
            f"Record the observation via:\n"
            f"  POST /api/v3/sla-compliance/observations\n"
            f"  body: {{\"mapping_id\": \"{mapping.id}\", "
            f"\"observed_value\": <value>, \"period_start\": <YYYY-MM-DD>, "
            f"\"period_end\": <YYYY-MM-DD>}}\n\n"
            f"Then trigger evaluation via:\n"
            f"  POST /api/v3/sla-compliance/mappings/{mapping.id}/evaluate\n"
        )
        notifier.send_email(to=recipients, subject=subject, body=body)
        return recipients
