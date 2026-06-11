"""SlaController — orchestrates SlaService, shapes wire responses."""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.schemas.sla import (
    SlaDefinitionResponse,
    SlaDetailResponse,
    SlaDslResponse,
    SlaFromRfpRequest,
    SlaOnboardRequest,
    SlaOnboardResponse,
    SlaUpdateRequest,
)
from app.services.sla_service import SlaService


class SlaController:
    def __init__(self, db: Session):
        self.service = SlaService(db)

    def onboard(
        self, payload: SlaOnboardRequest, created_by: Optional[str] = None
    ) -> SlaOnboardResponse:
        return self.service.create_from_form(payload, created_by=created_by)

    def onboard_from_rfp(
        self, payload: SlaFromRfpRequest, created_by: Optional[str] = None
    ) -> SlaOnboardResponse:
        return self.service.create_from_rfp(payload, created_by=created_by)

    def list_slas(
        self,
        *,
        contract_type: Optional[str] = None,
        formula_type: Optional[str] = None,
        status: Optional[str] = None,
        project_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[SlaDefinitionResponse], int]:
        return self.service.list_slas(
            contract_type=contract_type,
            formula_type=formula_type,
            status=status,
            project_id=project_id,
            skip=skip,
            limit=limit,
        )

    def get(self, sla_id: str) -> SlaDetailResponse:
        # Power-user / debug path — full parsed sub-tables. Reachable via
        # GET /sla-masters/{id}/parsed.
        return self.service.get_detail(sla_id)

    def get_rfp_view(self, sla_id: str):
        # Default user-facing path — RFP-friendly shape (no metric_key,
        # no sort_order, no formula_type). Reachable via
        # GET /sla-masters/{id}.
        return self.service.get_rfp_view(sla_id)

    def get_dsl(self, sla_id: str) -> SlaDslResponse:
        return self.service.get_dsl(sla_id)

    def update(self, sla_id: str, payload: SlaUpdateRequest) -> SlaDetailResponse:
        return self.service.update_basic(sla_id, payload)

    def delete(self, sla_id: str) -> SlaDefinitionResponse:
        return self.service.soft_delete(sla_id)

    def seed_defaults(
        self,
        contract_types: Optional[List[str]] = None,
        created_by: Optional[str] = None,
        overwrite: bool = False,
        project_id: Optional[str] = None,
    ) -> dict:
        return self.service.seed_default_slas(
            contract_types, created_by=created_by, overwrite=overwrite,
            project_id=project_id,
        )
