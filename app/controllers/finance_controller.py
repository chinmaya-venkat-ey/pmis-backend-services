"""FinanceController — thin orchestration over FinanceService."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.schemas.finance import FinanceSummaryResponse, FinanceUpdateRequest
from app.services.finance_service import FinanceService


class FinanceController:
    def __init__(self, db: Session):
        self.db = db
        self.service = FinanceService(db)

    def get(self, project_id: str) -> FinanceSummaryResponse:
        return self.service.summary(project_id)

    def update(
        self,
        project_id: str,
        payload: FinanceUpdateRequest,
        *, caller_user_id: Optional[str],
    ) -> FinanceSummaryResponse:
        return self.service.update(
            project_id, payload, caller_user_id=caller_user_id,
        )
