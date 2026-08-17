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
      Sourced from leave-mgmt via GET /api/attendance/cost/monthly. That
      endpoint already folds paid-leave, half-day, and RFP §5.24.1
      relaxation into the ``cost`` field, so we just sum. PA ≤ F when
      actual attendance falls short of planned.

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
from typing import List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.clients.leave_management_client import LeaveManagementClient
from app.schemas.npqp import NpqpResourceCost, NpqpResponse
from app.utilities.logger import get_logger
from app.utilities.quarter import QuarterKey


logger = get_logger(__name__)


def _months_of_quarter(qk: QuarterKey) -> List[Tuple[int, int]]:
    """Return the three (year, month) pairs that comprise the quarter."""
    start = qk.quarter_start
    out: List[Tuple[int, int]] = []
    y, m = start.year, start.month
    for _ in range(3):
        out.append((y, m))
        m += 1
        if m > 12:
            m = 1; y += 1
    return out


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
    ) -> Tuple[Decimal, List[NpqpResourceCost]]:
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
                SELECT apr.designation,
                       apr.quantity,
                       apr.monthly_rate,
                       apr.duration,
                       apr.computed_cost,
                       apr.planned_deployment_date
                  FROM project.activity_planned_resources apr
                  JOIN project.activities a ON a.id = apr.activity_id
                 WHERE apr.project_id = :pid
                   AND apr.deleted_at IS NULL
                   AND (a.start_date AT TIME ZONE 'Asia/Kolkata')::date
                       BETWEEN :qstart AND :qend
                """
            ),
            {"pid": project_id, "qstart": qk.quarter_start, "qend": qk.quarter_end},
        ).all()

        f_total = Decimal("0")
        per_alloc: List[NpqpResourceCost] = []
        for r in rows:
            if r.computed_cost is not None:
                cost = Decimal(str(r.computed_cost))
            else:
                # Snapshot missing → recompute from the row (matches finance's formula).
                rate = Decimal(str(r.monthly_rate or 0))
                cost = rate * Decimal(str(r.quantity or 0)) * Decimal(str(r.duration or 0))
            f_total += cost
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
        return f_total, per_alloc

    # ------------------------------------------------------------------ PA (actual)

    def _fetch_month_cost(
        self,
        project_id: str,
        year: int,
        month: int,
        bearer_token: Optional[str] = None,
    ) -> Tuple[Optional[Decimal], List[NpqpResourceCost]]:
        """One month → (F_month, per-resource rows). None means leave-mgmt
        returned nothing / errored — caller must not proceed with a partial F."""
        rows = self.leave_client.get_monthly_cost(
            project_id, year, month, bearer_token=bearer_token,
        )
        if rows is None:
            return None, []
        f_month = Decimal("0")
        per_month: List[NpqpResourceCost] = []
        for r in rows:
            try:
                cost = Decimal(str(r.get("cost") or 0))
            except (ValueError, ArithmeticError):
                cost = Decimal("0")
            f_month += cost
            per_month.append(NpqpResourceCost(
                resource_id=str(r.get("attendanceId") or r.get("resourceId") or ""),
                employee_name=r.get("employeeName"),
                year=year, month=month,
                monthly_rate=(
                    Decimal(str(r["monthlyRate"])) if r.get("monthlyRate") is not None else None
                ),
                cost=cost,
            ))
        return f_month, per_month

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
        f_total, planned_rows = self._compute_planned_f(project_id, qk)

        # 2. PA (actual) = the planned F prorated by the project's ATTENDANCE
        #    RATIO from leave-mgmt (Σ attendance-folded cost ÷ Σ planned rate over
        #    the leave-tracked resources). F comes from the activity PLAN and the
        #    leave roster is a DIFFERENT resource set (no designation→person link),
        #    so leave is used only as an attendance FACTOR against the plan — never
        #    as an absolute cost. Summing the leave roster directly (the old
        #    behaviour) made PA follow the often-stale/larger leave roster and
        #    exceed the planned/finance value; proration keeps PA ≤ F and reconciled
        #    with finance while still reflecting actual attendance. When leave can't
        #    answer, PA is unknown and the settlement blocks.
        leave_actual = Decimal("0")   # Σ attendance-folded cost from leave
        leave_planned = Decimal("0")  # Σ planned monthly rate from leave (ratio base)
        actual_rows: List[NpqpResourceCost] = []
        leave_ok = True
        for (year, month) in _months_of_quarter(qk):
            pa_month, rows = self._fetch_month_cost(
                project_id, year, month, bearer_token=bearer_token,
            )
            if pa_month is None:
                leave_ok = False
                logger.warning(
                    "NpqpService: leave-mgmt returned nothing for project=%s "
                    "%d-%02d — PA for that month unknown.",
                    project_id, year, month,
                )
                continue
            leave_actual += pa_month
            for r in rows:
                if r.monthly_rate is not None:
                    leave_planned += Decimal(str(r.monthly_rate))
            actual_rows.extend(rows)

        pa_total = Decimal("0")
        attendance_ratio: Optional[Decimal] = None
        if leave_ok:
            if leave_planned > 0:
                # actual ≤ planned → clamp the ratio to [0, 1].
                attendance_ratio = min(
                    Decimal("1"), max(Decimal("0"), leave_actual / leave_planned),
                )
            else:
                # leave reachable but no rate data → assume full attendance.
                attendance_ratio = Decimal("1")
            pa_total = (f_total * attendance_ratio).quantize(Decimal("0.01"))

        # 3. QGR — from project.project_qgr_config.
        qgr = self._qgr_for(project_id, qk.quarter_end)

        # 4. Status precedence: no deployment plan is worse than no
        #    leave-mgmt (we can't even compute F, so LD % has nothing
        #    to multiply). No planned rows AND no leave data → the
        #    project simply has no staffing this quarter.
        if not planned_rows and not actual_rows:
            status = "no_resources"
        elif not planned_rows:
            status = "no_deployment_plan"
        elif not leave_ok:
            status = "leave_mgmt_unavailable"
        else:
            status = "ok"

        # ``per_month`` is the audit trail — the PLAN rows (F is now the PA base,
        # PA = F × attendance_ratio), so the breakdown reconciles with F and PA.
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
