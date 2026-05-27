"""ContractService — business logic for contracts and phases."""
from __future__ import annotations

from typing import List, Optional, Tuple
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.errors import (
    ContractNotFoundError,
    ConflictError,
    PhaseNotFoundError,
)
from app.models.contract import Contract
from app.models.contract_phase import ContractPhase
from app.repositories.contract_repository import ContractRepository
from app.schemas.contract import (
    ContractCreateRequest,
    ContractUpdateRequest,
    PhaseCreateRequest,
    PhaseUpdateRequest,
)


class ContractService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ContractRepository(db)

    # ---------------------------------------------------------------- contracts

    def get_by_id(self, contract_id: str) -> Contract:
        row = self.repo.get_by_id(contract_id)
        if row is None:
            raise ContractNotFoundError(f"Contract '{contract_id}' not found")
        return row

    def list_(
        self,
        *,
        offset: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        vendor_name: Optional[str] = None,
    ) -> Tuple[List[Contract], int]:
        return self.repo.list_(
            offset=offset,
            page_size=page_size,
            status=status,
            vendor_name=vendor_name,
        )

    def create(
        self, payload: ContractCreateRequest, *, caller_user_id: Optional[str]
    ) -> Contract:
        if self.repo.get_by_ref(payload.contract_ref) is not None:
            raise ConflictError(
                f"Contract with ref '{payload.contract_ref}' already exists",
                code="duplicate_contract_ref",
            )
        contract = Contract(
            id=str(uuid4()),
            contract_ref=payload.contract_ref,
            title=payload.title,
            vendor_name=payload.vendor_name,
            start_date=payload.start_date,
            end_date=payload.end_date,
            total_value=payload.total_value,
            currency=payload.currency,
            quarterly_ld_cap_percent=payload.quarterly_ld_cap_percent,
            metadata_=payload.metadata,
            created_by=caller_user_id,
        )
        return self.repo.create(contract)

    def update(
        self,
        contract_id: str,
        payload: ContractUpdateRequest,
        *,
        caller_user_id: Optional[str],
    ) -> Contract:
        contract = self.get_by_id(contract_id)
        updates = payload.model_dump(exclude_unset=True)
        # schema uses "metadata" but model column is "metadata_"
        if "metadata" in updates:
            updates["metadata_"] = updates.pop("metadata")
        if not updates:
            return contract
        return self.repo.update(contract, **updates)

    # ---------------------------------------------------------------- phases

    def get_phase(self, contract_id: str, phase_id: str) -> ContractPhase:
        self.get_by_id(contract_id)  # ensure contract exists
        phase = self.repo.get_phase_by_id(phase_id)
        if phase is None or phase.contract_id != contract_id:
            raise PhaseNotFoundError(
                f"Phase '{phase_id}' not found on contract '{contract_id}'"
            )
        return phase

    def list_phases(
        self, contract_id: str, *, active_only: bool = False
    ) -> List[ContractPhase]:
        self.get_by_id(contract_id)
        return self.repo.list_phases(contract_id, active_only=active_only)

    def create_phase(
        self, contract_id: str, payload: PhaseCreateRequest
    ) -> ContractPhase:
        self.get_by_id(contract_id)
        phase = ContractPhase(
            id=str(uuid4()),
            contract_id=contract_id,
            phase_name=payload.phase_name,
            start_date=payload.start_date,
            end_date=payload.end_date,
            is_active=payload.is_active,
        )
        return self.repo.create_phase(phase)

    def update_phase(
        self, contract_id: str, phase_id: str, payload: PhaseUpdateRequest
    ) -> ContractPhase:
        phase = self.get_phase(contract_id, phase_id)
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return phase
        return self.repo.update_phase(phase, **updates)
