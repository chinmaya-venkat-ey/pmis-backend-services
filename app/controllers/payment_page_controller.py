"""PaymentPageController — thin orchestration over PaymentPageService for the
aggregated page, the per-phase QRG flag, and the CCN cap update."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.schemas.payment import PaymentPageResponse, QrgResponse
from app.services.payment_page_service import PaymentPageService


class PaymentPageController:
    def __init__(self, db: Session):
        self.db = db
        self.service = PaymentPageService(db)

    def get_page(self, project_id: str) -> PaymentPageResponse:
        return self.service.build_page(project_id)

    def set_qrg(
        self, project_id: str, phase: int, applied: bool, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> QrgResponse:
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
