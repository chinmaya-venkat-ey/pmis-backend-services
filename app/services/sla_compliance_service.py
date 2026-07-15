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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.db_activity_resolver import DbActivityResolver
from app.core.errors import NotFoundError, ValidationError
from app.models.sla_activity_mapping import SlaActivityMapping
from app.models.sla_definition import SlaDefinition
from app.models.sla_evaluation_result import SlaEvaluationResult
from app.models.sla_observation import SlaObservation
from app.models.sla_parameter_value import SlaParameterValue
from app.repositories.sla_activity_mapping_repository import SlaActivityMappingRepository
from app.schemas.sla_evaluation import SimpleEvaluationRequest
from app.services.sla_evaluator.service import SlaEvaluatorService

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
        return {"evaluatedOn": on_date.isoformat(), "activeMappings": len(active), "outcomes": dict(counts)}
