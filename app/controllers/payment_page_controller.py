"""PaymentPageController — thin orchestration over PaymentPageService for the
aggregated page, the per-phase QRG flag, and the CCN cap update."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.schemas.payment import CycleCountResponse, PaymentPageResponse
from app.services.payment_page_service import PaymentPageService
from app.utilities import cycle_calc
from app.utilities.timezones import IST


def _ist_date(dt: datetime) -> date:
    """Calendar date of ``dt`` in IST — matches the project's IST-everywhere
    convention (tz-aware inputs are converted before the date is taken, so a
    UTC instant that is already 'tomorrow' in IST buckets correctly)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(IST)
    return dt.date()


class PaymentPageController:
    def __init__(self, db: Session):
        self.db = db
        self.service = PaymentPageService(db)

    def get_page(self, project_id: str) -> PaymentPageResponse:
        return self.service.build_page(project_id)

    def set_qrg(
        self, project_id: str, phase: int, applied: bool, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        return self.service.set_qrg(
            project_id, phase, applied,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )

    def update_ccn_cap(
        self, project_id: str, ccn_cap_percent: Decimal, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        return self.service.update_ccn_cap(
            project_id, ccn_cap_percent,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )

    def cycle_count(
        self, start_date: datetime, end_date: datetime, frequency: str,
    ) -> CycleCountResponse:
        """Number of FY-aligned billing cycles between two dates (stateless).

        Dates are ``datetime`` on the wire (same type milestones/projects use);
        we normalize to the IST calendar date before counting.
        """
        return CycleCountResponse(
            cycles=cycle_calc.count_cycles(
                _ist_date(start_date), _ist_date(end_date), frequency,
            ),
        )
