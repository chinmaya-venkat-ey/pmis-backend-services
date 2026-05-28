"""MasterController — orchestrates MasterService, shapes wire responses."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.schemas.master import (
    ContractTypeCreateRequest,
    ContractTypeResponse,
    ContractTypeUpdateRequest,
    DataFieldResponse,
    FormulaLibraryResponse,
    SeverityLevelResponse,
    SeverityLevelUpdateRequest,
    SeverityMasterSetRequest,
)
from app.services.master_service import MasterService


class MasterController:
    def __init__(self, db: Session):
        self.service = MasterService(db)

    def list_contract_types(self) -> List[ContractTypeResponse]:
        return [ContractTypeResponse.model_validate(r) for r in self.service.list_contract_types()]

    def create_contract_type(self, payload: ContractTypeCreateRequest) -> ContractTypeResponse:
        return ContractTypeResponse.model_validate(self.service.create_contract_type(payload))

    def update_contract_type(
        self, code: str, payload: ContractTypeUpdateRequest
    ) -> ContractTypeResponse:
        return ContractTypeResponse.model_validate(self.service.update_contract_type(code, payload))

    def delete_contract_type(self, code: str) -> ContractTypeResponse:
        return ContractTypeResponse.model_validate(self.service.delete_contract_type(code))

    def list_formula_library(self) -> List[FormulaLibraryResponse]:
        return [
            FormulaLibraryResponse.from_orm_with_obs_type(r)
            for r in self.service.list_formula_library()
        ]

    def list_data_fields(
        self, *, contract_type: Optional[str] = None
    ) -> List[DataFieldResponse]:
        return [
            DataFieldResponse.model_validate(r)
            for r in self.service.list_data_fields(contract_type=contract_type)
        ]

    def set_severity_levels(
        self, project_id: str, payload: SeverityMasterSetRequest
    ) -> List[SeverityLevelResponse]:
        return [
            SeverityLevelResponse.model_validate(r)
            for r in self.service.set_severity_levels(project_id, payload)
        ]

    def list_severity_levels(self, project_id: str) -> List[SeverityLevelResponse]:
        return [
            SeverityLevelResponse.model_validate(r)
            for r in self.service.list_severity_levels(project_id)
        ]

    def update_severity_level(
        self, project_id: str, level: int, payload: SeverityLevelUpdateRequest
    ) -> SeverityLevelResponse:
        row = self.service.update_severity_level(project_id, level, payload)
        return SeverityLevelResponse.model_validate(row)
