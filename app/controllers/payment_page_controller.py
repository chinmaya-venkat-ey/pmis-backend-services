"""PaymentPageController — thin orchestration over PaymentPageService for the
aggregated page, the per-phase QRG flag, and the CCN cap update."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.schemas.payment import CycleCountResponse, PaymentPageResponse
from app.services.payment_page_service import PaymentPageService
from app.utilities import cycle_calc


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

    def set_phase_frequency(
        self, project_id: str, phase: int, frequency_code: str, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        return self.service.set_phase_frequency(
            project_id, phase, frequency_code,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )

    def cycle_count(
        self, start_date: datetime, end_date: datetime, frequency: str,
    ) -> CycleCountResponse:
        """Number of FY-aligned billing cycles between two dates (stateless).

        Dates are ``datetime`` on the wire (same type milestones/projects use);
        the calc normalizes to the IST calendar date before counting.
        """
        return CycleCountResponse(
            cycles=cycle_calc.count_cycles_from_datetimes(start_date, end_date, frequency),
        )
