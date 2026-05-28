"""SlaController — orchestrates SlaService, shapes wire responses."""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.schemas.sla import (
    SlaDefinitionResponse,
    SlaDetailResponse,
    SlaDslResponse,
    SlaOnboardRequest,
    SlaUpdateRequest,
)
from app.services.sla_service import SlaService


class SlaController:
    def __init__(self, db: Session):
        self.service = SlaService(db)

    def onboard(
        self, payload: SlaOnboardRequest, created_by: Optional[str] = None
    ) -> SlaDetailResponse:
        return self.service.create_from_form(payload, created_by=created_by)

    def list_slas(
        self,
        *,
        contract_type: Optional[str] = None,
        formula_type: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[SlaDefinitionResponse], int]:
        return self.service.list_slas(
            contract_type=contract_type,
            formula_type=formula_type,
            status=status,
            skip=skip,
            limit=limit,
        )

    def get(self, sla_id: str) -> SlaDetailResponse:
        return self.service.get_detail(sla_id)

    def get_dsl(self, sla_id: str) -> SlaDslResponse:
        return self.service.get_dsl(sla_id)

    def update(self, sla_id: str, payload: SlaUpdateRequest) -> SlaDetailResponse:
        return self.service.update_basic(sla_id, payload)

    def delete(self, sla_id: str) -> SlaDefinitionResponse:
        return self.service.soft_delete(sla_id)
