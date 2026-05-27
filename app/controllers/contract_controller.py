"""ContractController — orchestrates ContractService, shapes wire responses."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.schemas.contract import (
    ContractCreateRequest,
    ContractListResponse,
    ContractResponse,
    ContractUpdateRequest,
    PhaseCreateRequest,
    PhaseResponse,
    PhaseUpdateRequest,
)
from app.services.contract_service import ContractService


class ContractController:
    def __init__(self, db: Session):
        self.service = ContractService(db)

    # ---------------------------------------------------------------- contracts

    def get(self, contract_id: str) -> ContractResponse:
        row = self.service.get_by_id(contract_id)
        return ContractResponse.from_orm(row)

    def list_(
        self,
        *,
        offset: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        vendor_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        rows, total = self.service.list_(
            offset=offset,
            page_size=page_size,
            status=status,
            vendor_name=vendor_name,
        )
        return {
            "items": [ContractResponse.from_orm(r) for r in rows],
            "total": total,
            "offset": offset,
            "page_size": page_size,
        }

    def create(
        self, payload: ContractCreateRequest, *, caller_user_id: Optional[str]
    ) -> ContractResponse:
        row = self.service.create(payload, caller_user_id=caller_user_id)
        return ContractResponse.from_orm(row)

    def update(
        self,
        contract_id: str,
        payload: ContractUpdateRequest,
        *,
        caller_user_id: Optional[str],
    ) -> ContractResponse:
        row = self.service.update(contract_id, payload, caller_user_id=caller_user_id)
        return ContractResponse.from_orm(row)

    # ---------------------------------------------------------------- phases

    def get_phase(self, contract_id: str, phase_id: str) -> PhaseResponse:
        phase = self.service.get_phase(contract_id, phase_id)
        return PhaseResponse.model_validate(phase)

    def list_phases(
        self, contract_id: str, *, active_only: bool = False
    ) -> List[PhaseResponse]:
        phases = self.service.list_phases(contract_id, active_only=active_only)
        return [PhaseResponse.model_validate(p) for p in phases]

    def create_phase(
        self, contract_id: str, payload: PhaseCreateRequest
    ) -> PhaseResponse:
        phase = self.service.create_phase(contract_id, payload)
        return PhaseResponse.model_validate(phase)

    def update_phase(
        self, contract_id: str, phase_id: str, payload: PhaseUpdateRequest
    ) -> PhaseResponse:
        phase = self.service.update_phase(contract_id, phase_id, payload)
        return PhaseResponse.model_validate(phase)
