"""PaymentPageController — thin orchestration over PaymentPageService for the
aggregated page, carry-forward, phase order/frequency, per-activity split, and
the CCN cap update."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

from app.schemas.payment import (
    CycleCountResponse,
    PaymentPageResponse,
    PaymentTermResponse,
)
from app.services.payment_page_service import PaymentPageService
from app.utilities import cycle_calc


class PaymentPageController:
    def __init__(self, db: Session):
        self.db = db
        self.service = PaymentPageService(db)

    def get_page(self, project_id: str) -> PaymentPageResponse:
        return self.service.build_page(project_id)

    def validate(self, project_id: str) -> dict:
        return self.service.validate_finance(project_id)

    def set_carry_forward(
        self, project_id: str, phase: str, *,
        enabled: bool, method_code: Optional[str], caller_user_id: Optional[str],
        allocation_mode: Optional[str] = None, allocations: Optional[list] = None,
        caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        return self.service.set_carry_forward(
            project_id, phase, enabled=enabled, method_code=method_code,
            caller_user_id=caller_user_id,
            allocation_mode=allocation_mode, allocations=allocations,
            caller_is_admin=caller_is_admin,
        )

    def set_one_time_allocation(
        self, project_id: str, phase: str, *,
        enabled: bool, mode: Optional[str], value=None,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        return self.service.set_one_time_allocation(
            project_id, phase, enabled=enabled, mode=mode, value=value,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )

    def set_phase_sequence(
        self, project_id: str, phase: str, sequence: int, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        return self.service.set_phase_sequence(
            project_id, phase, sequence,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )

    def set_payment_term_activities(
        self, term_id: str, allocations: List[dict], *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentTermResponse:
        return self.service.set_payment_term_activities(
            term_id, allocations,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )

    def update_ccn_cap(
        self, project_id: str, ccn_cap_percent: Optional[Decimal], *,
        additional_cost_type: Optional[str] = None,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        return self.service.update_ccn_cap(
            project_id, ccn_cap_percent, additional_cost_type=additional_cost_type,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )

    def set_project_frequency(
        self, project_id: str, frequency_code: str, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        return self.service.set_project_frequency(
            project_id, frequency_code,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )

    def set_phase_frequency(
        self, project_id: str, phase: str, frequency_code: str, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        return self.service.set_phase_frequency(
            project_id, phase, frequency_code,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )

    def cycle_count(
        self, start_date: datetime, end_date: datetime, frequency: str,
    ) -> CycleCountResponse:
        """Number of calendar-aligned billing cycles between two dates (stateless).

        Dates are ``datetime`` on the wire (same type milestones/projects use);
        the calc normalizes to the IST calendar date before counting.
        """
        return CycleCountResponse(
            cycles=cycle_calc.count_cycles_from_datetimes(start_date, end_date, frequency),
        )
