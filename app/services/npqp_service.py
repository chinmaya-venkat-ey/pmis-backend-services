"""NpqpService — Phase C.

Computes F, PA and QGR for a project × quarter (RFP §5.28.1.d), plus the
DELETED-clause reference ``NPQP = F + QGR`` (§5.28.1.d.e was DELETED by the
corrigendum — NPQP is a display/audit value only, NOT the LD base).

F   = "Planned Quarterly Payment applicable (aggregate of monthly payment
      of all resources to be deployed as per resource deployment plan
      Plus CCN resources, if any)." (§5.28.1.d.c). Read cross-schema from
      ``project.activity_planned_resources`` — the SAME per-activity plan the
      finance page uses — by summing ``computed_cost`` over the allocations whose
      ``planned_deployment_date`` falls in the (resource-phase-anchored) quarter.

PA  = "Payable amount for Actual resource deployment" (§5.28.1.d.g).
      F prorated by ACTUAL attendance, per activity, from leave-mgmt's activity
      availability feed (GET /api/attendance/report/availability/activity). Each
      activity's completeness fraction is the BINDING (worst) of the measures the
      project's SLA007 configures — HOURS (Σ working-hours ÷ (planned-resource-
      months × hours-target)) AND/OR BUSINESS-DAYS (Σ days ÷ (planned-resource-
      months × days-target)); the per-resource-month targets are SLA007's own
      ``target_numeric`` values (RFP §5.28.3.e = 144 h / 16 d). PA = Σ (F_activity
      × fraction) ≤ F. Hard-sourced: when an in-quarter activity's attendance
      can't be read, the settlement BLOCKS rather than mis-paying.

QGR = per-project × phase amount from project.project_qgr_config.
      Cross-schema read (same DB, PMIS-project-management owns the writes).
      When no effective row exists → 0.

NPQP = F + QGR is a DELETED-clause reference only (§5.28.1.d.e was deleted by the
       corrigendum). It is computed/stored for display/audit but is NOT the LD
       base: LD is calculated on PQP (= F) and deducted from PA (§5.28.1.f/h) —
       that's why F and PA must NOT collapse into one number.

Consumed by:
  * QuarterlySettlementService.close (Phase D) — needs F for the LD %
    base, PA for the deduction line, both.
  * GET /api/v3/npqp/projects/{id}?quarter=... — audit / FE.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.clients.leave_management_client import LeaveManagementClient
from app.schemas.npqp import NpqpResourceCost, NpqpResponse
from app.utilities.logger import get_logger
from app.utilities.quarter import QuarterKey


logger = get_logger(__name__)

# RFP §5.28.3.e resource-availability minimums — the per-resource-month full-time
# basis PA prorates against. Sourced from the project's SLA007 metric targets
# (``resource_logged_hours`` / ``resource_business_days``); these RFP defaults are
# used ONLY when a project defines NEITHER target.
_DEFAULT_HOURS_TARGET = Decimal("144")
_DEFAULT_DAYS_TARGET = Decimal("16")

_HRS_METRIC = "resource_logged_hours"
_BD_METRIC = "resource_business_days"


def _num(v: Any) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (ArithmeticError, ValueError):
        return None


def _parse_date(v: Any) -> Optional[date]:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


class NpqpService:
    def __init__(
        self,
        db: Session,
        leave_client: Optional[LeaveManagementClient] = None,
    ):
        self.db = db
        self.leave_client = leave_client or LeaveManagementClient()

    # ------------------------------------------------------------------ QGR

    def _qgr_for(self, project_id: str, quarter_end: date) -> Decimal:
        """QGR active on ``quarter_end``. Cross-schema SELECT into project.*.

        We sum across all rows whose window covers the quarter's end date
        — normally 0 or 1 row, but a project could stack multiple phases
        (Phase 1 QGR + Phase 2 QGR) if the RFP schedule ever calls for it.
        """
        result = self.db.execute(
            text("""
                SELECT COALESCE(SUM(qgr_amount_per_quarter), 0) AS qgr
                  FROM project.project_qgr_config
                 WHERE project_id = :pid
                   AND effective_from <= :qend
                   AND (effective_until IS NULL OR effective_until >= :qend)
            """),
            {"pid": project_id, "qend": quarter_end},
        ).scalar()
        return Decimal(str(result or 0))

    # ------------------------------------------------------------------ F (planned)
    #
    # RFP §5.28.1.d.c definition of F — "aggregate of monthly payment of all
    # resources to be deployed as per resource deployment plan". Read from
    # project.activity_planned_resources — the SAME per-activity plan the
    # finance / payment page uses (the Java designation rate is snapshotted onto
    # each allocation at write time). Each allocation's ``computed_cost`` =
    # quantity × monthly_rate × duration (a flat month count within one quarter),
    # so F is the quarter's actual PLANNED spend and reconciles with finance.
    #
    # Historical note: F previously read ``leave.project_resource``. That was the
    # planned source in the July-2026 consolidation, but resource costing was
    # later re-architected onto ``project.activity_planned_resources``; leave now
    # supplies ONLY the ACTUAL side — attendance → PA below. The old leave table
    # had no assignment end dates, so it counted every resource in every quarter
    # indefinitely, inflating F far beyond the contract value.

    def _compute_planned_f(
        self, project_id: str, qk: QuarterKey,
    ) -> Tuple[Decimal, List[NpqpResourceCost], Dict[str, Dict[str, Decimal]]]:
        """(F_total, per-allocation planned rows) for the quarter, read from the
        project's resource deployment plan (``project.activity_planned_resources``).

        F = Σ ``computed_cost`` of every allocation whose ACTIVITY sits in this
        quarter — i.e. the activity's IST start date falls in
        ``[qk.quarter_start, qk.quarter_end]`` (the project-anchored bounds, so F
        follows PROJECT quarters, not the calendar). Bucketing by the ACTIVITY's
        quarter — not the row's ``planned_deployment_date`` — keeps F on the SAME
        quarter as that activity's SLA rollup (the activity is the quarter-proxy);
        a deployment date a day either side of a quarter boundary can't split a
        resource away from its activity's quarter. ``computed_cost`` is the
        snapshot finance stores (quantity × monthly_rate × duration); when NULL the
        product is recomputed. Soft-deleted rows are excluded.
        """
        rows = self.db.execute(
            text(
                """
                SELECT apr.activity_id,
                       apr.designation,
                       apr.quantity,
                       apr.monthly_rate,
                       apr.duration,
                       apr.computed_cost,
                       apr.planned_deployment_date
                  FROM project.activity_planned_resources apr
                  JOIN project.activities a ON a.id = apr.activity_id
                 WHERE apr.project_id = :pid
                   AND apr.deleted_at IS NULL
                   AND a.deleted_at IS NULL
                   AND (a.start_date AT TIME ZONE 'Asia/Kolkata')::date
                       BETWEEN :qstart AND :qend
                """
            ),
            {"pid": project_id, "qstart": qk.quarter_start, "qend": qk.quarter_end},
        ).all()

        f_total = Decimal("0")
        per_alloc: List[NpqpResourceCost] = []
        # Per-activity aggregates for PA: F_activity and planned resource-months
        # (Σ quantity × duration) — the denominator PA prorates attendance against.
        by_activity: Dict[str, Dict[str, Decimal]] = {}
        for r in rows:
            if r.computed_cost is not None:
                cost = Decimal(str(r.computed_cost))
            else:
                # Snapshot missing → recompute from the row (matches finance's formula).
                rate = Decimal(str(r.monthly_rate or 0))
                cost = rate * Decimal(str(r.quantity or 0)) * Decimal(str(r.duration or 0))
            months = Decimal(str(r.quantity or 0)) * Decimal(str(r.duration or 0))
            f_total += cost
            agg = by_activity.setdefault(
                r.activity_id, {"f": Decimal("0"), "months": Decimal("0")},
            )
            agg["f"] += cost
            agg["months"] += months
            d = r.planned_deployment_date
            per_alloc.append(NpqpResourceCost(
                # A planned allocation is by DESIGNATION, not a named resource.
                resource_id="",
                employee_name=r.designation,
                year=d.year, month=d.month,
                monthly_rate=(
                    Decimal(str(r.monthly_rate)) if r.monthly_rate is not None else None
                ),
                cost=cost,
            ))
        return f_total, per_alloc, by_activity

    # ------------------------------------------------------------------ PA (actual)

    def _resolve_availability_targets(
        self, project_id: str,
    ) -> Tuple[Optional[Decimal], Optional[Decimal]]:
        """The per-resource-month full-time targets PA prorates attendance
        against — SLA007's own ``target_numeric`` for hours and/or business-days,
        read from the resource-availability SLA mapped to this project's
        activities. Either may be ``None`` (a project can configure just one, and
        PA then prorates on that single measure). Falls back to the RFP §5.28.3.e
        defaults (144 h / 16 d) only when the project defines NEITHER target."""
        rows = self.db.execute(
            text(
                """
                SELECT m.metric_key, MAX(m.target_numeric) AS target
                  FROM contract.sla_metrics m
                  JOIN contract.sla_activity_mappings sam ON sam.sla_id = m.sla_id
                  JOIN project.activities a ON a.id = sam.activity_id
                 WHERE a.project_id = :pid
                   AND sam.status = 'ACTIVE'
                   AND m.metric_key IN (:hrs, :bd)
                   AND m.target_numeric IS NOT NULL
                 GROUP BY m.metric_key
                """
            ),
            {"pid": project_id, "hrs": _HRS_METRIC, "bd": _BD_METRIC},
        ).all()
        by_key = {r.metric_key: _num(r.target) for r in rows}
        hours_t = by_key.get(_HRS_METRIC)
        days_t = by_key.get(_BD_METRIC)
        if hours_t is None and days_t is None:
            logger.info(
                "NpqpService: project %s has no SLA007 availability target — PA "
                "falling back to RFP defaults (144 h / 16 d).", project_id,
            )
            return _DEFAULT_HOURS_TARGET, _DEFAULT_DAYS_TARGET
        return hours_t, days_t

    def _activity_delivered(
        self,
        project_id: str,
        activity_id: str,
        qk: QuarterKey,
        bearer_token: Optional[str],
    ) -> Optional[Tuple[Decimal, Decimal]]:
        """(Σ working-hours, Σ business-days) actually attended for the activity
        in this quarter — summed across every resource — from the availability
        feed. ``None`` means the attendance could NOT be read (feed unreachable /
        no base-url or bearer / activity unknown → 404 / nothing uploaded for the
        quarter); the caller BLOCKS rather than treating missing data as zero."""
        report = self.leave_client.get_activity_availability(
            project_id, activity_id, bearer_token=bearer_token,
        )
        if not isinstance(report, dict):
            return None
        hours = Decimal("0")
        days = Decimal("0")
        seen = False
        for m in report.get("months") or []:
            fd = _parse_date(m.get("fromDate"))
            if fd is not None and not (qk.quarter_start <= fd <= qk.quarter_end):
                continue  # activity-start-aligned cycle outside this quarter
            seen = True
            hours += _num(m.get("totalWorkingHours")) or Decimal("0")
            days += _num(m.get("totalBusinessDays")) or Decimal("0")
        if not seen:
            return None  # activity known but nothing uploaded for the quarter
        return hours, days

    # ------------------------------------------------------------------ public

    def compute(
        self,
        project_id: str,
        qk: QuarterKey,
        *,
        bearer_token: Optional[str] = None,
    ) -> NpqpResponse:
        # 1. F (planned) — from resource deployment plan. Independent of
        #    leave-mgmt availability; needs only cross-schema DB access.
        f_total, planned_rows, by_activity = self._compute_planned_f(project_id, qk)

        # 2. PA (actual) — HARD SWITCH to the per-activity attendance feed. Each
        #    activity's F is prorated by the BINDING (worst) of the completeness
        #    fractions the project's SLA007 configures: HOURS (Σ working-hours ÷
        #    (planned-resource-months × hours-target)) and/or BUSINESS-DAYS. A
        #    project logging long hours on few days (or many short days) is caught
        #    by whichever fraction is lower. Attendance is activity-linked, so PA
        #    is summed per activity and stays ≤ F. Missing attendance for an
        #    in-quarter activity is NOT treated as zero — it BLOCKS the quarter
        #    (future-month attendance can't be uploaded, so a settle-able quarter
        #    must already carry its actuals).
        hours_target, days_target = self._resolve_availability_targets(project_id)
        pa_total = Decimal("0")
        blocked: List[str] = []
        for activity_id, agg in by_activity.items():
            f_a = agg["f"]
            months_a = agg["months"]
            if f_a <= 0 or months_a <= 0:
                continue  # nothing planned to pay → PA_a = 0, no attendance needed
            delivered = self._activity_delivered(
                project_id, activity_id, qk, bearer_token,
            )
            if delivered is None:
                blocked.append(activity_id)
                continue
            hours, days = delivered
            fracs: List[Decimal] = []
            if hours_target and hours_target > 0:
                fracs.append(hours / (months_a * hours_target))
            if days_target and days_target > 0:
                fracs.append(days / (months_a * days_target))
            if not fracs:
                blocked.append(activity_id)
                continue
            fraction = min([Decimal("1")] + fracs)  # AND: the binding measure, ≤ 1
            pa_total += f_a * fraction
        pa_total = pa_total.quantize(Decimal("0.01"))

        # 3. QGR — from project.project_qgr_config.
        qgr = self._qgr_for(project_id, qk.quarter_end)

        # 4. Status precedence. Any in-quarter activity whose attendance can't be
        #    read blocks the whole quarter — PA would otherwise be understated.
        if not planned_rows:
            status = "no_resources"
        elif blocked:
            status = "attendance_unavailable"
            logger.warning(
                "NpqpService: PA blocked for project=%s %s — attendance "
                "unavailable for activities: %s",
                project_id, qk.label(), ", ".join(sorted(blocked)),
            )
        else:
            status = "ok"

        # ``per_month`` is the audit trail — the PLAN rows (F is the PA base,
        # PA = Σ F_activity × attendance-fraction), so it reconciles with F.
        per_month = planned_rows

        return NpqpResponse(
            project_id=project_id,
            fiscal_year=qk.fiscal_year, quarter=qk.quarter,
            quarter_start=qk.quarter_start, quarter_end=qk.quarter_end,
            f_amount=f_total,
            pa_amount=pa_total,
            qgr_amount=qgr,
            npqp=f_total + qgr,
            status=status,
            per_month=per_month,
        )
