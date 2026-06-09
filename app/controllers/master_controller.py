"""MasterController — orchestrates MasterService, shapes wire responses."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.schemas.master import (
    ContractTypeCreateRequest,
    ContractTypeResponse,
    ContractTypeUpdateRequest,
    DataFieldCreateRequest,
    DataFieldResponse,
    DataFieldUpdateRequest,
    FormulaLibraryResponse,
    LdBandResponse,
    LdBandSetRequest,
    LdBandUpdateRequest,
    SeverityLevelResponse,
    SeverityLevelUpdateRequest,
    SeverityMasterSetRequest,
    SlaCategoryResponse,
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

    def list_sla_categories(self) -> List[SlaCategoryResponse]:
        return [SlaCategoryResponse.model_validate(r) for r in self.service.list_sla_categories()]

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

    def create_data_field(self, payload: DataFieldCreateRequest) -> DataFieldResponse:
        return DataFieldResponse.model_validate(self.service.create_data_field(payload))

    def update_data_field(
        self, field_name: str, payload: DataFieldUpdateRequest
    ) -> DataFieldResponse:
        return DataFieldResponse.model_validate(
            self.service.update_data_field(field_name, payload)
        )

    def delete_data_field(self, field_name: str) -> DataFieldResponse:
        return DataFieldResponse.model_validate(self.service.delete_data_field(field_name))

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

    # ------------------------------------------------------------------ project ld bands

    def list_ld_bands(self, project_id: str) -> List[LdBandResponse]:
        return [
            LdBandResponse.model_validate(r)
            for r in self.service.list_ld_bands(project_id)
        ]

    def set_ld_bands(
        self, project_id: str, payload: LdBandSetRequest
    ) -> List[LdBandResponse]:
        return [
            LdBandResponse.model_validate(r)
            for r in self.service.set_ld_bands(project_id, payload)
        ]

    def update_ld_band(
        self, project_id: str, band_id: str, payload: LdBandUpdateRequest
    ) -> LdBandResponse:
        return LdBandResponse.model_validate(
            self.service.update_ld_band(project_id, band_id, payload)
        )

    # ------------------------------------------------------------------ combined seed

    def seed_master_defaults(self, project_id: str):
        return self.service.seed_master_defaults(project_id)
