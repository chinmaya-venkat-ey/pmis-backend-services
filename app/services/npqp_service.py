"""NpqpService — Phase C.

Computes NPQP = F + QGR for a project × quarter.

F  = Σ (per-resource per-month "cost") across the 3 months of the quarter.
     Sourced from leave-mgmt via GET /api/attendance/cost/monthly. That
     endpoint already folds paid-leave, half-day, and RFP §5.24.1
     relaxation into the ``cost`` field, so we just sum.

QGR = per-project × phase amount from project.project_qgr_config.
      Cross-schema read (same DB, PMIS-project-management owns the writes).
      When no effective row exists → 0.

Consumed by:
  * QuarterlySettlementService.close (Phase D) — for the "capped LD × NPQP"
    money calculation.
  * GET /api/v3/npqp/projects/{id}?quarter=... — audit / FE.
"""
from __future__ import annotations

from datetime import date, timedelta
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

    # ------------------------------------------------------------------ F

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
        f_total = Decimal("0")
        per_month: List[NpqpResourceCost] = []
        leave_ok = True
        for (year, month) in _months_of_quarter(qk):
            f_month, rows = self._fetch_month_cost(
                project_id, year, month, bearer_token=bearer_token,
            )
            if f_month is None:
                # Leave-mgmt didn't answer for this month. Record but keep going
                # so the audit response shows WHICH month failed.
                leave_ok = False
                logger.warning(
                    "NpqpService: leave-mgmt returned nothing for project=%s "
                    "%d-%02d — F for that month treated as unknown.",
                    project_id, year, month,
                )
                continue
            f_total += f_month
            per_month.extend(rows)

        qgr = self._qgr_for(project_id, qk.quarter_end)
        status = "ok"
        if not leave_ok:
            status = "leave_mgmt_unavailable"
        elif not per_month:
            status = "no_resources"

        return NpqpResponse(
            project_id=project_id,
            fiscal_year=qk.fiscal_year, quarter=qk.quarter,
            quarter_start=qk.quarter_start, quarter_end=qk.quarter_end,
            f_amount=f_total,
            qgr_amount=qgr,
            npqp=f_total + qgr,
            status=status,
            per_month=per_month,
        )
